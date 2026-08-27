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
        righe = await page.evaluate("""
            () => {
                const tabelle = Array.from(document.querySelectorAll('table'));
                for (const t of tabelle) {
                    const intestazioni = Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim());
                    if (!intestazioni.some(h => h.toLowerCase().includes('xg90'))) continue;
                    const idx = {};
                    intestazioni.forEach((h, i) => idx[h.toLowerCase()] = i);
                    const out = [];
                    t.querySelectorAll('tbody tr').forEach(tr => {
                        const celle = Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
                        if (!celle.length) return;
                        out.push({
                            player: celle[idx['player']] ?? null,
                            team: celle[idx['team']] ?? null,
                            apps: celle[idx['apps']] ?? null,
                            min: celle[idx['min']] ?? null,
                            goals: celle[idx['goals']] ?? null,
                            assists: celle[idx['a']] ?? null,
                            xG: celle[idx['xg']] ?? null,
                            xA: celle[idx['xa']] ?? null,
                            xG90: celle[idx['xg90']] ?? null,
                            xA90: celle[idx['xa90']] ?? null,
                        });
                    });
                    if (out.length) return out;
                }
                return [];
            }
        """)

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
            writer = csv.DictWriter(f, fieldnames=["player", "team", "apps", "min", "goals", "assists", "xG", "xA", "xG90", "xA90"])
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
