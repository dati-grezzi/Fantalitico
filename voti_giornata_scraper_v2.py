# -*- coding: utf-8 -*-
"""
VOTI GIORNATA — Scraper (v3: pagina generale con le 3 fonti)

CAMBIO IMPORTANTE (24/08/2026): la pagina giusta è quella generale
"voti-fantacalcio-serie-a", che mostra TUTTE e 10 le partite della giornata
in una sola pagina, con una tabella per squadra che riporta Voto e Fantavoto
di 3 fonti diverse (redazione Fantacalcio, voto statistico, voto Italia) più
Bonus/Malus. Prendiamo le prime due colonne (V e FV della prima fonte,
"Redazione Fantacalcio") come da indicazione esplicita.

Non serve più il match_id delle singole partite (né quindi
data/calendario_storico.json per questo script specifico) — un solo
caricamento di pagina copre tutta la giornata.

NOTA ONESTA: la struttura DOM interna esatta di QUESTA tabella (classi CSS
delle celle V/FV) non è stata ancora verificata su dati reali — è un
tentativo ragionato (righe ripetute per giocatore, prime due celle numeriche
= V e FV) con diagnostica ampia in caso di fallimento, stessa disciplina
di sempre: se fallisce, l'HTML vero finisce nel log per correggere i
selettori in un solo giro invece di continuare a indovinare.

USO
---
  pip install playwright
  python -m playwright install chromium
  python voti_giornata_scraper_v2.py [giornata]
"""

import asyncio
import json
import re
import sys
import os
from playwright.async_api import async_playwright

SEASON = "2026-27"
GIORNATA = int(sys.argv[1]) if len(sys.argv) > 1 else 1
os.makedirs("data", exist_ok=True)
OUT_JSON = f"data/voti_giornata_{GIORNATA}.json"

URL = f"https://www.fantacalcio.it/voti-fantacalcio-serie-a/{SEASON}/{GIORNATA}"


async def scarica_pagina_giornata():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"📡 {URL}")
        await page.goto(URL, wait_until="load", timeout=45000)
        await page.wait_for_timeout(1000)

        # Scroll di sicurezza (stesso pattern già validato su altre pagine di
        # questo sito, che caricano contenuti solo quando entrano in viewport)
        altezza = await page.evaluate("document.body.scrollHeight")
        y, step, i = 0, 1200, 0
        while y < altezza and i < 30:   # pagina lunga, 20 tabelle squadra: più iterazioni
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(250)
            y += step; i += 1
            altezza = await page.evaluate("document.body.scrollHeight")
        await page.wait_for_timeout(1000)

        # Tentativo di estrazione ragionato: per ogni riga-giocatore, prendo le
        # prime due celle che contengono un numero (virgola o punto decimale)
        # come Voto e Fantavoto della prima fonte (Redazione Fantacalcio).
        data = await page.evaluate("""
            () => {
                const numRe = /^\\d{1,2}([.,]\\d)?$/;
                const teams = [];
                document.querySelectorAll('[class*="team"]').forEach(() => {});  // no-op, solo per chiarezza

                // Ogni blocco squadra: cerco contenitori con un'intestazione nome
                // squadra seguita da righe giocatore (link a /squadre/.../ID)
                document.querySelectorAll('a[href*="/serie-a/squadre/"]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/squadre\\/([a-z0-9\\-]+)\\/([a-z0-9\\-]+)\\/(\\d+)$/);
                    if (!m) return;   // non è un link giocatore (es. link squadra generico)
                    const teamSlug = m[1], playerId = m[3];
                    const name = a.textContent.trim();
                    if (!name) return;

                    // Risalgo al contenitore riga (il player-name è quasi sempre
                    // dentro una riga/li/tr che contiene anche i voti accanto)
                    let riga = a.closest('tr, li, .player-row, [class*="row"]') || a.parentElement;
                    if (!riga) return;

                    // Cerco celle numeriche nella riga (voto/fantavoto), scartando
                    // il testo del link stesso
                    const testiCelle = Array.from(riga.querySelectorAll('td, div, span'))
                        .map(el => el.textContent.trim())
                        .filter(t => numRe.test(t));

                    if (testiCelle.length >= 2) {
                        teams.push({
                            team_slug: teamSlug, player_id: playerId, name,
                            voto: testiCelle[0], fantavoto: testiCelle[1]
                        });
                    }
                });
                return teams;
            }
        """)

        diagnostica = None
        if not data:
            html = await page.content()
            idx = -1
            for chiave in ["Voto e Fantavoto", "player-grade", "grades-table", "Redazione Fantacalcio"]:
                idx = html.find(chiave)
                if idx >= 0:
                    break
            if idx >= 0:
                diagnostica = html[max(0, idx-500): idx+4000]
            else:
                idx_body = html.find("<body")
                diagnostica = html[idx_body: idx_body+6000] if idx_body >= 0 else html[:6000]

        await browser.close()
        return data, diagnostica


def main():
    try:
        data, diagnostica = asyncio.run(scarica_pagina_giornata())
    except Exception as e:
        print(f"\n❌ Errore: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if not data:
        print("\n⚠️  ATTENZIONE: 0 giocatori estratti.")
        if diagnostica:
            print("\n" + "="*70)
            print("DIAGNOSTICA — HTML reale:")
            print("="*70)
            print(diagnostica)
            print("="*70)
        return 1

    print(f"✅ {len(data)} giocatori estratti\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"📝 Salvato in {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
