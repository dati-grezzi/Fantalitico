# -*- coding: utf-8 -*-
"""
FANTALITICO — playerstats.football, statistiche difensive e di passaggio.

Sesto tentativo per le metriche mancanti (dopo Understat, che non le ha mai
avute; FBref, bloccato da Cloudflare; SofaScore, bloccato dagli IP dei
server GitHub Actions anche con proxy gratuito; Kickest e legaseriea.it e
calcio.com, che non hanno ancora dati per questa stagione).

playerstats.football è stato VERIFICATO CON DATI VERI il 28/08/2026 (non solo
supposto): pagina raggiunta senza blocchi, senza login, con Gaetano che
mostra 4 tackle/90min alla Giornata 1 — confermato corretto.

Una pagina per categoria statistica (URL diretti, niente da indovinare):
tackles, interceptions, clearances, duels, key-passes, accurate-passes,
player-rating.

USO
---
  pip install requests beautifulsoup4 lxml
  python playerstats_pull.py
"""

import json
import re
import sys
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://playerstats.football/serie-a/stats"
PAUSA_TRA_CHIAMATE = 3

# categoria interna → slug URL
CATEGORIE = {
    "tackles_p90": "tackles",
    "interceptions_p90": "interceptions",
    "clearances_p90": "clearances",
    "duels_p90": "duels",
    "key_passes_p90": "key-passes",
    "accurate_passes_p90": "accurate-passes",
    "rating": "player-rating",
    # AGGIUNTE 02/09/2026 — Understat ha smesso di esporre i tiri: la sua
    # tabella di lega offre solo N/Player/Team/Apps/Min/G/NPG/A/xG/NPxG/xA e
    # le varianti per 90 (verificato aprendo il suo selettore colonne, dove
    # Sh90 e KP90 non esistono piu'). I tiri sono il segnale col peso piu'
    # alto del bonus attaccanti, quindi li prendiamo qui: stessa fonte gia'
    # automatizzata, stesso schema di URL, nessuna dipendenza nuova.
    "shots_p90": "total-shots",
    "shots_on_target_p90": "shots-on-target",
    # Copre i portieri, rimasti scoperti da quando SofaScore non e'
    # raggiungibile dagli IP di GitHub Actions.
    "saves_p90": "goalkeeper-saves",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}

OUT_JSON = Path(__file__).parent / "playerstats_2026.json"


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def estrai_pagina(slug):
    url = f"{BASE}/{slug}"
    print(f"📡 {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    righe = []
    # Ancoro sui link ai profili giocatore (/player/ID) — più robusto di
    # indovinare classi CSS esatte, stessa strategia già affidabile usata
    # su fantacalcio.it oggi.
    for a in soup.select('a[href*="/player/"]'):
        href = a.get("href", "")
        m = re.search(r"/player/(\d+)", href)
        if not m:
            continue
        player_id = m.group(1)
        nome = norm(a.get_text())
        if not nome:
            continue

        # Il contenitore della riga è un antenato del link — risalgo finché
        # non trovo un blocco che contiene sia il nome che i numeri (mins
        # played, per 90, totale).
        container = a
        testo_container = ""
        for _ in range(6):
            container = container.parent
            if container is None:
                break
            testo_container = norm(container.get_text())
            if "mins played" in testo_container.lower() and "per 90" in testo_container.lower():
                break

        m_mins = re.search(r"(\d+)\s*mins played", testo_container)
        m_per90 = re.search(r"([\d.]+)\s*per 90", testo_container)
        # Il totale è l'ultimo numero isolato nel blocco (dopo "per 90 ... N")
        m_tot = re.findall(r"per 90\D*(\d+(?:\.\d+)?)", testo_container)

        if not (m_mins and m_per90):
            continue

        righe.append({
            "player_id": player_id,
            "nome": nome,
            "minuti": int(m_mins.group(1)),
            "per90": float(m_per90.group(1)),
            "totale": float(m_tot[0]) if m_tot else None,
        })

    return righe


def main():
    dati_per_giocatore = {}  # player_id → {nome, campi...}

    for campo_interno, slug in CATEGORIE.items():
        try:
            righe = estrai_pagina(slug)
        except Exception as e:
            print(f"   ⚠️  Errore su {slug}: {e}")
            continue

        if not righe:
            print(f"   ⚠️  0 righe estratte per {slug} — struttura pagina diversa dal previsto?")
            continue

        print(f"   ✅ {len(righe)} giocatori per '{slug}'")
        for r in righe:
            pid = r["player_id"]
            if pid not in dati_per_giocatore:
                dati_per_giocatore[pid] = {"nome": r["nome"], "minuti": r["minuti"]}
            dati_per_giocatore[pid][campo_interno] = r["per90"]

        time.sleep(PAUSA_TRA_CHIAMATE)

    if not dati_per_giocatore:
        print("\n❌ Nessun dato estratto da nessuna categoria — controllare la struttura della pagina.")
        return 1

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(dati_per_giocatore, f, ensure_ascii=False, indent=1)

    print(f"\n✅ Totale: {len(dati_per_giocatore)} giocatori")
    print(f"📝 Salvato in {OUT_JSON}")

    # Anteprima di un giocatore con dati completi, per verifica rapida
    for pid, d in dati_per_giocatore.items():
        if len(d) >= 5:
            print("\n📊 Esempio:", json.dumps(d, ensure_ascii=False, indent=2))
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
