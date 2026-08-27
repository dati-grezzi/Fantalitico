# -*- coding: utf-8 -*-
"""
FANTALITICO — Elaborazione SofaScore (metriche difensive/di passaggio).
Legge sofascore_defense_2026.json (prodotto da sofascore_pull.py), fa il
matching con players.json, e salva data/sofascore.json.

Le metriche qui (tackles, interceptions, clearances, duelli, passaggi) sono
quelle che Understat non ha mai avuto — verificato il 25/08/2026 controllando
la lista ufficiale dei campi Understat, che è solo tiri/xG.

USO
---
  1. sofascore_pull.py genera sofascore_defense_2026.json
  2. Questo script lo elabora → data/sofascore.json
"""

import json
import sys
from pathlib import Path
from difflib import SequenceMatcher
import unicodedata
import re

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

JSON_IN = Path(__file__).parent / "sofascore_defense_2026.json"


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


def to_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def main() -> int:
    print("\n▶ Elaborazione SofaScore")

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
        print(f"     Run sofascore_pull.py prima per generarlo")
        return 1
    with open(JSON_IN, encoding='utf-8') as f:
        dati = json.load(f)
    righe = dati.get("giocatori", [])
    print(f"  Caricate {len(righe)} righe da {JSON_IN.name}")

    sofascore_by_id = {}
    matched = 0
    failed = []

    for riga in righe:
        player_info = riga.get("player") or {}
        nome = (player_info.get("name") or "").strip()
        if not nome:
            continue

        nome_norm = normalize_name(nome)
        best_match_id = None
        best_score = 0.65
        for player_id, fanta_name in giocatori_fanta.items():
            score = levenshtein_ratio(nome_norm, fanta_name)
            parti_sofa = nome_norm.split()
            parti_fanta = fanta_name.split()
            if parti_sofa and parti_fanta and parti_sofa[-1] == parti_fanta[-1]:
                score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_match_id = player_id

        if best_match_id:
            sofascore_by_id[best_match_id] = {
                "goals_p90": to_float(riga.get("goals")),
                "assists_p90": to_float(riga.get("assists")),
                "rating": to_float(riga.get("rating")),
                "tackles_p90": to_float(riga.get("tackles")),
                "interceptions_p90": to_float(riga.get("interceptions")),
                "clearances_p90": to_float(riga.get("clearances")),
                "duels_won_pct": to_float(riga.get("totalDuelsWonPercentage")),
                "passes_accurate_pct": to_float(riga.get("accuratePassesPercentage")),
                "key_passes_p90": to_float(riga.get("keyPasses")),
                "saves_box_p90": to_float(riga.get("savedShotsFromInsideTheBox")),
                "sofascore_name": nome,
                "match_score": round(best_score, 3),
            }
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
        "fonte": "SofaScore (statistiche difensive/di passaggio, per90)",
        "note": "Mapping ID fantacalcio → {tackles_p90, interceptions_p90, clearances_p90, duels_won_pct, passes_accurate_pct, key_passes_p90, saves_box_p90}. Da sofascore_defense_2026.json.",
        "giocatori": sofascore_by_id
    }
    with open(DATA_DIR / "sofascore.json", "w", encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"  ✔ scritto data/sofascore.json ({len(sofascore_by_id)} giocatori)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
