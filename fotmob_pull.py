# -*- coding: utf-8 -*-
"""
FANTALITICO — FotMob, statistiche difensive e di passaggio per giocatore.

Quinto tentativo per le metriche mancanti (dopo Understat, che non le ha mai
avute; FBref, bloccato da Cloudflare; SofaScore, che funziona ma è bloccato
dagli IP dei server GitHub Actions; Kickest, tecnicamente funzionante ma non
ancora aggiornato alla stagione 2026-27).

FotMob è confermato (25/08/2026, più fonti indipendenti) SENZA protezione
anti-bot sulle superfici usate qui — se davvero è così, potremmo finalmente
avere l'automazione completa sui server GitHub, cosa che SofaScore non ci
ha concesso.

Serie A = lega id 55 su FotMob (da fotmob.com/leagues/55/stats/serie).

NOTA ONESTA: non ho potuto verificare la struttura esatta della risposta
contro il sito vero (accesso di rete non disponibile nel mio ambiente) —
questo è un primo tentativo ragionato sui pattern noti di librerie esistenti
(LanusStats, worldfootballR), con diagnostica completa se qualcosa non
corrisponde.

USO
---
  pip install requests
  python fotmob_pull.py
"""

import json
import sys
import time
from pathlib import Path
import requests

API_BASE = "https://www.fotmob.com/api"
LEAGUE_ID = 55  # Serie A
PAUSA_TRA_CHIAMATE = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

OUT_JSON = Path(__file__).parent / "fotmob_stats_2026.json"


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    # 1) Info lega — per trovare l'id di stagione corrente (serve per le
    #    statistiche, che sono legate a una stagione specifica).
    url_lega = f"{API_BASE}/leagues?id={LEAGUE_ID}"
    print(f"📡 Info lega: {url_lega}")
    dati_lega = get_json(url_lega)

    # Diagnostica ampia: non sapendo con certezza dove sia annidato l'elenco
    # statistiche giocatori, stampo le chiavi di primo livello e una parte
    # della struttura, così anche in caso di fallimento sappiamo dove guardare.
    print("\n📊 Chiavi di primo livello nella risposta:")
    print(list(dati_lega.keys()) if isinstance(dati_lega, dict) else type(dati_lega))

    # Tentativo: molte implementazioni note (LanusStats, worldfootballR)
    # trovano le statistiche di stagione sotto una chiave tipo "stats" o
    # dentro "table"/"season" — provo i percorsi più comuni.
    candidati_stats = None
    for chiave in ("stats", "playerStats", "topPlayers", "table"):
        if isinstance(dati_lega, dict) and chiave in dati_lega:
            candidati_stats = dati_lega[chiave]
            print(f"\n✅ Trovata chiave '{chiave}' nella risposta")
            break

    if candidati_stats is None:
        print("\n⚠️  Nessuna chiave statistiche riconosciuta tra quelle attese.")
        print("Anteprima completa della risposta (primi 3000 caratteri):")
        print(json.dumps(dati_lega, ensure_ascii=False, indent=1)[:3000])
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(dati_lega, f, ensure_ascii=False, indent=1)
        print(f"\n📝 Salvata comunque la risposta grezza in {OUT_JSON} per analisi manuale")
        return 1

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(candidati_stats, f, ensure_ascii=False, indent=1)
    print(f"\n📝 Salvato in {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
