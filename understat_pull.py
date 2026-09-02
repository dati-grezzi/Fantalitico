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
        # Non basta un'attesa fissa: la tabella delle SQUADRE compare subito,
        # quella dei GIOCATORI parecchio dopo, e con lei il suo selettore di
        # colonne. Con i 2 secondi di prima il pannello non esisteva ancora e
        # l'attivazione delle colonne extra falliva in silenzio (log del
        # 02/09/2026: la riga "Colonne aggiuntive attivate" non compariva).
        try:
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('th'))
                        .some(th => th.textContent.toLowerCase().includes('xg90'))""",
                timeout=25000)
        except Exception:
            print("   ⚠️  La tabella giocatori non è comparsa entro 25s")
        await page.wait_for_timeout(2500)

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
        # Cerco le righe in TUTTO il documento invece che nel pannello
        # numero 1: l'indice non è affidabile, se la tabella squadre è l'unica
        # renderizzata in quel momento si finisce sul selettore sbagliato, dove
        # queste colonne non esistono (log del 02/09/2026).
        esito = await page.evaluate("""
            () => {
                const volute = ['npg','npxg','npxg90','xgchain','xgbuildup','xgchain90','xgbuildup90'];
                const etichetta = (r) => {
                    const t = r.querySelector('.row-title');
                    return (t ? t.textContent : r.textContent).trim().toLowerCase();
                };
                // Solo il pannello dei GIOCATORI: lo riconosco perche' contiene
                // una riga "xg90", che il pannello delle squadre non ha. Senza
                // questo filtro si spuntavano caselle anche nella tabella
                // squadre (nel log 'npxg' compariva due volte).
                const pannelli = Array.from(document.querySelectorAll('.table-options'));
                const p = pannelli.find(pa => Array.from(pa.querySelectorAll('.table-options-row'))
                                                .some(r => etichetta(r) === 'xg90'));
                if (!p) return {fatte: [], gia: [], righeTotali: 0, viste: [],
                                nota: 'pannello giocatori non trovato'};

                const righe = Array.from(p.querySelectorAll('.table-options-row'));
                const viste = righe.map(etichetta).filter(Boolean);
                const fatte = [], gia = [];
                righe.forEach(r => {
                    const et = etichetta(r);
                    if (!volute.includes(et)) return;
                    const box = r.querySelector('input[type=checkbox]');
                    if (!box) return;
                    if (box.checked) { gia.push(et); return; }
                    // Un clic sull'input via codice non sempre risveglia il
                    // componente: provo prima l'etichetta associata, che e'
                    // cio' che tocca una persona, poi ricado sull'input
                    // emettendo gli eventi che il framework si aspetta.
                    const lab = box.id ? p.querySelector('label[for="' + box.id + '"]') : null;
                    if (lab) lab.click();
                    else {
                        box.click();
                        box.dispatchEvent(new Event('input', {bubbles: true}));
                        box.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    fatte.push(et);
                });
                return {fatte, gia, righeTotali: righe.length, viste, nota: ''};
            }
        """)
        attivate = esito.get("fatte", [])
        if esito.get("gia"):
            print(f"   Colonne già attive: {esito['gia']}")
        if not attivate and not esito.get("gia"):
            print(f"   ⚠️  Nessuna colonna attivata — righe di opzioni trovate: "
                  f"{esito.get('righeTotali', 0)}")
            print(f"      etichette viste: {esito.get('viste', [])[:25]}")
            if esito.get("nota"):
                print(f"      {esito['nota']}")

        if attivate:
            print(f"   Colonne aggiuntive attivate: {attivate}")
            # Attendo che la tabella si ridisegni con le colonne nuove, invece
            # di sperare in una pausa fissa.
            try:
                await page.wait_for_function(
                    """() => Array.from(document.querySelectorAll('th'))
                            .some(th => th.textContent.toLowerCase().includes('xgchain90'))""",
                    timeout=12000)
            except Exception:
                print("   ⚠️  Le colonne nuove non sono comparse nell'intestazione")
            await page.wait_for_timeout(1500)
        else:
            print("   ⚠️  Nessuna colonna aggiuntiva attivata: pannello non trovato")

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
