# -*- coding: utf-8 -*-
"""
FANTALITICO — abbinamento nomi giocatori (modulo condiviso).

Le fonti esterne scrivono i nomi diversamente dal listone della Lega: Understat
"Francesco Pio Esposito", fantacalcio.it "Esposito F.P.". Il cognome puo' stare
in fondo o davanti, i nomi di battesimo essere abbreviati, e certi caratteri
(la i turca senza punto di Yildiz) sfuggire alla normalizzazione ordinaria.

Questa logica viveva dentro understat_process.py. Estratta qui perche' ogni
fonte che non fornisce gli id di fantacalcio.it deve rifare lo stesso lavoro,
e tre copie divergono al primo ritocco.

Regola di prudenza: se due candidati restano indistinguibili anche dopo squadra
e iniziali, NON si sceglie. Un dato mancante si vede nei log; un dato attribuito
al giocatore sbagliato no.
"""

import re
import unicodedata
from difflib import SequenceMatcher

SOGLIA = 0.65               # sotto questa somiglianza non si considera nemmeno
PUNTEGGIO_COGNOME = 0.90    # assegnato quando un token identificativo coincide

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
    # Fra i trattini c'è anche U+2011, quello unificatore: Calciomagazine lo usa
    # in Norton‑Cuffy, Loftus‑Cheek, Fitz‑Jim, e non è il segno meno normale.
    name = re.sub(r"[.'’ʼ`\-‐‑‒–—]", ' ', name)
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



def levenshtein_ratio(s1, s2):
    return SequenceMatcher(None, s1, s2).ratio()


def indice_giocatori(players_data):
    """Struttura attesa da abbina(), costruita da players.json."""
    return {
        p["id"]: (normalize_name(p["nome"]), p.get("squadra") or "")
        for p in players_data["giocatori"] if p.get("id")
    }


def abbina(nome_fonte, squadra_fonte, giocatori):
    """Ritorna (player_id, punteggio) oppure (None, motivo).

    motivo e' "ambiguo" oppure "nessun candidato".
    """
    norm = normalize_name(nome_fonte)
    token = token_identificativi(norm)

    candidati = []
    for pid, (nome_fanta, squadra_fanta) in giocatori.items():
        grezzo = levenshtein_ratio(norm, nome_fanta)
        score = grezzo
        if token & token_identificativi(nome_fanta):
            if not iniziali_compatibili(norm, nome_fanta):
                continue
            score = max(score, PUNTEGGIO_COGNOME)
        if score >= SOGLIA:
            candidati.append((score, grezzo, pid, squadra_fanta))

    if not candidati:
        return None, "nessun candidato"

    stessa = [c for c in candidati if stessa_squadra(squadra_fonte, c[3])]
    pool = stessa or candidati
    pool.sort(key=lambda c: (-c[0], -c[1]))
    if len(pool) > 1 and (pool[0][0], pool[0][1]) == (pool[1][0], pool[1][1]):
        return None, "ambiguo"
    return pool[0][2], round(pool[0][0], 3)
