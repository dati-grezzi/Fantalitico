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


import match_nomi as M


# Tetto di plausibilita': i minuti di una fonte non possono superare di molto
# quelli che la Lega attribuisce al giocatore (presenze con voto x 95, piu' due
# partite di margine per le sostituzioni senza voto). Serve perche' playerstats
# non fornisce la squadra: senza questo controllo "Filip Stankovic" (540 minuti)
# veniva attribuito all'Inter "Stankovic A." con 1 presenza.
MARGINE_PARTITE = 2
MINUTI_PARTITA = 95


def minuti_plausibili(minuti, pv):
    if minuti is None:
        return True
    return minuti <= ((pv or 0) + MARGINE_PARTITE) * MINUTI_PARTITA


def iniziali_ok(norm_fonte, nome_fanta):
    """Le abbreviazioni del listone ("F.P.", "Je.") non devono contraddire i nomi
    propri della fonte. Qui la fonte puo' avere meno nomi del listone ("Pio
    Esposito" contro "Esposito F.P."): basta che ogni nome della fonte inizi
    con una delle abbreviazioni."""
    corti = [t for t in nome_fanta.split() if len(t) < 3 and t not in M.PARTICELLE]
    if not corti:
        return True
    cognomi = M.token_identificativi(nome_fanta)
    propri = [t for t in norm_fonte.split() if t not in cognomi and t not in M.PARTICELLE]
    return all(any(n.startswith(c) for c in corti) for n in propri)


def candidati_per_nome(nome, giocatori):
    """Giocatori della Lega compatibili col nome, dal migliore al peggiore.

    Il cognome della fonte e' l'ULTIMO token ("Lorenzo Colombo" -> colombo) e
    deve comparire fra i token del listone: cosi' "Lorenzo" non aggancia
    "Di Lorenzo". Niente confronto fuzzy sul nome intero: il 17/10 "Éderson"
    combaciava con "Pedersen" a 0,80 e prendeva i suoi dati."""
    norm = M.normalize_name(nome)
    toks = M.token_identificativi(norm)
    parti = [t for t in norm.split() if t not in M.PARTICELLE]
    cognome = parti[-1] if parti else ""
    trovati = []
    for pid, (nome_fanta, squadra) in giocatori.items():
        tf = M.token_identificativi(nome_fanta)
        if cognome in tf or (len(tf) >= 2 and tf <= toks):
            if iniziali_ok(norm, nome_fanta):
                jac = len(toks & tf) / max(1, len(toks | tf))
                trovati.append((jac, pid, nome_fanta, squadra))
    if not trovati:
        # Rete di sicurezza per le grafie diverse ("Ndicka" / "N'Dicka"):
        # solo sul cognome, soglia alta.
        for pid, (nome_fanta, squadra) in giocatori.items():
            j = nome_fanta.replace(" ", "")
            if cognome and len(cognome) >= 5 and any(
                    M.levenshtein_ratio(cognome, M.normalize_name(x).replace(" ", "")) >= 0.9
                    for x in [nome_fanta.split(" ")[0] + (nome_fanta.split(" ")[1] if len(nome_fanta.split(" ")) > 1 and len(nome_fanta.split(" ")[0]) <= 2 else "")]):
                trovati.append((0.5, pid, nome_fanta, squadra))
    trovati.sort(key=lambda x: -x[0])
    return [(pid, nf, sq, jac) for jac, pid, nf, sq in trovati]


def main() -> int:
    print("\n▶ Elaborazione playerstats.football")

    players_file = DATA_DIR / "players.json"
    if not players_file.exists():
        print(f"  ✘ {players_file} non trovato (run scraper.py prima)")
        return 1
    with open(players_file, encoding='utf-8') as f:
        players_data = json.load(f)
    giocatori_fanta = M.indice_giocatori(players_data)
    pv_by_id = {p['id']: p.get('pv') or 0 for p in players_data['giocatori'] if p.get('id')}
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
    failed, ambigui, implausibili, collisioni = [], [], [], []
    id_in_collisione = set()

    for player_id_esterno, dati in righe.items():
        nome = (dati.get("nome") or "").strip()
        if not nome:
            continue

        cand = candidati_per_nome(nome, giocatori_fanta)
        if not cand:
            failed.append(nome)
            continue
        # Piu' candidati (omonimi in squadre diverse): decidono i minuti.
        ok = [c for c in cand if minuti_plausibili(dati.get("minuti"), pv_by_id.get(c[0]))]
        if not ok:
            implausibili.append(f"{nome} ({dati.get('minuti')} min) vs {', '.join(c[1] for c in cand)}")
            continue
        migliore = max(c[3] for c in ok)
        ok = [c for c in ok if c[3] == migliore]
        if len(ok) > 1:
            ambigui.append(f"{nome}: {', '.join(c[1] + ' ' + c[2] for c in ok)}")
            continue
        best_match_id = ok[0][0]

        voce = {k: v for k, v in dati.items() if k != "nome"}
        voce["playerstats_name"] = nome
        voce["match_score"] = 0.9
        if best_match_id in id_in_collisione:
            collisioni.append(f"{nome} (terza riga)")
            continue
        if best_match_id in risultato_by_id:
            id_in_collisione.add(best_match_id)
            # Due righe della fonte sullo stesso giocatore: non so quale e' giusta.
            collisioni.append(f"{nome} / {risultato_by_id[best_match_id]['playerstats_name']}")
            del risultato_by_id[best_match_id]
            matched -= 1
            continue
        risultato_by_id[best_match_id] = voce
        matched += 1

    print(f"  ✓ Matched: {matched} giocatori")
    if failed:
        print(f"    Senza corrispondenza ({len(failed)} totali, campione):")
        for name in failed[:10]:
            print(f"      - {name}")
    if ambigui:
        print(f"    Ambigui, scartati ({len(ambigui)}): {'; '.join(ambigui[:6])}")
    if implausibili:
        print(f"    Scartati per minuti incompatibili con le presenze ({len(implausibili)}):")
        for x in implausibili[:10]:
            print(f"      - {x}")
    if collisioni:
        print(f"    Collisioni (due righe, un giocatore), scartate ({len(collisioni)}): {'; '.join(collisioni[:6])}")

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
