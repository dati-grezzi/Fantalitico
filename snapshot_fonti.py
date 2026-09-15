# -*- coding: utf-8 -*-
"""
FANTALITICO — archivio storico delle fonti statistiche.

PERCHÉ ESISTE
-------------
I file understat.json, playerstats.json e titolarita_reale.json contengono
sempre e solo la fotografia di OGGI: a ogni run vengono sovrascritti. Va bene
per l'app, che vuole l'ultimo dato, ma rende impossibile la cosa che serve al
motore — misurare i pesi.

Il tentativo di calibrazione del 15/09/2026 si è arenato proprio qui: l'xG di
un giocatore era calcolato sulle stesse quattro giornate del suo fantavoto,
quindi la correlazione misurava il passato invece di predire il futuro (la
correlazione fra xG90 e gol già segnati era 0,64). Per una regressione pulita
servono i valori di una settimana e i voti di quella successiva.

Ogni giorno senza archivio è un giorno di dati perso per sempre: questo è il
motivo per cui lo script ha la precedenza su tutto il resto.

COSA FA
-------
Copia i feed in data/storico_fonti/AAAA-MM-GG/. Una cartella per giorno, con
l'ultima versione della giornata (la seconda run del giorno sovrascrive la
prima: piu' vicina alla partita, quindi piu' informativa).

I file sono piccoli — qualche decina di KB l'uno — quindi un anno di archivio
resta nell'ordine dei megabyte.

USO
---
  python snapshot_fonti.py
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"
ARCHIVIO = DATA / "storico_fonti"

# Solo i feed che servono a calibrare: i predittori del bonus performance e la
# titolarita'. Classifica e calendario si ricostruiscono da altre fonti,
# players.json cambia poco, i voti hanno gia' il loro storico per giornata.
DA_ARCHIVIARE = [
    "understat.json",
    "playerstats.json",
    "titolarita_reale.json",
]


def main() -> int:
    oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cartella = ARCHIVIO / oggi
    cartella.mkdir(parents=True, exist_ok=True)

    copiati, saltati = [], []
    for nome in DA_ARCHIVIARE:
        sorgente = DATA / nome
        if not sorgente.exists():
            saltati.append(f"{nome} (non esiste)")
            continue
        try:
            with open(sorgente, encoding="utf-8") as f:
                contenuto = json.load(f)
        except Exception as e:
            saltati.append(f"{nome} (illeggibile: {e})")
            continue

        # Un feed vuoto non va archiviato: sporcherebbe la serie storica con
        # un buco che sembra un dato.
        giocatori = contenuto.get("giocatori", contenuto)
        if not isinstance(giocatori, dict) or len(giocatori) < 10:
            saltati.append(f"{nome} (solo {len(giocatori) if hasattr(giocatori, '__len__') else '?'} voci)")
            continue

        shutil.copy2(sorgente, cartella / nome)
        copiati.append(f"{nome} ({len(giocatori)} voci)")

    print(f"📦 Archivio {oggi}")
    for c in copiati:
        print(f"   ✔ {c}")
    for s in saltati:
        print(f"   ✘ saltato: {s}")

    giorni = sorted(p.name for p in ARCHIVIO.iterdir() if p.is_dir())
    print(f"   Giorni archiviati finora: {len(giorni)}"
          + (f" (dal {giorni[0]} al {giorni[-1]})" if giorni else ""))

    if not copiati:
        print("   ⚠️  Niente archiviato: controllare che la pipeline abbia girato prima.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
