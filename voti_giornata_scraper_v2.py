# -*- coding: utf-8 -*-
"""
VOTI GIORNATA — Scraper (riscritto: schema URL cambiato)

CAMBIO STRUTTURALE IMPORTANTE (scoperto 24/08/2026): fantacalcio.it non ha
più un'unica pagina "voti-fantacalcio-serie-a/{stagione}/{giornata}" con
tutte le partite della giornata insieme — ora ogni partita ha la sua pagina
voti separata:
  https://www.fantacalcio.it/serie-a/calendario/{giornata}/{stagione}/{casa}-{trasferta}/{match_id}/voti

Serve quindi prima l'elenco delle partite della giornata (già disponibile in
data/calendario.json, prodotto da probabili_formazioni_scraper.py, che
include già il match_id di ognuna) — poi si scarica il voto di ogni singola
partita e si aggregano.

NOTA: la struttura DOM interna (classi CSS di voto/fantavoto/bonus) NON è
stata riverificata su questa nuova pagina — l'ho ereditata dal vecchio
script (funzionava sulla vecchia pagina, ora sostituita). Se l'estrazione
fallisce, questo script stampa l'HTML vero nel log invece di fallire senza
spiegazioni, così un giro reale basta a correggere i selettori.

USO
---
  pip install playwright
  python -m playwright install chromium
  python voti_giornata_scraper_v2.py [giornata]
"""

import asyncio
import json
import sys
import os
from playwright.async_api import async_playwright

SEASON = "2026-27"
GIORNATA = int(sys.argv[1]) if len(sys.argv) > 1 else 1
os.makedirs("data", exist_ok=True)
OUT_JSON = f"data/voti_giornata_{GIORNATA}.json"

FONTI = ["redazione_fantacalcio", "voto_statistico", "voto_italia"]



import re

# Stesso pattern tollerante già validato su probabili_formazioni_scraper.py —
# regge eventuali attributi extra tra data-match-id e data-teams-id.
BLOCK_RE = re.compile(r'<li data-match-id="(\d+)"[^>]*?class="match">(.*?)</li>', re.DOTALL)
TEAM_HREF_RE = re.compile(r'/serie-a/squadre/([a-z0-9\-]+)"')


async def scarica_match_ids_giornata(page, giornata):
    """calendario.json tiene solo la giornata 'in vetrina' del momento (si
    sovrascrive appena la stagione avanza) — inutile per recuperare i match_id
    di una giornata già conclusa. Li prendo direttamente dalla pagina
    calendario di QUELLA specifica giornata, usando lo slug squadra così come
    compare nei link del sito stesso (più affidabile di ricostruirlo a mano)."""
    url = f"https://www.fantacalcio.it/serie-a/calendario/{giornata}/{SEASON}"
    print(f"📅 Recupero le partite della giornata {giornata} da {url}...")
    await page.goto(url, wait_until="load", timeout=45000)
    await page.wait_for_timeout(1200)
    html = await page.content()

    partite = []
    for m in BLOCK_RE.finditer(html):
        match_id = m.group(1)
        blocco = m.group(2)
        squadre = TEAM_HREF_RE.findall(blocco)
        if len(squadre) >= 2:
            partite.append({"casa": squadre[0], "trasferta": squadre[1], "match_id": match_id})

    if not partite:
        idx = html.find('data-match-id')
        diagnostica = html[max(0, idx-300): idx+3000] if idx >= 0 else html[:3000]
        raise RuntimeError(f"nessuna partita trovata nella pagina calendario giornata {giornata}\n\nDIAGNOSTICA:\n{diagnostica}")

    print(f"   ✅ {len(partite)} partite trovate")
    return partite


async def scrape_una_partita(page, casa, trasferta, match_id):
    url = f"https://www.fantacalcio.it/serie-a/calendario/{GIORNATA}/{SEASON}/{casa}-{trasferta}/{match_id}/voti"
    print(f"📡 {casa} - {trasferta}: {url}")
    await page.goto(url, wait_until="load", timeout=45000)
    try:
        await page.wait_for_selector("table.grades-table", timeout=15000)
    except Exception:
        pass  # la diagnostica sotto rivelerà la struttura vera se questo fallisce
    await page.wait_for_timeout(1200)

    data = await page.evaluate("""
        () => {
            const parseNum = (s) => {
                if (s == null || s === "") return null;
                const n = parseFloat(String(s).replace(",", "."));
                if (isNaN(n)) return null;
                if (n === 55) return null;   // sentinella "non votato da questa fonte"
                return n;
            };
            const teams = [];
            document.querySelectorAll('div.team-table-body').forEach(teamBlock => {
                const teamNameEl = teamBlock.querySelector('.team-name');
                const teamName = teamNameEl ? teamNameEl.textContent.trim() : null;
                const teamHref = teamBlock.querySelector('a.team-link')?.getAttribute('href') || '';
                const teamSlug = (teamHref.match(/\\/squadre\\/([^\\/]+)/) || [])[1] || null;
                const players = [];
                teamBlock.querySelectorAll('table.grades-table tbody tr').forEach(row => {
                    const nameA = row.querySelector('a.player-name');
                    if (!nameA) return;
                    const href = nameA.getAttribute('href') || '';
                    const idMatch = href.match(/\\/(\\d+)\\/\\d{4}-\\d{2}\\/?$/);
                    const playerId = idMatch ? idMatch[1] : null;
                    const name = nameA.querySelector('span')?.textContent.trim() || nameA.textContent.trim();
                    const role = row.querySelector('span.role')?.getAttribute('data-value') || null;
                    const sostituito = !!row.querySelector('img.player-icon[title*="Sostitu" i]');
                    const pills = row.querySelectorAll('td:nth-child(2) .pill');
                    const voti = Array.from(pills).map((pill, i) => ({
                        fonte: i,
                        voto: parseNum(pill.querySelector('.player-grade')?.getAttribute('data-value')),
                        fantavoto: parseNum(pill.querySelector('.player-fanta-grade')?.getAttribute('data-value'))
                    }));
                    const bmEls = row.querySelectorAll('td:nth-child(3) .player-bonus');
                    const bonusMalus = Array.from(bmEls).map(el => ({
                        tipo: el.getAttribute('title') || null,
                        segno: el.classList.contains('malus') ? '-' : '+',
                        valore: parseNum(el.getAttribute('data-value'))
                    })).filter(b => b.valore !== null && b.valore !== 0);
                    players.push({ player_id: playerId, name, role, sostituito, voti, bonus_malus: bonusMalus });
                });
                teams.push({ team: teamName, team_slug: teamSlug, players });
            });
            return teams;
        }
    """)

    if not data or all(len(t["players"]) == 0 for t in data):
        html = await page.content()
        idx = html.find("grades-table")
        diagnostica = html[max(0, idx-500): idx+3000] if idx >= 0 else html[:3000]
        return None, diagnostica
    return data, None


async def main_async():
    tutte_squadre = []
    diagnostica_salvata = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        partite = await scarica_match_ids_giornata(page, GIORNATA)
        print(f"Partite da scaricare per la giornata {GIORNATA}: {len(partite)}\n")

        for partita in partite:
            try:
                data, diag = await scrape_una_partita(page, partita["casa"], partita["trasferta"], partita["match_id"])
                if data:
                    tutte_squadre.extend(data)
                    n = sum(len(t["players"]) for t in data)
                    print(f"   ✅ {n} giocatori estratti\n")
                else:
                    print(f"   ⚠️  0 giocatori estratti per questa partita\n")
                    if diagnostica_salvata is None:
                        diagnostica_salvata = diag
            except Exception as e:
                print(f"   ❌ Errore su questa partita: {e}\n")
        await browser.close()

    if not tutte_squadre:
        print("\n⚠️  ATTENZIONE: nessun dato estratto da nessuna partita.")
        if diagnostica_salvata:
            print("\n" + "="*70)
            print("DIAGNOSTICA — HTML reale attorno a 'grades-table' (prima partita fallita):")
            print("="*70)
            print(diagnostica_salvata)
            print("="*70)
        return 1

    total_players = sum(len(t["players"]) for t in tutte_squadre)
    print(f"✅ Totale: {len(tutte_squadre)} squadre, {total_players} giocatori\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tutte_squadre, f, ensure_ascii=False, indent=2)
    print(f"📝 Salvato in {OUT_JSON}")
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
