# -*- coding: utf-8 -*-
"""
FANTALITICO — pipeline dati
Scarica statistiche giocatori (tabella pubblica fantacalcio.it),
classifica, calendario, rigoristi e indisponibili di Serie A,
e salva tutto come JSON nella cartella /data, pronta per la PWA.

Ogni fonte è indipendente: se una fallisce, le altre vengono
comunque aggiornate e il JSON precedente resta al suo posto.
"""

import io
import json
import re
import sys
import datetime as dt
from pathlib import Path

import requests
import pandas as pd

BASE = "https://www.fantacalcio.it"

CLASSIFICA_URL = f"{BASE}/serie-a/classifica"
RIGORISTI_URL = f"{BASE}/rigoristi-serie-a"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ── UTILITÀ ───────────────────────────────────────────────────────
def fetch(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    return r


def save_json(name: str, payload) -> None:
    path = DATA_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"  ✔ scritto {path.name}")


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


# ── 1. STATISTICHE GIOCATORI (tabella HTML, nessun login richiesto) ──
def job_statistiche() -> None:
    """
    RIPORTATO IL 25/08/2026 a una richiesta HTTP semplice, dopo un tentativo
    con Playwright che ha creato più problemi di quanti ne risolvesse (falsi
    blocchi, rilevamento bot). Non avevo mai verificato con certezza che una
    richiesta semplice non prendesse dati reali — l'avevo solo supposto per
    analogia con altre pagine del sito che DAVVERO richiedono JavaScript.
    Se questa pagina è invece renderizzata lato server (come diceva il
    commento originale), la richiesta semplice dovrebbe bastare.

    La logica di estrazione (allineamento celle-intestazioni per nome,
    euristiche multiple per il ruolo) resta INVARIATA.
    """
    from bs4 import BeautifulSoup

    html = fetch(f"{BASE}/statistiche-serie-a").text

    soup = BeautifulSoup(html, "lxml")

    # La riga di intestazione vera è quella con celle data-col-key="mv" e
    # data-col-key="mfv" (FM) — identificatori diretti e univoci, molto più
    # solidi del testo o del title (che sta sull'<a> annidato, non sul <th>).
    # NON uso più "tr th" per trovarla: le righe DATI usano <th> anche per i
    # primi campi (nome, ruoli) — un selettore così ampio mescola centinaia
    # di celle giocatore con le vere intestazioni, sballando tutto (bug
    # scoperto il 25/08 dopo 3 tentativi falliti con altri approcci).
    header_row = soup.select_one('th[data-col-key="mv"]')
    header_row = header_row.find_parent("tr") if header_row else None
    if header_row is None:
        raise ValueError("Riga di intestazione (con data-col-key='mv') non trovata nella pagina")
    table = header_row.find_parent("table")
    if table is None:
        raise ValueError("Tabella statistiche non trovata a partire dalla riga di intestazione")

    header_cells = header_row.find_all(["th", "td"], recursive=False)
    # Mappa: data-col-key vero → nostra etichetta interna
    COLKEY_PER_LABEL = {
        "sq": "sq", "pv": "pg", "mv": "mv", "fm": "mfv",
        "gol": "gol", "golSubiti": "gs", "rig": "rig",
        "rigoriParati": "rp", "assist": "ass",
        "ammonizioni": "amm", "espulsioni": "esp", "autogol": "au",
    }
    colkey_to_index = {}
    for i, th in enumerate(header_cells):
        k = th.get("data-col-key")
        if k:
            colkey_to_index[k] = i

    idx = {label: colkey_to_index.get(colkey) for label, colkey in COLKEY_PER_LABEL.items()}

    def to_num(s):
        s = norm(s).replace(",", ".") if s else ""
        if not s or s == "-":
            return None
        try:
            f = float(s)
            return int(f) if f.is_integer() else round(f, 3)
        except ValueError:
            return None

    ROLE_TITLES = {"portiere": "P", "difensore": "D",
                   "centrocampista": "C", "attaccante": "A"}

    players = []
    for tr in table.find_all("tr"):
        if tr is header_row:
            continue
        a = tr.select_one("a[href*='/serie-a/squadre/']")
        if not a:
            continue
        m = re.search(r"/serie-a/squadre/([^/]+)/([^/]+)/(\d+)", a.get("href", ""))
        # Stesso metodo usato per l'intestazione (th+td, diretti, in ordine) —
        # prima usavo solo "td", ma le righe dati hanno <th> per i primi campi
        # (nome, ruoli) esattamente come l'intestazione, quindi serve lo stesso
        # criterio da entrambe le parti per restare allineati.
        cells = [norm(c.get_text()) for c in tr.find_all(["th", "td"], recursive=False)]

        # ruolo: 1) attributo data-value  2) classe role-x  3) title/aria-label
        role = None
        el = tr.select_one("[data-value]")
        if el and norm(el.get("data-value", "")).lower() in ("p", "d", "c", "a"):
            role = norm(el.get("data-value")).upper()
        if role is None:
            for el in tr.select("[class]"):
                for cls in el.get("class", []):
                    mm = re.fullmatch(r"role[-_]?([pdca])", cls.lower())
                    if mm:
                        role = mm.group(1).upper()
                        break
                if role:
                    break
        if role is None:
            for el in tr.select("[title], [aria-label]"):
                lab = (el.get("title") or el.get("aria-label") or "").strip().lower()
                if lab in ROLE_TITLES:
                    role = ROLE_TITLES[lab]
                    break

        def cell(key):
            i = idx.get(key)
            return cells[i] if i is not None and i < len(cells) else None

        rig_s = rig_c = None
        rig_raw = cell("rig")
        if rig_raw:
            mm = re.match(r"(\d+)\s*/\s*(\d+)", rig_raw)
            if mm:
                rig_s, rig_c = int(mm.group(1)), int(mm.group(2))

        players.append({
            "id": int(m.group(3)) if m else None,
            "nome": norm(a.get_text()),
            "squadra": m.group(1) if m else None,
            "ruolo": role,
            "pv": to_num(cell("pv")), "mv": to_num(cell("mv")), "fm": to_num(cell("fm")),
            "gol": to_num(cell("gol")), "golSubiti": to_num(cell("golSubiti")),
            "rigoriSegnati": rig_s, "rigoriCalciati": rig_c,
            "rigoriParati": to_num(cell("rigoriParati")), "assist": to_num(cell("assist")),
            "ammonizioni": to_num(cell("ammonizioni")), "espulsioni": to_num(cell("espulsioni")),
            "autogol": to_num(cell("autogol")),
        })

    if len(players) < 200:
        raise ValueError(f"Statistiche: trovati solo {len(players)} giocatori, struttura pagina cambiata?")

    # Controllo esplicito per il bug scoperto il 25/08: la tabella può caricarsi
    # con la struttura giusta ma i valori ancora a zero/vuoti. Fallito 3 volte
    # di fila con approcci diversi (Playwright, richiesta semplice, matching
    # per title) — invece di tentare una quarta ipotesi alla cieca, stampo
    # l'HTML vero della prima riga di intestazione e della prima riga dati,
    # così la prossima volta vediamo la realtà invece di indovinare ancora.
    con_mv = sum(1 for p in players if p["mv"] is not None)
    if con_mv < len(players) * 0.5:
        print("\n" + "="*70)
        print("DIAGNOSTICA — celle di intestazione (data-col-key → indice):")
        print("="*70)
        for i, th in enumerate(header_cells):
            print(i, repr(th.get("data-col-key")), repr(str(th)[:200]))
        print("Indici mappati:", idx)
        print("\n" + "="*70)
        print("DIAGNOSTICA — HTML vero della prima riga dati:")
        print("="*70)
        prima_riga = next((tr for tr in table.find_all("tr") if tr is not header_row), None)
        if prima_riga:
            print(str(prima_riga)[:3000])
        print("="*70)
        raise ValueError(
            f"Statistiche: solo {con_mv}/{len(players)} giocatori hanno un MV valido — "
            "la tabella sembra non essersi popolata del tutto (dati ancora a zero/vuoti)."
        )

    con_ruolo = sum(1 for p in players if p["ruolo"])
    save_json("players.json", {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fonte": "tabella HTML statistiche-serie-a",
        "giocatori": players,
    })
    print(f"    {len(players)} giocatori ({con_ruolo} con ruolo riconosciuto, {con_mv} con MV valido)")


# ── 2. CLASSIFICA ─────────────────────────────────────────────────
def job_classifica() -> None:
    html = fetch(CLASSIFICA_URL).text
    tables = pd.read_html(io.StringIO(html))
    # scegliamo la tabella che contiene sia 'Squadra' sia i punti
    table = None
    for t in tables:
        cols = [norm(c).lower() for c in t.columns.astype(str)]
        if any("squadra" in c for c in cols) and any(c in ("pt", "punti", "pti") for c in cols):
            table = t
            break
    if table is None:
        raise ValueError("Tabella classifica non trovata")

    table.columns = [norm(c).lower() for c in table.columns.astype(str)]
    # Possono esserci più colonne con "squadra" nel nome (pandas rinomina i
    # duplicati "squadra", "squadra.1", ...) — una spesso contiene solo il
    # numero di posizione, l'altra il nome vero. Scelgo quella il cui
    # contenuto è testo (non numeri), non semplicemente la prima trovata.
    # Bug reale scoperto il 28/08: la prima era quella coi numeri di
    # posizione, e i nomi finivano tutti vuoti.
    candidate_sq = [c for c in table.columns if "squadra" in c]
    col_sq = None
    for c in candidate_sq:
        valori = table[c].astype(str).head(5)
        if not all(v.strip().isdigit() for v in valori):
            col_sq = c
            break
    if col_sq is None:
        col_sq = candidate_sq[0] if candidate_sq else None
    if col_sq is None:
        raise ValueError("Nessuna colonna 'squadra' trovata nella tabella")
    col_pt = next(c for c in table.columns if c in ("pt", "punti", "pti"))

    standings = []
    for _, r in table.iterrows():
        squadra = norm(r[col_sq])
        # la cella spesso ripete il nome (logo+testo): teniamo l'ultimo token utile
        squadra = re.sub(r"^(\d+\s*)", "", squadra)
        try:
            punti = int(r[col_pt])
        except (ValueError, TypeError):
            continue
        standings.append({"squadra": squadra, "punti": punti})

    if len(standings) < 18:
        raise ValueError(f"Classifica incompleta: {len(standings)} squadre")

    # Controllo esplicito (bug scoperto il 28/08: nomi tutti vuoti, punti tutti
    # uguali a 3 — pandas aveva selezionato colonne sbagliate/non quelle vere).
    # Se il pattern è sospetto, meglio un errore con diagnostica reale che
    # salvare dati silenziosamente rotti come è successo quella volta.
    nomi_vuoti = sum(1 for s in standings if not s["squadra"])
    punti_distinti = len(set(s["punti"] for s in standings))
    if nomi_vuoti > 2 or punti_distinti <= 1:
        print("\n" + "="*70)
        print(f"DIAGNOSTICA — nomi vuoti: {nomi_vuoti}/{len(standings)}, valori punti distinti: {punti_distinti}")
        print("="*70)
        print("Tabelle trovate nella pagina (indice, colonne, prime 2 righe):")
        for i, t in enumerate(tables):
            print(f"\n--- Tabella {i} ---")
            print("Colonne:", list(t.columns.astype(str)))
            print(t.head(2).to_string())
        print("\n" + "="*70)
        print(f"Tabella scelta: colonna squadra='{col_sq}', colonna punti='{col_pt}'")
        print("Prime 3 righe della tabella scelta (grezze, prima della pulizia):")
        print(table.head(3).to_string())
        print("="*70)
        raise ValueError(
            f"Classifica sospetta: {nomi_vuoti}/{len(standings)} nomi vuoti, "
            f"{punti_distinti} valori di punti distinti — probabile tabella o colonne sbagliate."
        )

    save_json("classifica.json", {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "classifica": standings,
    })
    print(f"    {len(standings)} squadre")


# ── 3. CALENDARIO — SUPERATO da probabili_formazioni_scraper.py ───
# Quella fonte dà anche data/ora/stadio reali (qui mancavano), in un
# solo fetch condiviso con titolarità e indisponibili. Vedi quello script.


# ── 4. RIGORISTI ──────────────────────────────────────────────────
def job_rigoristi() -> None:
    html = fetch(RIGORISTI_URL).text
    # i nomi giocatore compaiono come link /serie-a/squadre/<team>/<player>/<id>
    matches = re.findall(r"/serie-a/squadre/([^/]+)/([^/]+)/\d+", html)
    per_team = {}
    for team, player in matches:
        per_team.setdefault(team, [])
        if player not in per_team[team] and len(per_team[team]) < 3:
            per_team[team].append(player)  # primi ~3 = gerarchia rigoristi

    if len(per_team) < 15:
        raise ValueError("Rigoristi: meno di 15 squadre trovate (normale a campionato fermo)")
    save_json("rigoristi.json", {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rigoristi": per_team,
    })
    print(f"    {len(per_team)} squadre")


# ── 5. INDISPONIBILI — SUPERATO da probabili_formazioni_scraper.py ─
# Quella fonte distingue squalificati/diffidati/infortunati/in dubbio
# (qui erano tutti mescolati in un'unica lista) e include il dettaglio
# dell'infortunio con rientro atteso. Vedi quello script.


# ── MAIN ──────────────────────────────────────────────────────────
JOBS = [
    ("Statistiche giocatori", job_statistiche),
    ("Classifica", job_classifica),
    ("Rigoristi", job_rigoristi),
]
# Calendario/Indisponibili/Titolarità: vedi probabili_formazioni_scraper.py,
# lanciato come step separato nel workflow (stessa fonte, un solo fetch).


def main() -> int:
    esiti = {}
    for nome, fn in JOBS:
        print(f"\n▶ {nome}")
        try:
            fn()
            esiti[nome] = "ok"
        except Exception as e:  # noqa: BLE001 — vogliamo continuare con le altre fonti
            esiti[nome] = f"ERRORE: {e}"
            print(f"  ✘ {e}", file=sys.stderr)

    save_json("meta.json", {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(),
        "esiti": esiti,
    })
    # exit code 0 anche con errori parziali: i JSON validi vanno comunque committati
    print("\nRiepilogo:", json.dumps(esiti, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
