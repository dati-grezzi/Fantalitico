# -*- coding: utf-8 -*-
"""
FANTALITICO — terza fonte per il consensus titolarità (Calciomagazine).

PERCHÉ
------
Il consensus aveva due fonti, ma su 461 giocatori solo 220 erano coperti da
entrambe: per gli altri 241 il "consensus" era una fonte sola. Calciomagazine
pubblica titolari E panchina di tutte e 20 le squadre — oltre 450 nomi — quindi
chiude proprio quel buco di copertura.

COSA DÀ, E QUANTO VALE
----------------------
La pagina non pubblica una percentuale per ogni giocatore come fantacalcio.it,
ma distingue quattro stati, che traduciamo in confidenze diverse:

  Titolari       → 0.85   (pronostico di redazione, non una certezza)
  Ballottaggi    → la percentuale vera, es. "Bellanova 55%-Zappacosta 45%"
  Panchina       → 0.15   (può subentrare, ma non parte)
  Squal./Indisp. → 0.02   (stesso valore usato da indiceTitolarita nell'app)

I ballottaggi sono la parte più preziosa: sono i casi dubbi, cioè quelli dove
le fonti divergono e dove sbagliare costa di più, ed è l'unico punto in cui
questa fonte dà un numero invece di un'etichetta.

NOTE TECNICHE
-------------
La pagina è HTML servito dal server (WordPress): niente Playwright, basta
requests. Il parsing lavora sul TESTO e non sui selettori CSS, perché le classi
di un tema WordPress cambiano a ogni restyling, mentre le etichette in grassetto
("Titolari:", "Panchina:") sono contenuto editoriale e restano.

I nomi seguono la stessa convenzione del listone ("Esposito F.P.", "Marin R."),
quindi l'abbinamento via match_nomi.py è quasi sempre esatto.

USO
---
  python calciomagazine_scraper.py
  python calciomagazine_scraper.py --dry-run    # non scrive il file
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_nomi as M

URL = "https://www.calciomagazine.net/probabili-formazioni"
FONTE = "calciomagazine.it"
OUT = "data/fonti_titolarita/calciomagazine.json"
PLAYERS = "data/players.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9",
}

CONF_TITOLARE = 0.85
CONF_PANCHINA = 0.15
CONF_FUORI = 0.02

MIN_GIOCATORI = 300     # sotto questa soglia la pagina è cambiata: non sovrascrivo

SQUADRE = ["atalanta", "bologna", "cagliari", "como", "fiorentina", "frosinone",
           "genoa", "inter", "juventus", "lazio", "lecce", "milan", "monza",
           "napoli", "parma", "roma", "sassuolo", "torino", "udinese", "venezia"]

# "Atalanta (4-3-3)" — inizio di un blocco squadra
RE_SQUADRA = re.compile(r"^\s*(" + "|".join(SQUADRE) + r")\s*\(([\d\-]+)\)\s*$", re.I)
# "Bellanova 55%-Zappacosta 45%"
RE_BALLO_SEMPLICE = re.compile(r"([A-ZÀ-Ü][\w'’.\-\u2011 ]*?)\s*(\d{1,3})\s*%")
# "Martinez L.-Bonny 55%-45%"  (i due nomi prima, le due percentuali dopo)
RE_BALLO_COPPIA = re.compile(
    r"([A-ZÀ-Ü][\w'’.\-\u2011 ]*?)\s*-\s*([A-ZÀ-Ü][\w'’.\-\u2011 ]*?)\s*(\d{1,3})\s*%\s*-\s*(\d{1,3})\s*%")

ETICHETTE = ["Titolari", "Panchina", "Allenatore", "Squalificati",
             "Indisponibili", "Diffidati", "Ballottaggi"]


def spezza_nomi(testo):
    """I nomi sono separati da ';' e ',' — le note fra parentesi vanno via."""
    if not testo:
        return []
    testo = re.sub(r"\([^)]*\)", "", testo)
    fuori = []
    for pezzo in re.split(r"[;,]", testo):
        n = pezzo.strip(" .-–—\u2011")
        if len(n) >= 2 and n != "-":
            fuori.append(n)
    return fuori


def blocchi_squadra(testo):
    """Divide il testo della pagina in un blocco per squadra."""
    blocchi, corrente = [], None
    for riga in [r.strip() for r in testo.split("\n")]:
        m = RE_SQUADRA.match(riga)
        if m:
            if corrente:
                blocchi.append(corrente)
            corrente = {"squadra": m.group(1).lower(), "righe": []}
        elif corrente is not None:
            corrente["righe"].append(riga)
    if corrente:
        blocchi.append(corrente)
    return blocchi


def sezioni(blocco):
    """Dal blocco squadra estrae {etichetta: testo}."""
    fuori, attuale = {}, None
    for riga in blocco["righe"]:
        trovata = next((et for et in ETICHETTE if riga.startswith(et + ":")), None)
        if trovata:
            attuale = trovata
            fuori[attuale] = riga.split(":", 1)[1].strip()
        elif attuale and riga:
            fuori[attuale] = (fuori.get(attuale, "") + " " + riga).strip()
    return fuori


def percentuali_ballottaggi(testo):
    """Ricava {nome: percentuale} dai ballottaggi, nei due formati usati."""
    fuori = {}
    if not testo or testo.strip() == "-":
        return fuori
    for pezzo in testo.split(","):
        pezzo = pezzo.strip()
        m = RE_BALLO_COPPIA.search(pezzo)
        if m:
            fuori[m.group(1).strip()] = int(m.group(3)) / 100
            fuori[m.group(2).strip()] = int(m.group(4)) / 100
            continue
        for m in RE_BALLO_SEMPLICE.finditer(pezzo):
            nome = m.group(1).strip(" -–—\u2011")
            if nome:
                fuori[nome] = int(m.group(2)) / 100
    return fuori


def raccogli(testo_pagina):
    """Ritorna la lista grezza [{nome, squadra, confidence, stato}]."""
    letture = []
    for b in blocchi_squadra(testo_pagina):
        sez = sezioni(b)
        ballo = percentuali_ballottaggi(sez.get("Ballottaggi", ""))
        ballo_norm = {M.normalize_name(k): v for k, v in ballo.items()}

        def aggiungi(nomi, conf, stato):
            for n in nomi:
                letture.append({
                    "nome": n, "squadra": b["squadra"],
                    "confidence": ballo_norm.get(M.normalize_name(n), conf),
                    "stato": stato,
                })

        aggiungi(spezza_nomi(sez.get("Titolari", "")), CONF_TITOLARE, "titolare")
        aggiungi(spezza_nomi(sez.get("Panchina", "")), CONF_PANCHINA, "panchina")
        for et in ("Squalificati", "Indisponibili"):
            aggiungi(spezza_nomi(sez.get(et, "")), CONF_FUORI, et.lower())
    return letture


def main():
    if not os.path.exists(PLAYERS):
        print(f"Manca {PLAYERS}: lancia prima scraper.py")
        return 1
    with open(PLAYERS, encoding="utf-8") as f:
        players = json.load(f)
    indice = M.indice_giocatori(players)
    print(f"Listone: {len(indice)} giocatori")

    print(f"Scarico {URL} ...")
    r = requests.get(URL, headers=HEADERS, timeout=40)
    r.raise_for_status()
    testo = BeautifulSoup(r.text, "lxml").get_text("\n")

    letture = raccogli(testo)
    if not letture:
        print("Nessuna lettura estratta: la struttura della pagina è cambiata.")
        idx = testo.find("Titolari")
        print("DIAGNOSTICA — testo attorno a 'Titolari':")
        print(testo[max(0, idx - 300):idx + 600] if idx >= 0 else testo[:800])
        return 1

    squadre_viste = {l["squadra"] for l in letture}
    print(f"Letture grezze: {len(letture)} su {len(squadre_viste)} squadre")

    giocatori, ambigui, falliti = {}, [], []
    for l in letture:
        pid, esito = M.abbina(l["nome"], l["squadra"], indice)
        if pid is None:
            (ambigui if esito == "ambiguo" else falliti).append(f"{l['nome']} ({l['squadra']})")
            continue
        chiave = str(pid)
        # Se un nome compare due volte (es. in panchina e fra gli indisponibili),
        # tengo la lettura più informativa: quella più lontana da 0.5.
        prec = giocatori.get(chiave)
        if prec and abs(prec["confidence"] - 0.5) >= abs(l["confidence"] - 0.5):
            continue
        giocatori[chiave] = {
            "nome": l["nome"], "squadra": l["squadra"],
            "confidence": round(l["confidence"], 2),
            "percentuale": round(l["confidence"] * 100),
            "stato": l["stato"],
            "match_score": esito,
        }

    print(f"Abbinati: {len(giocatori)}")
    if ambigui:
        print(f"  Ambigui, scartati per prudenza ({len(ambigui)}): {', '.join(ambigui[:8])}")
    if falliti:
        print(f"  Non trovati nel listone ({len(falliti)}): {', '.join(falliti[:10])}")
    if len(squadre_viste) < 20:
        print(f"  ATTENZIONE: solo {len(squadre_viste)}/20 squadre trovate")

    if len(giocatori) < MIN_GIOCATORI:
        print(f"Solo {len(giocatori)} giocatori (soglia {MIN_GIOCATORI}): non sovrascrivo il file.")
        return 1

    if "--dry-run" in sys.argv:
        print("(dry-run: nessun file scritto)")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "fonte": FONTE,
            "aggiornato": datetime.now(timezone.utc).isoformat(),
            "giornata": None,
            "giocatori": giocatori,
        }, f, ensure_ascii=False, indent=1)
    print(f"Scritto {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
