# -*- coding: utf-8 -*-
"""
FANTALITICO — Consensus Titolarità Reale
Legge TUTTI i file in data/fonti_titolarita/*.json (uno per fonte, stesso
schema: {fonte, giornata, giocatori:{player_id:{percentuale/confidence,...}}})
e li combina in data/titolarita_reale.json, il file che il motore (index.html)
legge in S.titolarita_reale.

Con 1 sola fonte disponibile (oggi: fantacalcio.it) il consensus coincide con
quella fonte. Quando altre fonti verranno aggiunte (stesso schema, tramite
player_name_matcher.py per il matching nome->id), si combinano automaticamente
in media pesata — nessuna modifica a questo script.

USO
---
  python titolarita_consensus.py
"""

import json
import glob
import os
from datetime import datetime, timezone
from collections import defaultdict

FONTI_DIR = "data/fonti_titolarita"
OUT_JSON = "data/titolarita_reale.json"

PESI_FONTE = {
    "fantacalcio.it": 1.0,
    "sosfanta.com": 0.8,      # meno storicamente validata di fantacalcio.it in questo progetto, peso minore
    # Terza fonte, aggiunta il 30/08 per coprire i giocatori visti da una sola
    # delle prime due. Peso più basso non per sfiducia nella redazione, ma
    # perché il suo segnale è meno fine: se non pubblica percentuali, la
    # confidence è quasi binaria e porta meno informazione di un "73%".
    "calciomagazine.it": 0.6,
}
PESO_DEFAULT = 0.5  # per fonti non ancora presenti in PESI_FONTE (nuove, non tarate)


def carica_fonti():
    fonti = []
    for path in sorted(glob.glob(os.path.join(FONTI_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        fonti.append(data)
    return fonti


def combina(fonti):
    """Per ogni player_id, media pesata delle 'confidence' tra le fonti che lo citano."""
    accumulo = defaultdict(list)
    anagrafica = {}

    for f in fonti:
        nome_fonte = f.get("fonte", "sconosciuta")
        peso = PESI_FONTE.get(nome_fonte, PESO_DEFAULT)
        for pid, g in f.get("giocatori", {}).items():
            conf = g.get("confidence")
            if conf is None and g.get("percentuale") is not None:
                conf = g["percentuale"] / 100
            if conf is None:
                continue
            match_score = g.get("match_score", 1.0)
            peso_effettivo = peso * match_score
            accumulo[pid].append((conf, peso_effettivo, nome_fonte))
            if pid not in anagrafica:
                anagrafica[pid] = {"nome": g.get("nome"), "squadra": g.get("squadra")}

    risultato = {}
    for pid, letture in accumulo.items():
        peso_tot = sum(p for _, p, _ in letture)
        if peso_tot <= 0:
            continue
        confidence = sum(c * p for c, p, _ in letture) / peso_tot
        # Conserviamo anche il valore GREZZO di ogni fonte, non solo la media.
        # Senza questo, se il consensus dà un numero sospetto non c'è modo di
        # sapere quale fonte l'ha prodotto: i file per-fonte vivono solo dentro
        # il runner e non vengono committati. Costa pochi byte e permette di
        # misurare quanto le fonti sono davvero d'accordo — che è la domanda
        # che dice se l'incrocio sta lavorando o se stiamo solo ricopiando
        # due volte lo stesso dato.
        valori = {fn: round(c, 3) for c, _, fn in letture}
        scarto = round(max(valori.values()) - min(valori.values()), 3) if len(valori) > 1 else None
        risultato[pid] = {
            **anagrafica[pid],
            "confidence": round(confidence, 3),
            "fonti": [fn for _, _, fn in letture],
            "n_fonti": len(letture),
            "valori": valori,
            "scarto": scarto,
        }
    return risultato


def main():
    fonti = carica_fonti()
    if not fonti:
        print(f"Nessuna fonte trovata in {FONTI_DIR}/ - lancia prima uno scraper")
        return 1

    print(f"{len(fonti)} fonte/i trovate:")
    for f in fonti:
        print(f"   {f.get('fonte','?'):20s} - {len(f.get('giocatori',{}))} giocatori, giornata {f.get('giornata')}")

    consensus = combina(fonti)
    print(f"\nConsensus calcolato per {len(consensus)} giocatori")

    multi_fonte = [pid for pid, g in consensus.items() if g["n_fonti"] > 1]
    print(f"   di cui {len(multi_fonte)} confermati da piu' di una fonte")

    # Quanto sono d'accordo le fonti, dove si sovrappongono
    scarti = [consensus[pid]["scarto"] for pid in multi_fonte if consensus[pid]["scarto"] is not None]
    if scarti:
        scarti_ord = sorted(scarti)
        medio = sum(scarti) / len(scarti)
        mediano = scarti_ord[len(scarti_ord) // 2]
        concordi = sum(1 for x in scarti if x <= 0.10)
        # Ordino con una chiave esplicita sul solo scarto: confrontando le
        # tuple intere, a parita' di scarto Python finiva per confrontare i
        # dizionari dei valori e sollevava TypeError.
        discordi = sorted(
            (pid for pid in multi_fonte if consensus[pid]["scarto"] is not None),
            key=lambda pid: consensus[pid]["scarto"],
            reverse=True,
        )[:5]
        print(f"   scarto tra fonti: medio {medio:.3f}, mediano {mediano:.3f}")
        print(f"   d'accordo entro 10 punti: {concordi}/{len(scarti)} ({100*concordi/len(scarti):.0f}%)")
        print("   maggiori disaccordi:")
        for pid in discordi:
            g = consensus[pid]
            dettaglio = " vs ".join(f"{fn} {v:.2f}" for fn, v in g["valori"].items())
            print(f"      {(g.get('nome') or '?'):22s} scarto {g['scarto']:.2f}  ({dettaglio})")

    os.makedirs("data", exist_ok=True)
    output = {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "fonti_usate": [f.get("fonte") for f in fonti],
        "giocatori": consensus,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Salvato in {OUT_JSON}")

    print("\nAnteprima (10 giocatori):")
    for pid, g in list(consensus.items())[:10]:
        print(f"   id={pid:>6s}  {str(g['nome']):20s}  confidence={g['confidence']}  fonti={g['fonti']}")

    return 0


if __name__ == "__main__":
    exit(main())
