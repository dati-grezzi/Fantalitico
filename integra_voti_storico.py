# -*- coding: utf-8 -*-
"""
INTEGRAZIONE VOTI GIORNATA → voti_storico.json
Prende l'output di voti_giornata_scraper_v2.py (formato per-squadra) e:
  1. Appiattisce per player_id (stesso ID di players.json → matching diretto)
  2. Calcola il CONSENSUS tra le 3 redazioni (media semplice, scartando i null)
  3. Accumula nello storico voti_storico.json (una riga per player_id x giornata)

USO
---
  python integra_voti_storico.py voti_giornata_16.json 16
"""

import json
import sys
import os
from pathlib import Path

STORICO_PATH = "data/voti_storico.json"


def flatten(teams_data, giornata):
    """Appiattisce il formato per-squadra prodotto dallo scraper attuale:
    [{team: "Inter", players: [{player_id, name, role, fantavoto, eventi}]}]
    — un solo fantavoto per giocatore (verificato contro fonti esterne), non
    più 3 redazioni da mediare come nella versione precedente del sito.
    Difensiva: una squadra con formato inatteso viene saltata con un avviso,
    non manda in crash tutto lo script."""
    rows = []
    squadre_saltate = []
    for team in teams_data:
        if not isinstance(team, dict) or "players" not in team:
            squadre_saltate.append(team.get("team", "?") if isinstance(team, dict) else str(team)[:50])
            continue

        squadra = (team.get("team") or "").strip().lower()
        for p in team["players"]:
            if not p.get("player_id"):
                continue  # giocatori senza id (raro, es. nome non linkato) scartati

            fantavoto = p.get("fantavoto")
            if fantavoto is not None and abs(fantavoto) > 15:
                print(f"⚠️  Valore sospetto: {p.get('name')} (id={p.get('player_id')}) fantavoto={fantavoto} — verifica a vista")

            rows.append({
                "player_id": p["player_id"],
                "nome": p.get("name"),
                "squadra": squadra,
                "ruolo": p.get("role"),
                "giornata": giornata,
                # NOTA: il nostro scraper cattura un solo numero per giocatore (non
                # più voto e fantavoto separati come nella versione precedente del
                # sito) — non è ancora chiaro con certezza se sia voto puro o
                # fantavoto. Finché non lo chiariamo, popolo entrambi i campi con
                # lo stesso valore: l'app (Modificatore di Difesa in Top 11) si
                # aspetta "voto_consensus" per funzionare, e senza questo campo
                # restava null, rompendo il calcolo — meglio un'approssimazione
                # dichiarata che un dato mancante silenzioso.
                "voto_consensus": fantavoto,
                "fantavoto_consensus": fantavoto,
                "eventi": p.get("eventi", []),
            })

    if squadre_saltate:
        print(f"⚠️  {len(squadre_saltate)} blocchi squadra saltati (formato inatteso, niente 'players'): {squadre_saltate}")

    return rows


def load_storico():
    if Path(STORICO_PATH).exists():
        with open(STORICO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_storico(storico):
    os.makedirs("data", exist_ok=True)
    with open(STORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(storico, f, ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 3:
        print("Uso: python integra_voti_storico.py <file_voti_giornata.json> <numero_giornata>")
        return 1

    voti_path, giornata = sys.argv[1], int(sys.argv[2])

    with open(voti_path, encoding="utf-8") as f:
        teams_data = json.load(f)

    rows = flatten(teams_data, giornata)
    print(f"✅ {len(rows)} giocatori appiattiti dalla giornata {giornata}")

    anomalie = [r for r in rows if r["fantavoto_consensus"] is None]
    if anomalie:
        print(f"⚠️  {len(anomalie)} giocatori senza fantavoto valido (probabile non giocato):")
        for a in anomalie[:5]:
            print(f"   {a['nome']} (id={a['player_id']})")

    # Carica storico esistente e integra (keyed by player_id → lista giornate)
    storico = load_storico()
    aggiornati, nuovi = 0, 0

    for r in rows:
        pid = r["player_id"]
        if pid not in storico:
            storico[pid] = {"nome": r["nome"], "squadra": r["squadra"], "ruolo": r["ruolo"], "giornate": {}}
            nuovi += 1
        else:
            aggiornati += 1

        storico[pid]["giornate"][str(giornata)] = {
            "voto_consensus": r["voto_consensus"],
            "fantavoto_consensus": r["fantavoto_consensus"],
            "eventi": r["eventi"],
        }

    save_storico(storico)
    print(f"\n📝 voti_storico.json aggiornato: {nuovi} giocatori nuovi, {aggiornati} aggiornati")
    print(f"   Totale giocatori nello storico: {len(storico)}")

    # Anteprima consensus (dopo il salvataggio, che è già avvenuto sopra —
    # robusta a nomi/id mancanti, non deve più bloccare nulla di importante)
    print("\n📊 Anteprima (primi 5):")
    for r in rows[:5]:
        nome = r.get("nome") or "(nome mancante)"
        pid = str(r.get("player_id") or "?")
        squadra = r.get("squadra") or "?"
        print(f"   {nome:20s} id={pid:>6s} squadra={squadra:12s} FV={r.get('fantavoto_consensus')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
