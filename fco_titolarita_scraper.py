# -*- coding: utf-8 -*-
"""
FANTALITICO — probabili formazioni da Fantacalcio-Online (FCO).

Perche' esiste
--------------
La pagina /it/serie-a/<stagione>/probabili-formazioni/<N>-giornata di
fantacalcio-online.com mette una accanto all'altra la percentuale di
schierabilita' che danno quattro redazioni: Fantacalcio.it, Gazzetta, SOS Fanta
e Sky, per ogni titolare e ogni giocatore in panchina di ogni squadra.

Ci da' due cose che non avevamo:
  1. DUE FONTI NUOVE e indipendenti: Gazzetta e Sky.
  2. COPERTURA: il nostro scraper di SOS Fanta vede ~220 giocatori e quello di
     fantacalcio.it ~465, FCO ne ha ~550 per ogni redazione. Le colonne FC e SOS
     vengono usate SOLO per i giocatori che i nostri scraper diretti non hanno
     (altrimenti la stessa redazione verrebbe contata due volte).

Il 17/10 il problema da risolvere era questo: 245 giocatori avevano una sola
fonte e il consenso su di loro e' il meno affidabile (AUC 0,77-0,79 contro
0,85-0,88 di chi ne ha due).

Controlli
---------
- Freschezza: "Ultima rilevazione: <data> alle <ora>" nella pagina. Piu' vecchia
  di 96 ore -> le fonti vengono svuotate (lezione Calciomagazine: una pagina
  ferma da agosto e' stata letta come attuale per sette settimane).
- Abbinamento: per squadra (titolo sopra la tabella) e per chiave del nome,
  senza fuzzy. In caso di piu' candidati NON si sceglie.
- Soglia minima di giocatori, sotto la quale i file non vengono toccati.

File scritti in data/fonti_titolarita/:
  fco_gazzetta.json (fonte gazzetta.it), fco_sky.json (fonte sky.it),
  fco_fantacalcio.json (fonte fantacalcio.it, solo buchi),
  fco_sosfanta.json (fonte sosfanta.com, solo buchi).

USO
---
  python fco_titolarita_scraper.py            # scrive i file
  python fco_titolarita_scraper.py --dry-run  # solo diagnostica
  python fco_titolarita_scraper.py --file pagina.html   # prova su HTML salvato
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_nomi as M

STAGIONE = "2026-2027"
URL_TPL = "https://www.fantacalcio-online.com/it/serie-a/{stagione}/probabili-formazioni/{n}-giornata"
PLAYERS = "data/players.json"
CALENDARIO = "data/calendario.json"
OUT_DIR = "data/fonti_titolarita"

MAX_ETA_ORE = 96
MIN_GIOCATORI = 250   # sotto, la struttura della pagina e' cambiata: non si scrive

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9",
}

# colonna della pagina -> (file, nome fonte, solo_buchi)
COLONNE = {
    "FC":  ("fco_fantacalcio.json", "fantacalcio.it", True),
    "GAZ": ("fco_gazzetta.json",    "gazzetta.it",    False),
    "SOS": ("fco_sosfanta.json",    "sosfanta.com",   True),
    "SKY": ("fco_sky.json",         "sky.it",         False),
}
ORDINE_DEFAULT = ["FC", "GAZ", "SOS", "SKY", "MEDIA"]

MESI = {m: i + 1 for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"])}

RE_PERC = re.compile(r"^(\d{1,3})\s*%$")
RE_TRATTINO = re.compile(r"^[–—-]$")
RE_RILEVAZIONE = re.compile(
    r"Ultima rilevazione:?\s*(\d{1,2})\s+([a-zà]+)\s+(\d{4})\s+alle\s+(\d{1,2})[:.](\d{2})", re.I)


# ── pagina ─────────────────────────────────────────────────────────────────
def giornata_da_calendario():
    with open(CALENDARIO, encoding="utf-8") as f:
        return int(json.load(f)["giornata"])


def data_rilevazione(testo):
    """Data dell'ultima rilevazione (ora italiana, approssimata a UTC+2/+1)."""
    m = RE_RILEVAZIONE.search(testo)
    if not m:
        return None
    g, mese, anno, h, mi = m.groups()
    mese = MESI.get(mese.lower())
    if not mese:
        return None
    # Ora legale fino all'ultima domenica di ottobre: per un controllo di
    # freschezza a 96 ore la differenza di un'ora e' irrilevante.
    return datetime(int(anno), mese, int(g), int(h), int(mi),
                    tzinfo=timezone(timedelta(hours=2)))


# ── nomi ───────────────────────────────────────────────────────────────────
def chiave(nome):
    """'Stankovic F.' -> 'stankovicf', "MONTIPO'L" -> 'montipol'."""
    return M.normalize_name(nome).replace(" ", "")


def chiavi_fco(testo):
    """Il nome FCO e' COGNOME + iniziale (STANKOVICF), a volte con la lettera del
    ruolo davanti. Restituisce le chiavi candidate, dalla piu' alla meno probabile."""
    t = (testo or "").strip()
    out = []
    parti = t.split()
    # ruolo separato: "P STANKOVIC F" / "P STANKOVICF"
    if len(parti) > 1 and len(parti[0]) == 1 and parti[0].upper() in "PDCA":
        out.append(chiave(" ".join(parti[1:])))
    k = chiave(t)
    out.append(k)
    # ruolo attaccato: "PSTANKOVICF"
    if len(k) > 3 and k[0] in "pdca":
        out.append(k[1:])
    visti, res = set(), []
    for x in out:
        if x and x not in visti:
            visti.add(x)
            res.append(x)
    return res


def costruisci_indice(players):
    """squadra -> lista di (pid, chiave_lega, nome, ruolo)."""
    per_squadra = {}
    for p in players["giocatori"]:
        if not p.get("id") or not p.get("squadra"):
            continue
        per_squadra.setdefault(p["squadra"], []).append(
            (p["id"], chiave(p["nome"]), p["nome"], p.get("ruolo")))
    return per_squadra


def abbina_riga(testo_nome, squadra_slug, indice):
    """(pid, nome_lega) oppure (None, motivo). Solo dentro la squadra."""
    candidati_squadra = indice.get(squadra_slug, [])
    for k in chiavi_fco(testo_nome):
        esatti = [c for c in candidati_squadra if c[1] == k]
        if len(esatti) == 1:
            return esatti[0][0], esatti[0][2]
        if len(esatti) > 1:
            return None, "ambiguo"
        # FCO ha una sola iniziale, il listone puo' averne due ("martinezj" ->
        # "martinezjo"); oppure il listone non ha iniziale ("hainaut" -> "hainauta").
        lunghi = [c for c in candidati_squadra if c[1].startswith(k) and 0 < len(c[1]) - len(k) <= 2]
        corti = [c for c in candidati_squadra if k.startswith(c[1]) and len(k) - len(c[1]) == 1 and len(c[1]) >= 3]
        trovati = lunghi or corti
        if len(trovati) == 1:
            return trovati[0][0], trovati[0][2]
        if len(trovati) > 1:
            return None, "ambiguo"
    # Ultima chance: nomi del listone fatti di piu' parole senza iniziale
    # ("Juan Jesus", "Zambo Anguissa") contro FCO "JESUS J", "ANGUISSA A". Il
    # cognome FCO (la chiave senza l'ultima lettera, che e' l'iniziale) deve essere
    # uno dei token del listone, e il candidato deve essere uno solo nella squadra.
    for k in chiavi_fco(testo_nome):
        if len(k) < 5:
            continue
        cognome = k[:-1]
        trovati = [c for c in candidati_squadra
                   if cognome in {t for t in M.normalize_name(c[2]).split() if len(t) >= 3}]
        if len(trovati) == 1:
            return trovati[0][0], trovati[0][2]
        if len(trovati) > 1:
            return None, "ambiguo"
    return None, "nessun candidato"


def squadra_slug(titolo, slugs):
    for s in slugs:
        if M.stessa_squadra(titolo, s):
            return s
    return None


# ── parsing ────────────────────────────────────────────────────────────────
def tipo_tabella(tabella):
    testo = tabella.get_text(" ", strip=True).lower()
    cima = testo[:200]
    if "panchina" in cima:
        return "panchina"
    if "titolar" in cima:
        return "titolare"
    return None


def ordine_colonne(tabella):
    """Legge le intestazioni (FC GAZ SOS SKY MEDIA) per non dipendere dall'ordine."""
    for tr in tabella.find_all("tr"):
        celle = [c.get_text(" ", strip=True).upper().rstrip("*") for c in tr.find_all(["th", "td"])]
        trovate = [c for c in celle if c in ("FC", "GAZ", "SOS", "SKY", "MEDIA")]
        if len(trovate) >= 4:
            return trovate
    return ORDINE_DEFAULT


def squadra_della_tabella(tabella, slugs):
    for h in tabella.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=8):
        s = squadra_slug(h.get_text(" ", strip=True), slugs)
        if s:
            return s
    return None


def valore(cella):
    t = cella.strip()
    m = RE_PERC.match(t)
    if m:
        return int(m.group(1))
    if RE_TRATTINO.match(t):
        return None
    return "NO"


def estrai(html, indice):
    zuppa = BeautifulSoup(html, "lxml")
    testo = zuppa.get_text(" ", strip=True)
    slugs = list(indice.keys())

    letture = {c: {} for c in COLONNE}   # colonna -> {pid: (percentuale, nome_fco, squadra, tipo)}
    righe_viste = scartate = 0
    non_abbinati, ambigui = [], []
    squadre_viste = set()

    for tabella in zuppa.find_all("table"):
        tipo = tipo_tabella(tabella)
        if not tipo:
            continue
        squadra = squadra_della_tabella(tabella, slugs)
        if not squadra:
            continue
        squadre_viste.add(squadra)
        ordine = ordine_colonne(tabella)

        for tr in tabella.find_all("tr"):
            celle = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(celle) < 6:
                continue
            valori = [valore(c) for c in celle[1:]]
            # le prime len(ordine) celle dopo il nome sono le percentuali
            perc = valori[:len(ordine)]
            if any(v == "NO" for v in perc):
                continue
            righe_viste += 1
            pid, nome_lega = abbina_riga(celle[0], squadra, indice)
            if pid is None:
                (ambigui if nome_lega == "ambiguo" else non_abbinati).append(f"{celle[0]} ({squadra})")
                scartate += 1
                continue
            for col, v in zip(ordine, perc):
                if col in letture and v is not None:
                    letture[col][pid] = (v, nome_lega, squadra, tipo)

    return {
        "letture": letture, "testo": testo, "righe": righe_viste, "scartate": scartate,
        "non_abbinati": non_abbinati, "ambigui": ambigui, "squadre": squadre_viste,
    }


# ── scrittura ──────────────────────────────────────────────────────────────
def carica_pid_diretti(nome_file):
    path = os.path.join(OUT_DIR, nome_file)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("giocatori", {}).keys())
    except Exception:
        return set()


FILE_DIRETTI = {"FC": "fantacalcio.json", "SOS": "sosfanta.json"}


def scrivi_fonte(file, fonte, giocatori, giornata, extra=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = {"fonte": fonte, "aggiornato": datetime.now(timezone.utc).isoformat(),
           "giornata": giornata, "via": "fantacalcio-online.com", "giocatori": giocatori}
    if extra:
        doc.update(extra)
    with open(os.path.join(OUT_DIR, file), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(PLAYERS):
        print(f"Manca {PLAYERS}: lancia prima scraper.py")
        return 1
    with open(PLAYERS, encoding="utf-8") as f:
        players = json.load(f)
    indice = costruisci_indice(players)

    if "--file" in sys.argv:
        with open(sys.argv[sys.argv.index("--file") + 1], encoding="utf-8") as f:
            html = f.read()
        giornata = giornata_da_calendario() if os.path.exists(CALENDARIO) else 0
    else:
        giornata = giornata_da_calendario()
        url = URL_TPL.format(stagione=STAGIONE, n=giornata)
        print(f"Scarico {url} ...")
        r = requests.get(url, headers=HEADERS, timeout=40)
        if r.status_code == 404:
            print(f"Pagina della giornata {giornata} non ancora pubblicata (404): fonti svuotate.")
            risultato = None
        else:
            r.raise_for_status()
            html = r.text
            risultato = True
        if risultato is None:
            if not dry:
                for col, (file, fonte, _) in COLONNE.items():
                    scrivi_fonte(file, fonte, {}, giornata, {"stale": True, "motivo": "pagina non pubblicata"})
            return 0

    ris = estrai(html, indice)
    print(f"Righe di giocatori lette: {ris['righe']} su {len(ris['squadre'])} squadre; "
          f"scartate {ris['scartate']}")
    if ris["ambigui"]:
        print(f"  Ambigui, scartati per prudenza ({len(ris['ambigui'])}): {', '.join(ris['ambigui'][:8])}")
    if ris["non_abbinati"]:
        print(f"  Non trovati nel listone ({len(ris['non_abbinati'])}): {', '.join(ris['non_abbinati'][:10])}")

    rilev = data_rilevazione(ris["testo"])
    if rilev is None:
        print("ATTENZIONE: data di rilevazione non trovata, non posso verificare la freschezza.")
    else:
        eta = datetime.now(timezone.utc) - rilev
        print(f"Ultima rilevazione: {rilev.isoformat()} ({eta.total_seconds() / 3600:.0f} ore fa)")
        if eta > timedelta(hours=MAX_ETA_ORE):
            print(f"Pagina ferma da oltre {MAX_ETA_ORE}h: fonti SVUOTATE, il consensus le ignora.")
            if not dry:
                for col, (file, fonte, _) in COLONNE.items():
                    scrivi_fonte(file, fonte, {}, giornata,
                                 {"stale": True, "contenuto_modificato": rilev.isoformat()})
            return 0

    if len(ris["squadre"]) < 18:
        print(f"ATTENZIONE: solo {len(ris['squadre'])}/20 squadre trovate (giornata con recuperi?)")

    totale = sum(len(v) for v in ris["letture"].values())
    if ris["righe"] < MIN_GIOCATORI:
        print(f"Solo {ris['righe']} righe (soglia {MIN_GIOCATORI}): non scrivo niente.")
        if ris["righe"] == 0:
            idx = ris["testo"].lower().find("probabili titolari")
            print("DIAGNOSTICA — testo attorno a 'Probabili titolari':")
            print(ris["testo"][max(0, idx - 200):idx + 600] if idx >= 0 else ris["testo"][:800])
        return 1

    for col, (file, fonte, solo_buchi) in COLONNE.items():
        gia = carica_pid_diretti(FILE_DIRETTI[col]) if solo_buchi and col in FILE_DIRETTI else set()
        giocatori = {}
        for pid, (perc, nome, squadra, tipo) in ris["letture"][col].items():
            if str(pid) in gia:
                continue
            giocatori[str(pid)] = {
                "nome": nome, "squadra": squadra,
                "confidence": round(perc / 100, 2), "percentuale": perc,
                "match_score": 1.0, "lista": tipo,
            }
        etichetta = f"(solo buchi, {len(gia)} gia' coperti dallo scraper diretto)" if solo_buchi else ""
        print(f"  {fonte:16s} {len(giocatori):4d} giocatori {etichetta}")
        if not dry:
            scrivi_fonte(file, fonte, giocatori, giornata)

    print("(dry-run: nessun file scritto)" if dry else f"Scritti i file in {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
