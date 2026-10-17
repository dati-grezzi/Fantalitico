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
import re
import sys
import os
from collections import defaultdict
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
    senza_nome = []
    for team in teams_data:
        if not isinstance(team, dict) or "players" not in team:
            squadre_saltate.append(team.get("team", "?") if isinstance(team, dict) else str(team)[:50])
            continue

        squadra = (team.get("team") or "").strip().lower()
        for p in team["players"]:
            if not p.get("player_id"):
                continue  # giocatori senza id (raro, es. nome non linkato) scartati

            # Guardrail anagrafica: una riga senza nome non è attribuibile a
            # nessuno. In passato righe del genere (id presi da un attributo
            # sbagliato, fuori dal range del listone) sono finite nello storico
            # come voci fantasma, e in 3 casi hanno pure sovrascritto giocatori
            # veri collidendo sull'id. Meglio perderle che sporcare lo storico.
            if not (p.get("name") or "").strip():
                senza_nome.append(str(p.get("player_id")))
                continue

            voto_puro = p.get("voto_puro")
            fantavoto = p.get("fantavoto")
            # Il voto puro in Classic non supera mai ~11 (nemmeno con Player of the
            # Match) — il fantavoto invece può salire parecchio con più bonus insieme
            # (es. tripletta = +9), quindi controllo la soglia solo sul voto puro.
            if voto_puro is not None and abs(voto_puro) > 11:
                print(f"⚠️  Valore sospetto: {p.get('name')} (id={p.get('player_id')}) voto_puro={voto_puro} — verifica a vista")

            rows.append({
                "player_id": p["player_id"],
                "nome": p.get("name"),
                "squadra": squadra,
                "ruolo": p.get("role"),
                "giornata": giornata,
                # voto_puro: usato dal Modificatore di Difesa in Top 11 (media
                # portiere + 3 migliori difensori). fantavoto: già calcolato dallo
                # scraper sommando i bonus/malus reali (gol, assist, ammonizioni...)
                # al voto puro — è il numero giusto per il punteggio complessivo.
                "voto_consensus": voto_puro,
                "fantavoto_consensus": fantavoto,
                "eventi": p.get("eventi", []),
            })

    if squadre_saltate:
        print(f"⚠️  {len(squadre_saltate)} blocchi squadra saltati (formato inatteso, niente 'players'): {squadre_saltate}")

    if senza_nome:
        print(f"⚠️  {len(senza_nome)} righe scartate perché senza nome (id: {', '.join(senza_nome[:10])}"
              f"{'...' if len(senza_nome) > 10 else ''})")
        print("    Se il numero è alto, lo scraper ha smesso di collegare i nomi: controllalo.")

    return rows


# Bonus/malus a evento, per riverificare i fantavoti gia' nello storico.
_BONUS = {"Gol segnato": 3, "Assist": 1, "Assist soft": 1, "Assist GOLD": 1,
          "Ammonizione": -0.5, "Espulsione": -1, "Autogol": -2, "Autorete": -2,
          "Rigore parato": 3, "Rigore sbagliato": -3, "Man of the match": 0,
          "Uscito per infortunio": 0}


def _fv_atteso(voto, eventi):
    """voto + bonus dagli eventi, oppure None se compare un evento sconosciuto.
    Il campo 'count' e' l'indice progressivo dell'evento (il 2o gol ha count 2),
    quindi per ogni tipo vale il massimo, non la somma."""
    massimi = defaultdict(int)
    for e in eventi:
        t = re.sub(r"\s*\(.*\)", "", e.get("tipo", "")).strip()
        try:
            massimi[t] = max(massimi[t], int(e.get("count", 1)))
        except (TypeError, ValueError):
            return None
    tot = 0
    for t, c in massimi.items():
        if t == "Gol subito":
            tot -= c
        elif t in _BONUS:
            tot += _BONUS[t] * c
        else:
            return None
    return voto + tot


def ripara_fantavoti(storico):
    """Corregge i fantavoti a cui e' stata tolta una cifra: un fantavoto intero
    fra 11 e 30 (8 + 3 di bonus = 11) veniva diviso per 10 e diventava 1,1.
    Capitato a Dybala G1, Bracaglia G2, Varela G5.

    Con gli eventi si riconosce con certezza (voto + bonus = fantavoto x 10).
    Senza eventi (pagina aggregata) si interviene solo nel caso inequivocabile:
    fantavoto molto sotto il voto e fantavoto x 10 a distanza plausibile da
    esso. Idempotente: a una seconda passata non trova piu' niente."""
    riparati = []
    for pid, r in storico.items():
        for g, v in r.get("giornate", {}).items():
            voto, fv = v.get("voto_consensus"), v.get("fantavoto_consensus")
            if voto is None or fv is None or not (0 < fv < 3.1):
                continue
            candidato = round(fv * 10, 1)
            ev = v.get("eventi") or []
            if ev:
                atteso = _fv_atteso(voto, ev)
                ok = atteso is not None and abs(atteso - fv) > 0.01 and abs(atteso - candidato) < 0.01
            else:
                ok = (fv - voto <= -3.5 and r.get("ruolo") != "p"
                      and 0 <= candidato - voto <= 7 and candidato <= 30)
            if ok:
                v["fantavoto_consensus"] = candidato
                riparati.append(f"{r.get('nome')} G{g}: {fv} -> {candidato}")
    return riparati


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
            # L'anagrafica va rinfrescata, non solo creata: prima veniva scritta
            # una volta sola alla creazione del record, così un record nato male
            # restava sbagliato per sempre. Serve anche per chi cambia squadra
            # a mercato aperto.
            storico[pid]["nome"] = r["nome"]
            storico[pid]["squadra"] = r["squadra"]
            storico[pid]["ruolo"] = r["ruolo"]
            aggiornati += 1

        storico[pid]["giornate"][str(giornata)] = {
            "voto_consensus": r["voto_consensus"],
            "fantavoto_consensus": r["fantavoto_consensus"],
            "eventi": r["eventi"],
        }

    riparati = ripara_fantavoti(storico)
    if riparati:
        print(f"🔧 {len(riparati)} fantavoti riparati (cifra persa): {'; '.join(riparati[:10])}")

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
