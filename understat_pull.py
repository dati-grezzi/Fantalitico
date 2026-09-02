# -*- coding: utf-8 -*-
"""
FANTALITICO — Understat, statistiche per giocatore (Serie A).

RISCRITTO IL 25/08/2026: il sito è passato da dati incorporati staticamente
nell'HTML (una variabile JS "datesData" che il vecchio script cercava con
una richiesta HTTP semplice) a un caricamento dinamico via JavaScript — la
tabella si popola solo dopo che la pagina carica ed esegue script. Serve
un browser vero (Playwright), non una richiesta HTTP semplice.

In più, la tabella "Players" ora dà già i totali di stagione per giocatore
(presenze, minuti, gol, assist, xG, xA, xG90, xA90) — non serve più
ricostruire tutto sommando partita per partita come nella versione precedente.

USO
---
  pip install playwright
  python -m playwright install chromium
  python understat_pull.py
"""

import asyncio
import csv
import sys
from pathlib import Path
from playwright.async_api import async_playwright

SEASON = "2026"                       # Understat: 2026 = stagione 2026-27
URL = f"https://understat.com/league/Serie_A/{SEASON}"
OUT_CSV = Path(__file__).parent / "understat_players_2026.csv"


async def main_async():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Scaricando {URL} (Playwright, il sito carica i dati via JS)...")
        await page.goto(URL, wait_until="load", timeout=45000)
        await page.wait_for_timeout(2000)

        # La pagina ha più tabelle (classifica squadre, giocatori, portieri...).
        # Cerco quella con le colonne dei giocatori (contiene "xG90" in intestazione).
        def estrai_pagina_corrente():
            return page.evaluate("""
                () => {
                    const tabelle = Array.from(document.querySelectorAll('table'));
                    for (const t of tabelle) {
                        const intestazioni = Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim());
                        if (!intestazioni.some(h => h.toLowerCase().includes('xg90'))) continue;
                        const idx = {};
                        intestazioni.forEach((h, i) => idx[h.toLowerCase()] = i);
                        // Sh90 (tiri per 90') e KP90 (passaggi chiave) servono al bonus
                        // performance del motore: Sh90 è il segnale col peso più alto per
                        // gli attaccanti (beta 0,112). Vanno cercati in modo tollerante
                        // perché l'intestazione può comparire come "Sh90" o "Sh", e se
                        // mancano del tutto il campo resta null invece di rompere la riga.
                        const prendi = (celle, ...nomi) => {
                            for (const n of nomi) {
                                if (idx[n] === undefined) continue;
                                const v = celle[idx[n]];
                                if (v === undefined) continue;
                                const t = String(v).trim();
                                if (t === '' || t === '-') continue;
                                return t;
                            }
                            return null;   // null = non lo sappiamo, non "zero"
                        };
                        const out = [];
                        t.querySelectorAll('tbody tr').forEach(tr => {
                            const celle = Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
                            if (!celle.length) return;
                            // Ogni campo con i suoi nomi possibili. La mappatura
                        // rigida era fragile e sbagliava in silenzio: Understat
                        // intitola i gol "G", non "goals", quindi idx['goals']
                        // era undefined, la cella usciva null e a valle
                        // diventava 0. Esposito F.P. risultava con 0 gol dopo
                        // averne segnato uno (1/09/2026). Stesso difetto sui
                        // tiri. Meglio elencare gli alias: se nessuno combacia
                        // il campo resta null, che a valle viene saltato invece
                        // di essere scambiato per uno zero misurato.
                        out.push({
                                player: prendi(celle, 'player'),
                                team: prendi(celle, 'team'),
                                apps: prendi(celle, 'apps', 'app'),
                                min: prendi(celle, 'min', 'minutes'),
                                goals: prendi(celle, 'g', 'goals'),
                                assists: prendi(celle, 'a', 'assists'),
                                xG: prendi(celle, 'xg'),
                                xA: prendi(celle, 'xa'),
                                xG90: prendi(celle, 'xg90'),
                                xA90: prendi(celle, 'xa90'),
                                sh90: prendi(celle, 'sh90'),
                                kp90: prendi(celle, 'kp90'),
                                npg: prendi(celle, 'npg'),
                                npxg: prendi(celle, 'npxg'),
                                npxg90: prendi(celle, 'npxg90'),
                                xgchain90: prendi(celle, 'xgchain90'),
                                xgbuildup90: prendi(celle, 'xgbuildup90'),
                            });
                        });
                        if (out.length) return out;
                    }
                    return [];
                }
            """)

        # Le colonne spente del selettore valgono piu' di quelle accese: NPxG
        # toglie i rigori dal conteggio (quindi non premia i rigoristi per il
        # solo fatto di batterli), xGChain e xGBuildup misurano il contributo
        # all'azione anche senza tiro ne' assist. Sono gratis: basta spuntarle.
        # NON entrano ancora nel motore — i beta misurati valgono per tiri e
        # xA, non per questi campi. Le raccogliamo ora per poterle calibrare
        # quando ci saranno giornate a sufficienza.
        attivate = await page.evaluate("""
            () => {
                const volute = ['npg','npxg','npxg90','xgchain','xgbuildup','xgchain90','xgbuildup90'];
                const pannelli = document.querySelectorAll('.table-options');
                const p = pannelli[1] || pannelli[0];
                if (!p) return [];
                const fatte = [];
                p.querySelectorAll('.table-options-row').forEach(r => {
                    const et = Array.from(r.childNodes).filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim()).join(' ').trim().toLowerCase();
                    if (!volute.includes(et)) return;
                    const box = r.querySelector('input[type=checkbox]');
                    if (box && !box.checked) { box.click(); fatte.push(et); }
                });
                return fatte;
            }
        """)
        if attivate:
            print(f"   Colonne aggiuntive attivate: {attivate}")
            await page.wait_for_timeout(2500)

        # La tabella "Players" mostra i risultati paginati (visto nello screenshot:
        # controlli "« 1 »" in fondo alla tabella) — raccolgo tutte le pagine,
        # cliccando avanti finché non trovo più un pulsante "successiva" attivo.
        righe = await estrai_pagina_corrente()
        visti = {(r["player"], r["team"]) for r in righe}
        for _ in range(40):  # limite di sicurezza (~319 giocatori / ~11 a pagina ≈ 29)
            cliccato = await page.evaluate("""
                () => {
                    // Cerco un elemento cliccabile "pagina successiva": simbolo »,
                    // freccia, o testo "next" — non disabilitato.
                    const candidati = Array.from(document.querySelectorAll('a, button, span, li'));
                    for (const el of candidati) {
                        const testo = (el.textContent || '').trim();
                        const disabilitato = el.classList.contains('disabled') ||
                            el.closest('.disabled') ||
                            el.getAttribute('aria-disabled') === 'true';
                        if (disabilitato) continue;
                        if (testo === '»' || testo === '›' || testo.toLowerCase() === 'next') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if not cliccato:
                break
            await page.wait_for_timeout(900)
            nuova_pagina = await estrai_pagina_corrente()
            nuove = [r for r in nuova_pagina if (r["player"], r["team"]) not in visti]
            if not nuove:
                break  # la pagina non è cambiata davvero (bottone finto/ultima pagina)
            righe.extend(nuove)
            for r in nuove:
                visti.add((r["player"], r["team"]))

        print(f"Pagine raccolte, totale righe: {len(righe)}")

        intestazioni_viste = await page.evaluate("""
            () => {
                const t = Array.from(document.querySelectorAll('table'))
                    .find(t => Array.from(t.querySelectorAll('th'))
                        .some(th => th.textContent.toLowerCase().includes('xg90')));
                return t ? Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim()) : [];
            }
        """)
        print(f"   Colonne esposte dalla tabella: {intestazioni_viste}")
        for atteso in ('Sh90', 'KP90'):
            if not any(atteso.lower() == h.lower() for h in intestazioni_viste):
                print(f"   ⚠️  Colonna {atteso} NON presente: il campo resterà vuoto")

        if not righe:
            html = await page.content()
            idx = html.find("<table")
            diagnostica = html[max(0, idx-500): idx+5000] if idx >= 0 else html[:5000]
            print("\n⚠️  ATTENZIONE: nessuna tabella giocatori trovata (0 righe).")
            print("\n" + "="*70)
            print("DIAGNOSTICA — HTML reale attorno alla prima <table>:")
            print("="*70)
            print(diagnostica)
            print("="*70)
            await browser.close()
            return 1

        print(f"✅ {len(righe)} giocatori estratti")
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["player", "team", "apps", "min", "goals", "assists", "xG", "xA", "xG90", "xA90", "sh90", "kp90",
                                                    "npg", "npxg", "npxg90", "xgchain90", "xgbuildup90"])
            writer.writeheader()
            writer.writerows(righe)
        print(f"📝 Salvato in {OUT_CSV}")

        await browser.close()
        return 0


def main():
    try:
        return asyncio.run(main_async())
    except Exception as e:
        print(f"\n❌ Errore: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
