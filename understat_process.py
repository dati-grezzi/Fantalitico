# -*- coding: utf-8 -*-
"""
FANTALITICO — Elaborazione Understat.
Legge il CSV da understat_pull.py (già aggregato per stagione da Understat
stesso — non più da sommare partita per partita), fa il matching con
players.json, e salva understat.json.

RISCRITTO IL 25/08/2026 insieme a understat_pull.py: la nuova tabella
"Players" del sito dà già i totali (apps, min, goals, xG, xA, xG90, xA90)
per l'intera stagione fin qui — questo script ora fa solo il matching e
la conversione, senza più aggregare righe partita-per-partita.

USO
---
  1. understat_pull.py genera understat_players_2026.csv
  2. Questo script lo elabora → data/understat.json
"""

import json
import sys
from pathlib import Path
from difflib import SequenceMatcher
import unicodedata
import re
import csv

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

CSV_IN = Path(__file__).parent / "understat_players_2026.csv"

MIN_MINUTI = 90  # scarta chi ha giocato meno di 90 minuti totali finora


def normalize_name(name: str) -> str:
    """Normalizza nomi per il matching fuzzy."""
    if not name:
        return ""
    name = name.lower().strip()
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = re.sub(r'\s+[a-z]\.$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def levenshtein_ratio(s1: str, s2: str) -> float:
    return SequenceMatcher(None, s1, s2).ratio()


def to_float(s, default=0.0):
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def to_int(s, default=0):
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default


def main() -> int:
    print("\n▶ Elaborazione Understat")

    players_file = DATA_DIR / "players.json"
    if not players_file.exists():
        print(f"  ✘ {players_file} non trovato (run scraper.py prima)")
        return 1
    with open(players_file, encoding='utf-8') as f:
        players_data = json.load(f)
    giocatori_fanta = {p['id']: normalize_name(p['nome']) for p in players_data['giocatori'] if p.get('id')}
    print(f"  Caricati {len(giocatori_fanta)} giocatori da players.json")

    if not CSV_IN.exists():
        print(f"  ✘ {CSV_IN} non trovato")
        print(f"     Run understat_pull.py prima per generare il CSV")
        return 1

    understat_by_id = {}
    matched = 0
    scartati_pochi_minuti = 0
    failed = []

    with open(CSV_IN, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nome = (row.get('player') or '').strip()
            if not nome:
                continue

            minuti = to_int(row.get('min'))
            if minuti < MIN_MINUTI:
                scartati_pochi_minuti += 1
                continue

            understat_norm = normalize_name(nome)
            best_match_id = None
            best_score = 0.65  # soglia minima
            for player_id, fanta_name in giocatori_fanta.items():
                score = levenshtein_ratio(understat_norm, fanta_name)
                parts_under = understat_norm.split()
                parts_fanta = fanta_name.split()
                if parts_under and parts_fanta and parts_under[-1] == parts_fanta[-1]:
                    score = max(score, 0.85)
                if score > best_score:
                    best_score = score
                    best_match_id = player_id

            if best_match_id:
                understat_by_id[best_match_id] = {
                    "apps": to_int(row.get('apps')),
                    "minutes_total": minuti,
                    "goals": to_int(row.get('goals')),
                    "assists": to_int(row.get('assists')),
                    "xG": to_float(row.get('xG')),
                    "xA": to_float(row.get('xA')),
                    "xG90": to_float(row.get('xG90')),
                    "xA90": to_float(row.get('xA90')),
                    "understat_name": nome,
                    "match_score": round(best_score, 3),
                }
                matched += 1
            else:
                failed.append((nome, minuti))

    print(f"  Scartati per pochi minuti (<{MIN_MINUTI}'): {scartati_pochi_minuti}")
    print(f"  ✓ Matched: {matched} giocatori")
    if failed:
        print(f"    Falliti ({len(failed)} totali, campione):")
        for name, mins in failed[:10]:
            print(f"      - {name} ({mins} min)")

    import datetime as dt
    result = {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fonte": "Understat (tabella Players, totali di stagione)",
        "note": "Mapping ID fantacalcio → {apps, minutes_total, goals, assists, xG, xA, xG90, xA90}. Da understat_players_2026.csv.",
        "giocatori": understat_by_id
    }
    with open(DATA_DIR / "understat.json", "w", encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"  ✔ scritto data/understat.json ({len(understat_by_id)} giocatori)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
