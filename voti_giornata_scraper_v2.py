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
                return isNaN(n) ? null : Math.abs(n);
            };
            const teams = [];
            let scartateOrfane = 0;

            // Tabella bonus/malus standard Classic, per data-event-id (più stabile
            // del testo, che include il minuto tipo " (86°)"). Valori confermati:
            // id 3 "Gol segnato" +3, id 1 "Ammonizione" -0.5, id 4 "Gol subito" -1,
            // id 22 "Assist" +1. Gli altri (23 "Assist GOLD", 26 "Man of the match",
            // 17 "Uscito per infortunio") non hanno ancora un valore confermato — li
            // tratto come 0 per ora, values_sconosciuti li segnala per revisione.
            const BONUS_PER_EVENTO = { "1": -0.5, "3": 3, "4": -1, "22": 1 };
            // Espulsione e autogol aggiunti il 28/08 SENZA un id numerico
            // confermato (mai visto un caso reale con questi eventi finora)
            // — li riconosco dal testo invece che dall'id, più sicuro che
            // indovinare un numero a caso. I rigori restano fuori apposta:
            // rischio di doppio conteggio con "Gol segnato" mai verificato.
            const BONUS_PER_TESTO = [
                { prefisso: "espulsione", valore: -1 },
                { prefisso: "autogol", valore: -2 },
                { prefisso: "autorete", valore: -2 },
            ];
            const eventi_sconosciuti = new Set();
            const rigoriTrovati = [];

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
                    // Il data-value è il VOTO PURO (confermato 25/08 con dati reali,
                    // caso Malen: data-value 8,5 = voto puro, non il fantavoto 17,5
                    // che include i bonus per la tripletta).
                    const votoPuro = gradeDiv ? parseVoto(gradeDiv.getAttribute('data-value')) : null;
                    const eventiRaw = Array.from(li.querySelectorAll('.player-event')).map(ev => ({
                        tipo: (ev.getAttribute('title') || '').trim(),
                        count: ev.getAttribute('data-count'),
                        eventId: ev.getAttribute('data-event-id')
                    }));
                    // Il "count" è un valore CUMULATIVO (es. 3 gol = tre eventi con
                    // count 1,2,3, non tre gol separati da sommare) — prendo il
                    // massimo per tipo di evento, non la somma di tutte le occorrenze.
                    const maxPerEvento = {};
                    const tipoPerEvento = {};
                    for (const ev of eventiRaw) {
                        const c = parseInt(ev.count, 10) || 1;
                        if (!(ev.eventId in maxPerEvento) || c > maxPerEvento[ev.eventId]) {
                            maxPerEvento[ev.eventId] = c;
                            tipoPerEvento[ev.eventId] = ev.tipo;
                        }
                        if (!(ev.eventId in BONUS_PER_EVENTO)) eventi_sconosciuti.add(ev.eventId + ":" + ev.tipo);
                    }
                    // Diagnostica automatica sui rigori (28/08): non abbiamo ancora
                    // un caso reale per sapere se un rigore segnato genera SIA
                    // "Gol segnato" SIA un evento "Rigore" separato (rischio doppio
                    // conteggio se sommassimo entrambi alla cieca). Appena capita,
                    // questo blocco lo segnala con tutti gli eventi del giocatore.
                    if (eventiRaw.some(ev => ev.tipo.toLowerCase().includes("rigore"))) {
                        rigoriTrovati.push({ nome, eventi: eventiRaw });
                    }
                    let bonusMalusTotale = 0;
                    for (const [eventId, count] of Object.entries(maxPerEvento)) {
                        if (eventId in BONUS_PER_EVENTO) {
                            bonusMalusTotale += BONUS_PER_EVENTO[eventId] * count;
                            continue;
                        }
                        // Fallback per testo (espulsione, autogol — id non confermato)
                        const testoNorm = (tipoPerEvento[eventId] || "").trim().toLowerCase();
                        const match = BONUS_PER_TESTO.find(b => testoNorm.startsWith(b.prefisso));
                        if (match) bonusMalusTotale += match.valore * count;
                    }
                    const fantavoto = votoPuro != null ? Math.round((votoPuro + bonusMalusTotale) * 2) / 2 : null;
                    // Scarto le righe senza nome collegato (voti "orfani", probabilmente
                    // di sostituti mostrati in forma compatta) — meglio perdere quel
                    // singolo dato che rischiare di attribuirlo al giocatore vicino
                    // sbagliato (bug reale scoperto il 25/08: un voto orfano è finito
                    // attaccato a un altro giocatore).
                    if (playerId && name) players.push({ player_id: playerId, name, role, voto_puro: votoPuro, fantavoto, eventi: eventiRaw });
                    else if (playerId) scartateOrfane++;
                });
                teams.push({ team: teamName, players });
            });
            return { teams, scartateOrfane, eventi_sconosciuti: [...eventi_sconosciuti], rigoriTrovati };
        }
    """)

    if data and data.get("eventi_sconosciuti"):
        print(f"   ℹ️  Tipi di evento senza bonus/malus mappato (trattati come 0): {data['eventi_sconosciuti']}")

    if data and data.get("rigoriTrovati"):
        print("\n" + "="*70)
        print("DIAGNOSTICA RIGORI — trovato un caso reale, ecco tutti gli eventi:")
        print("="*70)
        for caso in data["rigoriTrovati"]:
            print(json.dumps(caso, ensure_ascii=False, indent=2))
        print("="*70)
        print("Manda questa sezione a Claude per sistemare finalmente i rigori con dati veri.\n")

    teams = data.get("teams", []) if data else []
    scartate = data.get("scartateOrfane", 0) if data else 0
    if scartate:
        print(f"   ℹ️  {scartate} righe voto senza nome collegato scartate (probabili sostituti in forma compatta)")

    if not teams or all(len(t["players"]) == 0 for t in teams):
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
    return teams, None


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

    # Salvo SUBITO, prima di qualunque altra cosa — i dati veri non devono mai
    # dipendere dalla riuscita di un'anteprima di debug
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tutte_squadre, f, ensure_ascii=False, indent=2)
    print(f"📝 Salvato in {OUT_JSON}")

    # Anteprima concreta (solo dopo il salvataggio) — robusta a nomi mancanti
    # (es. voci allenatore o giocatori senza link nel DOM)
    print("\n📊 Anteprima primi 5 giocatori estratti:")
    conteggio = 0
    for t in tutte_squadre:
        for p in t["players"][:2]:
            if conteggio >= 5: break
            nome = p.get("name") or "(nome mancante)"
            print(f"   {nome:20s} ruolo={p.get('role')} fantavoto={p.get('fantavoto')}")
            conteggio += 1

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
