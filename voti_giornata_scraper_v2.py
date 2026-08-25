# -*- coding: utf-8 -*-
"""
VOTI GIORNATA — Scraper (v4: pagina della singola partita, versione consolidata)

Questa è la versione che raccoglie TUTTE le correzioni fatte finora, dopo aver
scoperto che la pagina generale "voti-fantacalcio-serie-a" mostra le celle
voto/fantavoto VUOTE quando non si è loggati (verificato scaricando la pagina
direttamente: struttura presente, valori assenti per tutti i giocatori) —
probabilmente un contenuto riservato agli utenti autenticati.

La pagina della singola partita invece FUNZIONA da anonimi — confermato
(24/08/2026) confrontando i valori estratti con le pagelle pubblicate da due
fonti esterne indipendenti (Calciomagazine, SOS Fanta) su Inter-Monza: i
valori combaciavano esattamente. Un solo fantavoto (non le 3 fonti separate),
ma vero.

URL: https://www.fantacalcio.it/serie-a/calendario/{giornata}/{stagione}/{casa}-{trasferta}/{match_id}/voti

I match_id vengono da data/calendario_storico.json (archivio permanente
costruito da probabili_formazioni_scraper.py) — NON da calendario.json, che
tiene solo la giornata "in vetrina" del momento e si sovrascrive.

Struttura DOM confermata su dati reali:
  #playersListsTemplateTarget > div.col (uno per squadra)
    ul.player-list > li.player-item (uno per giocatore)
      span.role[data-value]           → ruolo (p/d/c/a)
      a[href*="/squadre/"] > span     → nome
      .player-grade                   → fantavoto (nel TESTO mostrato, non nel
                                         data-value, che ha un significato diverso
                                         non ancora chiaro — verificato con fonti esterne)

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

CALENDARIO_STORICO = "data/calendario_storico.json"


def carica_match_ids_giornata(giornata):
    """I match_id vengono dall'archivio permanente (data/calendario_storico.json,
    costruito da probabili_formazioni_scraper.py ogni volta che gira) — NON da
    calendario.json, che tiene solo la giornata 'in vetrina' del momento e si
    sovrascrive appena la stagione avanza."""
    if not os.path.exists(CALENDARIO_STORICO):
        raise FileNotFoundError(
            f"{CALENDARIO_STORICO} non trovato. Si costruisce da solo, una giornata alla "
            f"volta, ogni volta che gira probabili_formazioni_scraper.py — se manca la "
            f"giornata {giornata}, va recuperata a mano dalla cronologia Git di calendario.json."
        )
    with open(CALENDARIO_STORICO, encoding="utf-8") as f:
        storico = json.load(f)
    partite = storico.get(str(giornata))
    if not partite:
        disponibili = sorted(int(g) for g in storico) if storico else []
        raise KeyError(f"Giornata {giornata} non nell'archivio. Disponibili: {disponibili}.")
    return partite


async def scrape_una_partita(page, casa, trasferta, match_id):
    url = f"https://www.fantacalcio.it/serie-a/calendario/{GIORNATA}/{SEASON}/{casa}-{trasferta}/{match_id}/voti"
    print(f"📡 {casa} - {trasferta}: {url}")
    await page.goto(url, wait_until="load", timeout=45000)
    try:
        await page.wait_for_selector("#playersListsTemplateTarget", timeout=15000)
    except Exception:
        pass  # la diagnostica sotto rivelerà la struttura vera se questo fallisce
    await page.wait_for_timeout(1000)

    # Scroll di sicurezza (pattern già validato su altre pagine di questo sito,
    # che caricano contenuti solo quando entrano in viewport)
    altezza = await page.evaluate("document.body.scrollHeight")
    y, step, i = 0, 1200, 0
    while y < altezza and i < 15:
        await page.evaluate(f"window.scrollTo(0, {y})")
        await page.wait_for_timeout(300)
        y += step; i += 1
        altezza = await page.evaluate("document.body.scrollHeight")
    await page.wait_for_timeout(800)

    data = await page.evaluate("""
        () => {
            const parseVoto = (s) => {
                if (s == null || s === "" || s.toLowerCase() === "sv") return null;
                const n = parseFloat(String(s).trim().replace(",", "."));
                return isNaN(n) ? null : n;
            };
            const teams = [];
            document.querySelectorAll('#playersListsTemplateTarget > div.col').forEach(col => {
                const teamNameEl = col.querySelector('.team-name');
                const teamName = teamNameEl ? teamNameEl.textContent.trim() : null;
                const players = [];
                col.querySelectorAll('ul.player-list > li.player-item').forEach(li => {
                    const playerId = li.getAttribute('data-id') || null;
                    const nameEl = li.querySelector('a.player-name span');
                    const name = nameEl ? nameEl.textContent.trim() : null;
                    const roleSpan = li.querySelector('span.role[data-value]');
                    const role = roleSpan ? roleSpan.getAttribute('data-value') : null;
                    const gradeDiv = li.querySelector('.player-grade');
                    const fantavoto = gradeDiv ? parseVoto(gradeDiv.textContent) : null;
                    const eventi = Array.from(li.querySelectorAll('.player-event')).map(ev => ({
                        tipo: (ev.getAttribute('title') || '').trim(),
                        count: ev.getAttribute('data-count'),
                        eventId: ev.getAttribute('data-event-id')
                    }));
                    if (playerId) players.push({ player_id: playerId, name, role, fantavoto, eventi });
                });
                teams.push({ team: teamName, players });
            });
            return teams;
        }
    """)

    if not data or all(len(t["players"]) == 0 for t in data):
        html = await page.content()
        idx = -1
        for chiave in ["playersListsTemplateTarget", "player-grade", "player-item", "team-formation"]:
            idx = html.find(chiave)
            if idx >= 0:
                break
        if idx >= 0:
            diagnostica = html[max(0, idx-500): idx+4000]
        else:
            idx_body = html.find("<body")
            diagnostica = html[idx_body: idx_body+6000] if idx_body >= 0 else html[:6000]
        return None, diagnostica
    return data, None


async def main_async():
    partite = carica_match_ids_giornata(GIORNATA)
    print(f"Partite da scaricare per la giornata {GIORNATA}: {len(partite)}\n")

    tutte_squadre = []
    diagnostica_salvata = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

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
            print("DIAGNOSTICA — HTML reale:")
            print("="*70)
            print(diagnostica_salvata)
            print("="*70)
        return 1

    total_players = sum(len(t["players"]) for t in tutte_squadre)
    print(f"✅ Totale: {len(tutte_squadre)} squadre, {total_players} giocatori\n")

    # Anteprima concreta, per verificare a occhio prima di fidarsi del salvataggio
    print("📊 Anteprima primi 5 giocatori estratti:")
    conteggio = 0
    for t in tutte_squadre:
        for p in t["players"][:2]:
            if conteggio >= 5: break
            print(f"   {p['name']:20s} ruolo={p['role']} fantavoto={p['fantavoto']}")
            conteggio += 1

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tutte_squadre, f, ensure_ascii=False, indent=2)
    print(f"\n📝 Salvato in {OUT_JSON}")
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
