# -*- coding: utf-8 -*-
"""
FANTALITICO — Elaborazione playerstats.football.
Legge playerstats_2026.json (prodotto da playerstats_pull.py), fa il
matching con players.json, e salva data/playerstats.json.

USO
---
  1. playerstats_pull.py genera playerstats_2026.json
  2. Questo script lo elabora → data/playerstats.json
"""

import json
import sys
from pathlib import Path
from difflib import SequenceMatcher
import unicodedata
import re

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

JSON_IN = Path(__file__).parent / "playerstats_2026.json"


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = re.sub(r'\s+[a-z]\.$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def levenshtein_ratio(s1: str, s2: str) -> float:
    return SequenceMatcher(None, s1, s2).ratio()


def main() -> int:
    print("\n▶ Elaborazione playerstats.football")

    players_file = DATA_DIR / "players.json"
    if not players_file.exists():
        print(f"  ✘ {players_file} non trovato (run scraper.py prima)")
        return 1
    with open(players_file, encoding='utf-8') as f:
        players_data = json.load(f)
    giocatori_fanta = {p['id']: normalize_name(p['nome']) for p in players_data['giocatori'] if p.get('id')}
    print(f"  Caricati {len(giocatori_fanta)} giocatori da players.json")

    if not JSON_IN.exists():
        print(f"  ✘ {JSON_IN} non trovato")
        print(f"     Run playerstats_pull.py prima per generarlo")
        return 1
    with open(JSON_IN, encoding='utf-8') as f:
        righe = json.load(f)
    print(f"  Caricate {len(righe)} righe da {JSON_IN.name}")

    risultato_by_id = {}
    matched = 0
    failed = []

    for player_id_esterno, dati in righe.items():
        nome = (dati.get("nome") or "").strip()
        if not nome:
            continue

        nome_norm = normalize_name(nome)
        best_match_id = None
        best_score = 0.65
        for fanta_id, fanta_name in giocatori_fanta.items():
            score = levenshtein_ratio(nome_norm, fanta_name)
            parti_ext = nome_norm.split()
            parti_fanta = fanta_name.split()
            if parti_ext and parti_fanta and parti_ext[-1] == parti_fanta[-1]:
                score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_match_id = fanta_id

        if best_match_id:
            voce = {k: v for k, v in dati.items() if k != "nome"}
            voce["playerstats_name"] = nome
            voce["match_score"] = round(best_score, 3)
            risultato_by_id[best_match_id] = voce
            matched += 1
        else:
            failed.append(nome)

    print(f"  ✓ Matched: {matched} giocatori")
    if failed:
        print(f"    Falliti ({len(failed)} totali, campione):")
        for name in failed[:10]:
            print(f"      - {name}")

    import datetime as dt
    result = {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fonte": "playerstats.football (statistiche difensive/di passaggio, per90, solo top-50 per categoria)",
        "note": "Mapping ID fantacalcio → {tackles_p90, interceptions_p90, clearances_p90, duels_p90, key_passes_p90, accurate_passes_p90, rating}. Copertura parziale: solo chi rientra nei primi 50 di almeno una categoria.",
        "giocatori": risultato_by_id
    }
    with open(DATA_DIR / "playerstats.json", "w", encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"  ✔ scritto data/playerstats.json ({len(risultato_by_id)} giocatori)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
