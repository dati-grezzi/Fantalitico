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


# Caratteri che la scomposizione NFD non tocca, perché non sono lettera+accento
# ma lettere a sé: la ı turca di Yıldız, la ø nordica, la đ croata. Senza questa
# mappa il confronto fallisce anche quando i due nomi sono identici a occhio.
TRADUZIONE = str.maketrans({
    'ı': 'i', 'ø': 'o', 'đ': 'd', 'ð': 'd', 'ł': 'l', 'ß': 'ss',
    'æ': 'ae', 'œ': 'oe', 'þ': 'th',
})

# Particelle dei cognomi composti: da sole non identificano nessuno, e se
# entrassero nel confronto per token farebbero combaciare "De Bruyne" con
# "De Ketelaere".
PARTICELLE = {'de', 'di', 'da', 'del', 'della', 'dei', 'dos', 'van', 'von',
              'der', 'den', 'el', 'al', 'la', 'le', 'bin', 'ben', 'mac', 'mc'}


def normalize_name(name: str) -> str:
    """Normalizza nomi per il matching fuzzy."""
    if not name:
        return ""
    name = name.lower().strip().translate(TRADUZIONE)
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    # Punti, apostrofi (anche quello tipografico) e trattini diventano spazi:
    # "Esposito F.P." → "esposito f p", "N'Dri" → "n dri", "Abdou-Salam" → due token.
    name = re.sub(r"[.'’ʼ`\-]", ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def token_identificativi(nome_norm: str) -> set:
    """I token che possono fare da cognome: almeno 3 lettere, non particelle.

    Serve perché le due fonti mettono il cognome in posizioni diverse:
    Understat scrive "Francesco Pio Esposito", fantacalcio.it "Esposito F.P.".
    Confrontare gli insiemi invece delle posizioni risolve entrambi i versi.
    """
    return {t for t in nome_norm.split() if len(t) >= 3 and t not in PARTICELLE}


def iniziali_compatibili(nome_understat: str, nome_fanta: str) -> bool:
    """Controlla le iniziali quando il listone abbrevia il nome di battesimo.

    Il listone distingue gli omonimi con le iniziali: "Martinez Jo." (Josep) e
    "Martinez L." (Lautaro) sono due giocatori diversi della stessa squadra, e
    né il cognome né la squadra li separano. Understat scrive il nome per
    esteso, quindi il confronto è fra "jo" e "lautaro" → incompatibili.

    Se il nome del listone non ha abbreviazioni (es. "Kalulu") non c'è niente
    da verificare e la funzione lascia passare.
    """
    # Le particelle sono corte ma non sono abbreviazioni: in "Di Lorenzo" il
    # "di" fa parte del cognome, non è l'iniziale di un nome di battesimo.
    corti = [t for t in nome_fanta.split() if len(t) < 3 and t not in PARTICELLE]
    if not corti:
        return True
    cognomi = token_identificativi(nome_fanta)
    # Due letture dei nomi propri, perché una particella può essere davvero tale
    # ("Koni de Winter") oppure far parte del nome di battesimo ("El Bilal
    # Touré", che il listone abbrevia in "Tourè E."). Basta che una delle due
    # regga: rifiutare richiede che siano incompatibili entrambe.
    completi = [t for t in nome_understat.split() if t not in cognomi]
    filtrati = [t for t in completi if t not in PARTICELLE]

    def compatibile(nomi_propri):
        if not nomi_propri:
            # Understat ha solo il cognome (i mononimi tipo "Vitinha"): non c'è
            # niente da smentire, decide semmai il controllo di ambiguità a valle.
            return True
        # "F.P." → ['f','p'] contro ['francesco','pio']; "Jo." → ['jo'] contro ['lautaro'].
        return all(proprio.startswith(abbrev)
                   for abbrev, proprio in zip(corti, nomi_propri))

    return compatibile(completi) or compatibile(filtrati)


def normalize_team(nome: str) -> str:
    """Riduce il nome squadra a confronto: 'AC Milan' e lo slug 'milan' combaciano."""
    if not nome:
        return ""
    n = normalize_name(nome)
    n = re.sub(r'\b(ac|as|ss|us|fc|cfc|hellas|calcio|1909|1913)\b', ' ', n)
    return re.sub(r'[^a-z]', '', n)


def stessa_squadra(squadra_understat: str, slug_fanta: str) -> bool:
    a, b = normalize_team(squadra_understat), normalize_team(slug_fanta)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def levenshtein_ratio(s1: str, s2: str) -> float:
    return SequenceMatcher(None, s1, s2).ratio()


def to_float(s, default=0.0):
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def to_float_o_nulla(s):
    """Come to_float, ma un valore mancante resta None invece di diventare 0.

    Distinzione tutt'altro che accademica. perfBonus() salta i segnali a null,
    mentre uno zero lo tratta come misurazione vera: con mean 2,451 e sd 0,943,
    zero tiri p90 dà z = -2,6, che il cap porta a -2 e produce il malus MASSIMO
    di -0,42. Cioè il motore puniva al massimo proprio i giocatori di cui non
    aveva il dato — l'opposto di quello che deve fare.
    Scoperto l'1/09/2026 su Esposito F.P., che aveva shots_p90 = 0 insieme a
    xG90 = 0,96: impossibile aver creato quasi un gol atteso ogni 90 minuti
    senza mai tirare.
    """
    if s is None:
        return None
    t = str(s).strip()
    if t == "" or t == "-":
        return None
    try:
        return float(t)
    except (ValueError, TypeError):
        return None


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
    giocatori_fanta = {
        p['id']: (normalize_name(p['nome']), p.get('squadra') or '')
        for p in players_data['giocatori'] if p.get('id')
    }
    print(f"  Caricati {len(giocatori_fanta)} giocatori da players.json")

    if not CSV_IN.exists():
        print(f"  ✘ {CSV_IN} non trovato")
        print(f"     Run understat_pull.py prima per generare il CSV")
        return 1

    understat_by_id = {}
    matched = 0
    scartati_pochi_minuti = 0
    failed = []
    ambigui = []

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
            squadra_understat = (row.get('team') or '').strip()
            token_under = token_identificativi(understat_norm)

            # Raccolgo TUTTI i candidati sopra soglia, non solo il migliore:
            # con 23 cognomi ripetuti nel listone (Esposito, Thuram, Martinez,
            # Colombo...) il punteggio più alto da solo non basta, serve la
            # squadra per disambiguare.
            candidati = []
            for player_id, (fanta_name, fanta_squadra) in giocatori_fanta.items():
                grezzo = levenshtein_ratio(understat_norm, fanta_name)
                score = grezzo
                if token_under & token_identificativi(fanta_name):
                    if not iniziali_compatibili(understat_norm, fanta_name):
                        continue          # stesso cognome ma nome di battesimo diverso
                    score = max(score, 0.90)
                if score >= 0.65:
                    # il punteggio grezzo resta come spareggio fra pari merito
                    candidati.append((score, grezzo, player_id, fanta_squadra))

            best_match_id = None
            best_score = 0.0
            if candidati:
                stessa = [c for c in candidati if stessa_squadra(squadra_understat, c[3])]
                pool = stessa or candidati
                pool.sort(key=lambda c: (-c[0], -c[1]))
                # Se due candidati restano indistinguibili anche dopo squadra e
                # iniziali, meglio nessun dato che il dato di un altro.
                if len(pool) > 1 and (pool[0][0], pool[0][1]) == (pool[1][0], pool[1][1]):
                    ambigui.append(f"{nome} ({squadra_understat})")
                else:
                    best_score, _, best_match_id, _ = pool[0]

            if best_match_id:
                understat_by_id[best_match_id] = {
                    "apps": to_int(row.get('apps')),
                    "minutes_total": minuti,
                    "goals": to_float_o_nulla(row.get('goals')),
                    "assists": to_float_o_nulla(row.get('assists')),
                    "xG": to_float_o_nulla(row.get('xG')),
                    "xA": to_float_o_nulla(row.get('xA')),
                    "xG90": to_float_o_nulla(row.get('xG90')),
                    "xA90": to_float_o_nulla(row.get('xA90')),
                    # Nomi allineati a quelli che cerca perfBonus() in index.html:
                    # PERF_W.ruoli.A usa shots_p90 (beta 0,112). Se il campo arriva
                    # con un nome diverso il motore lo ignora in silenzio e il bonus
                    # attaccanti resta a zero, che è esattamente il bug del 25/08.
                    "shots_p90": to_float_o_nulla(row.get('sh90')),
                    "key_passes_p90": to_float_o_nulla(row.get('kp90')),
                    # In cassaforte dal 02/09/2026: raccolti ma NON ancora usati
                    # dal motore. I beta della Parte 2.4 valgono per tiri e xA,
                    # non per questi campi: prima la calibrazione, poi il codice.
                    "npg": to_float_o_nulla(row.get('npg')),
                    "npxG": to_float_o_nulla(row.get('npxg')),
                    "npxG90": to_float_o_nulla(row.get('npxg90')),
                    "xGChain90": to_float_o_nulla(row.get('xgchain90')),
                    "xGBuildup90": to_float_o_nulla(row.get('xgbuildup90')),
                    "understat_name": nome,
                    "match_score": round(best_score, 3),
                }
                matched += 1
            else:
                failed.append((nome, minuti))

    print(f"  Scartati per pochi minuti (<{MIN_MINUTI}'): {scartati_pochi_minuti}")
    print(f"  ✓ Matched: {matched} giocatori")
    if ambigui:
        print(f"    ⚠️  Ambigui, scartati per prudenza ({len(ambigui)}): {', '.join(ambigui[:8])}")

    if failed:
        print(f"    Falliti ({len(failed)} totali, campione):")
        for name, mins in failed[:10]:
            print(f"      - {name} ({mins} min)")

    import datetime as dt
    result = {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fonte": "Understat (tabella Players, totali di stagione)",
        "note": "Mapping ID fantacalcio → {apps, minutes_total, goals, assists, xG, xA, xG90, xA90, shots_p90, key_passes_p90}. Da understat_players_2026.csv.",
        "giocatori": understat_by_id
    }
    with open(DATA_DIR / "understat.json", "w", encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"  ✔ scritto data/understat.json ({len(understat_by_id)} giocatori)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
