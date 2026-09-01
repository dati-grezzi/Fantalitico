# -*- coding: utf-8 -*-
"""
FANTALITICO — sonda: dove tiene i tiri, Understat?

CONTESTO
--------
La tabella della pagina di lega espone solo:
    №, Player, Team, Apps, Min, G, A, xG, xA, xG90, xA90
Niente Sh90 né KP90 (verificato dal log dell'1/09/2026). Ma il volume di tiri
è il segnale col peso più alto del bonus performance per gli attaccanti
(beta 0,112), quindi vale la pena cercarlo prima di rinunciare.

Tre posti plausibili, che questo script controlla in ordine:
  1. un JSON incorporato negli script della pagina (Understat storicamente
     usava "playersData" con dentro shots e key_passes come TOTALI);
  2. una chiamata di rete che popola la tabella;
  3. un selettore di colonne nell'interfaccia, che aggiunga Sh90 e KP90.

Se troviamo i TOTALI va benissimo lo stesso, anzi meglio: i per-90 li
calcoliamo noi dividendo per i minuti, senza dipendere da come li arrotonda
il sito.

USO
---
  python understat_esplora.py
Non scrive nulla: stampa e basta.
"""

import asyncio
import json
import re
import sys

from playwright.async_api import async_playwright

URL = "https://understat.com/league/Serie_A/2026"
SPIE = ("shots", "key_passes", "npxG", "xGChain")


async def main_async():
    risposte = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def raccogli(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct and not resp.url.endswith(".json"):
                    return
                corpo = await resp.text()
                if any(s in corpo for s in SPIE):
                    risposte.append((resp.url, len(corpo), corpo[:400]))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(raccogli(r)))

        print(f"Apro {URL} ...")
        await page.goto(URL, wait_until="load", timeout=45000)
        await page.wait_for_timeout(4000)

        # ── 1. JSON incorporato negli script ──────────────────────────────
        print("\n" + "=" * 64)
        print("1. JSON INCORPORATO NEGLI SCRIPT")
        print("=" * 64)
        trovati = await page.evaluate("""
            () => {
                const spie = ['shots', 'key_passes', 'npxG', 'xGChain'];
                const out = [];
                document.querySelectorAll('script').forEach((s, i) => {
                    const t = s.textContent || '';
                    if (!t) return;
                    const presenti = spie.filter(x => t.includes(x));
                    if (!presenti.length) return;
                    const nomi = (t.match(/var\\s+(\\w+)\\s*=/g) || []).slice(0, 6);
                    out.push({indice: i, lunghezza: t.length, spie: presenti,
                              variabili: nomi, estratto: t.slice(0, 500)});
                });
                return out;
            }
        """)
        if trovati:
            for t in trovati:
                print(f"\n  script #{t['indice']} — {t['lunghezza']} caratteri")
                print(f"  contiene: {t['spie']}")
                print(f"  variabili: {t['variabili']}")
                print(f"  estratto: {t['estratto'][:300]!r}")
        else:
            print("  Nessuno script contiene i campi cercati.")

        # ── 2. Chiamate di rete ───────────────────────────────────────────
        print("\n" + "=" * 64)
        print("2. CHIAMATE DI RETE CON QUEI CAMPI")
        print("=" * 64)
        if risposte:
            for url, n, estratto in risposte:
                print(f"\n  {url}  ({n} caratteri)")
                print(f"  {estratto[:300]!r}")
        else:
            print("  Nessuna risposta JSON contiene i campi cercati.")

        # ── 3. Selettore di colonne ───────────────────────────────────────
        print("\n" + "=" * 64)
        print("3. SELETTORE DI COLONNE NELL'INTERFACCIA")
        print("=" * 64)
        controlli = await page.evaluate("""
            () => {
                const out = [];
                const sel = '[class*="option"], [class*="setting"], [class*="column"], [class*="gear"], [class*="filter"], button, .fa, i';
                document.querySelectorAll(sel).forEach(el => {
                    const t = (el.textContent || '').trim().slice(0, 40);
                    const c = typeof el.className === 'string' ? el.className : '';
                    if (!c && !t) return;
                    out.push(el.tagName + ' class="' + c + '" testo="' + t + '"');
                });
                return [...new Set(out)].slice(0, 30);
            }
        """)
        for c in controlli:
            print(f"  {c}")
        if not controlli:
            print("  Nessun controllo riconoscibile.")

        # ── 4. Una pagina giocatore ha i tiri? ────────────────────────────
        print("\n" + "=" * 64)
        print("4. PAGINA DI UN SINGOLO GIOCATORE")
        print("=" * 64)
        link = await page.evaluate(
            "() => { const a = document.querySelector('a[href*=\"/player/\"]');"
            " return a ? a.href : null; }")
        if link:
            print(f"  Provo {link}")
            await page.goto(link, wait_until="load", timeout=45000)
            await page.wait_for_timeout(2500)
            intest = await page.evaluate("""
                () => Array.from(document.querySelectorAll('th'))
                        .map(th => th.textContent.trim()).filter(Boolean).slice(0, 40)
            """)
            print(f"  Intestazioni trovate: {intest}")
            print("  Sh90 presente:", any(h.lower() == 'sh90' for h in intest))
        else:
            print("  Nessun link a pagina giocatore nella tabella.")

        await browser.close()
    print("\nFatto. Incolla tutto l'output.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception as e:
        print(f"Errore: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
