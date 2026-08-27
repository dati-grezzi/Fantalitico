# -*- coding: utf-8 -*-
"""
FANTALITICO — SofaScore, statistiche difensive e di passaggio per giocatore.

v2 (25/08/2026): la chiamata diretta all'API con 'requests' dà 403 — il sito
probabilmente richiede un contesto di browser vero (cookie/token generati
visitando prima il sito). Passo a Playwright: apro prima sofascore.com per
davvero, poi chiamo l'API con un fetch() eseguito DENTRO quella pagina —
porta con sé automaticamente tutto quello che un browser vero avrebbe.

Serie A = torneo id 23 su SofaScore. Il season_id va cercato dinamicamente.

USO
---
  pip install playwright
  python -m playwright install chromium
  python sofascore_pull.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

API_BASE = "https://api.sofascore.com/api/v1"
TOURNAMENT_ID = 23  # Serie A
PAUSA_TRA_CHIAMATE = 5  # secondi

OUT_JSON = Path(__file__).parent / "sofascore_defense_2026.json"


async def fetch_json_da_pagina(page, url):
    """Chiama l'API con un fetch() eseguito dentro la pagina del browser,
    non dall'esterno — porta con sé i cookie/contesto di un browser vero."""
    risultato = await page.evaluate("""
        async (url) => {
            const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!r.ok) return { errore: true, status: r.status, testo: await r.text() };
            return { errore: false, dati: await r.json() };
        }
    """, url)
    if risultato.get("errore"):
        raise RuntimeError(f"HTTP {risultato['status']} per {url}: {risultato['testo'][:300]}")
    return risultato["dati"]


async def trova_stagione_corrente(page):
    url = f"{API_BASE}/unique-tournament/{TOURNAMENT_ID}/seasons"
    print(f"📡 Cerco la stagione corrente: {url}")
    data = await fetch_json_da_pagina(page, url)
    stagioni = data.get("seasons", [])
    for s in stagioni:
        nome = (s.get("name") or "").replace(" ", "")
        if "26/27" in nome or "2026/2027" in nome or "2026/27" in nome:
            print(f"   ✅ Trovata: {s.get('name')} (id={s.get('id')})")
            return s["id"], s.get("name")
    print(f"   ⚠️  Nessuna stagione 26/27 trovata. Disponibili: {[s.get('name') for s in stagioni[:5]]}")
    return None, None


async def scarica_statistiche(page, season_id, accumulation="per90"):
    # IMPORTANTE (bug trovato 25/08 sui dati reali): senza "fields" l'API
    # risponde solo con l'identità del giocatore, nessuna statistica vera.
    # Elenco ampio per la prima verifica — quelli con nome sbagliato
    # torneranno semplicemente vuoti/nulli, non causano errori.
    campi = [
        "goals", "assists", "rating",
        "tackles", "interceptions", "clearances",
        "totalDuelsWonPercentage", "accuratePassesPercentage",
        "keyPasses", "savedShotsFromInsideTheBox",
    ]
    fields_param = "%2C".join(campi)

    tutti = []
    offset = 0
    for _ in range(30):
        url = (f"{API_BASE}/unique-tournament/{TOURNAMENT_ID}/season/{season_id}/statistics"
               f"?limit=100&order=-rating&offset={offset}&accumulation={accumulation}"
               f"&fields={fields_param}")
        print(f"📡 Statistiche giocatori (offset={offset}): {url}")
        data = await fetch_json_da_pagina(page, url)
        risultati = data.get("results", [])
        if not risultati:
            break
        tutti.extend(risultati)
        print(f"   ✅ {len(risultati)} giocatori in questa pagina (totale finora: {len(tutti)})")
        if data.get("page") is not None and data.get("pages") is not None and data["page"] >= data["pages"]:
            break
        offset += 100
        await asyncio.sleep(PAUSA_TRA_CHIAMATE)
    return tutti


async def main_async():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        # Visito prima il sito vero, per avere un contesto di browser
        # legittimo (cookie, ecc.) prima di chiamare l'API.
        print("📡 Visito sofascore.com per stabilire un contesto valido...")
        await page.goto("https://www.sofascore.com/football/tournament/italy/serie-a/23",
                         wait_until="load", timeout=45000)
        await page.wait_for_timeout(2500)

        try:
            season_id, nome_stagione = await trova_stagione_corrente(page)
        except RuntimeError as e:
            print(f"\n❌ {e}")
            await browser.close()
            return 1

        if not season_id:
            await browser.close()
            return 1

        await asyncio.sleep(PAUSA_TRA_CHIAMATE)
        try:
            giocatori = await scarica_statistiche(page, season_id)
        except RuntimeError as e:
            print(f"\n❌ {e}")
            await browser.close()
            return 1

        await browser.close()

    if not giocatori:
        print("\n⚠️  0 giocatori estratti.")
        return 1

    print(f"\n📊 Anteprima primo giocatore (per vedere quali campi sono davvero disponibili):")
    print(json.dumps(giocatori[0], ensure_ascii=False, indent=2)[:2000])

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"stagione": nome_stagione, "giocatori": giocatori}, f, ensure_ascii=False, indent=1)
    print(f"\n✅ Totale: {len(giocatori)} giocatori")
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
