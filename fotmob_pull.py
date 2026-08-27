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
    # Provo più varianti in un solo lancio (invece di un tentativo alla volta,
    # costoso da rilanciare da cellulare) — la documentazione trovata non è
    # stata chiara sull'URL esatto per le statistiche di lega.
    candidati = [
        f"{API_BASE}/leagues?id={LEAGUE_ID}",
        f"{API_BASE}/leagues?id={LEAGUE_ID}&type=season",
        f"{API_BASE}/leagues?id={LEAGUE_ID}&tab=stats",
        f"{API_BASE}/leagues?id={LEAGUE_ID}&season=2026-2027",
        "https://www.fotmob.com/api/allLeagues",
    ]

    for url in candidati:
        print(f"\n{'='*70}")
        print(f"📡 Provo: {url}")
        print('='*70)
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                dati = r.json()
                print("✅ SUCCESSO — chiavi di primo livello:")
                print(list(dati.keys()) if isinstance(dati, dict) else f"(tipo: {type(dati)})")
                with open(OUT_JSON, "w", encoding="utf-8") as f:
                    json.dump(dati, f, ensure_ascii=False, indent=1)
                print(f"📝 Salvato in {OUT_JSON}")
            else:
                print(f"❌ {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"❌ Errore: {e}")
        time.sleep(2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
