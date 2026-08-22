# Fantalitico

PWA per l'ottimizzazione della formazione fantacalcio (regolamento Classic),
con pipeline dati automatizzata da più fonti incrociate.

**Live:** `https://<utente>.github.io/<repo>/`

---

## Cosa fa l'app

- **Rosa** — la tua rosa con rating (Indice di Schierabilità), titolarità e
  scomposizione del calcolo per ogni giocatore. Flag automatici: squalificato,
  infortunato, rigorista, fuori Serie A. Bottone "Aggiorna con dati live" per
  riallineare i giocatori già in rosa quando i dati si aggiornano
- **Giornata** — partite della prossima giornata di Serie A con Δ calendario
  per squadra
- **Formazione** — modulo ottimo e undici titolare, basati **solo** su
  performance e titolarità: un consiglio universale, indipendente dalle
  regole della tua lega. Simulazione Monte Carlo (3000 giornate) con banda
  di incertezza P10/mediana/P90. Sotto-scheda **Dettagli Lineup** con tutti
  i giocatori (titolari e panchina) e i calcoli completi
- **Sfida** — confronto testa a testa Monte Carlo contro l'avversario di
  giornata, con selezione automatica dal **Calendario Lega** (round-robin
  generato o importato)
- **Top 11** — classifica di lega sulla migliore formazione *realmente*
  giocata a giornata conclusa (voti reali, non previsioni), con Bonus
  Capitano/Vice e Modificatore di Difesa applicati secondo le **Regole Lega**
- **Regole Lega** — Bonus Capitano (raddoppio / fisso / a fasce, con vice
  automatico) e Modificatore di Difesa (meccanismo reale fantacalcio.it:
  media voto puro di portiere + 3 migliori difensori, richiede 4+ difensori
  schierati), entrambi opzionali e configurabili — si applicano solo al
  Top 11, non alla Formazione
- **Mercato** — spunti di acquisto/cessione basati su chi rende meglio
  rispetto a chi hai già in rosa
- **Appunti per l'asta** — budget, obiettivi, quota personale, e **Max %**
  suggerita dal prezzo medio *realmente pagato* in migliaia d'aste vere
  (Fantacalcio-Online), riscalata sul tuo budget — con ripiego su una stima
  FVM/ripartizione-budget-per-ruolo se un giocatore non è ancora coperto dal
  dato reale. Sotto-schermata **Più comprati**: classifica di popolarità
  reale, filtrabile per ruolo, con ricerca e aggiunta rapida
- **Listone** — import quotazioni ufficiali (Excel), usato anche come fonte
  complementare di matching quando un giocatore manca dal database
  statistiche. Riconosce i giocatori usciti dalla Serie A (foglio "Ceduti"
  o asterisco nel nome) e li segnala con un flag dedicato
- **Calendario Lega** — round-robin generato o importato, usato dalla Sfida
- **Chi ce l'ha** — cerca un giocatore in tutte le tue leghe importate

## L'Indice di Schierabilità (motore)

```
Schierabilità = (Fantamedia shrunk + Forza squadra + Δ calendario
                 + Performance Understat + bonus rigorista) × Indice di Titolarità
```

**Fantamedia shrunk**: shrinkage bayesiano verso il prior di ruolo (e verso
lo storico personale del giocatore, se disponibile), con K specifico per
ruolo — evita di sopravvalutare un giocatore con poche presenze fortunate.

**Indice di Titolarità (IT)**:
```
IT = 0,12 · TS + 0,88 · consensus_fonti_reali   (quando le fonti reali sono disponibili)
IT = TS                                          (altrimenti)
IT = 0,02                                        (squalificato/infortunato confermato — priorità assoluta)
```
- **TS**: transizione graduale da rateo presenze stagione precedente
  (`storico_presenze.json`) a rateo presenze stagione corrente, man mano
  che le giornate reali si accumulano. Fallback neutro (0,7) se non c'è
  storico per un giocatore.
- **Fonti reali**: consensus pesato tra fantacalcio.it (peso 1.0) e
  SOS Fanta (peso 0.8), calcolato da `titolarita_consensus.py`.

## Fonti dati

| Dato | Fonte | Script |
|---|---|---|
| Statistiche stagionali, classifica, rigoristi | fantacalcio.it | `scraper.py` |
| Titolarità + calendario | fantacalcio.it (via Playwright, contenuto caricato via JS) | `probabili_formazioni_scraper.py` |
| Titolarità (seconda fonte) | SOS Fanta | `sosfanta_titolarita_scraper.py` |
| Indisponibili (squalificati/infortunati) | SOS Fanta | `sosfanta_indisponibili_scraper.py` |
| Prezzi reali d'asta | Fantacalcio-Online | `fantacalcio_online_scraper.py` |
| Voti giornata reale | 3 redazioni, consensus | `voti_giornata_scraper_v2.py` + `integra_voti_storico.py` |
| Statistiche avanzate (Understat) | Understat | `understat_pull.py` + `understat_process.py` (disabilitato fuori stagione) |

`titolarita_consensus.py` combina le fonti titolarità in `data/titolarita_reale.json`.
`player_name_matcher.py` fa il matching nome→id per le fonti senza ID
compatibili con fantacalcio.it (SOS Fanta, Fantacalcio-Online).

## Struttura

```
fantalitico/
├── index.html                        # la PWA
├── manifest.json                     # nome/icona per "Aggiungi a Home"
├── sw.js                             # service worker (cache offline)
├── icon-512.png                      # icona app
├── scraper.py                        # statistiche stagionali (pv/mv/fm/gol/...)
├── understat_pull.py                 # scarica CSV Understat (disabilitato fuori stagione)
├── understat_process.py              # CSV → understat.json
├── voti_giornata_scraper_v2.py       # voti reali di una giornata (3 redazioni)
├── integra_voti_storico.py           # consensus voti → voti_storico.json
├── probabili_formazioni_scraper.py   # titolarità + calendario (fantacalcio.it, Playwright)
├── sosfanta_titolarita_scraper.py    # titolarità (SOS Fanta, seconda fonte)
├── sosfanta_indisponibili_scraper.py # squalificati/infortunati (SOS Fanta)
├── fantacalcio_online_scraper.py     # prezzi reali d'asta (Fantacalcio-Online)
├── titolarita_consensus.py           # combina le fonti → titolarita_reale.json
├── player_name_matcher.py            # matching nome→id riusabile da qualsiasi fonte
├── requirements.txt
├── data/                             # output JSON, letti dalla PWA
│   ├── players.json                  # statistiche stagione corrente
│   ├── classifica.json
│   ├── calendario.json
│   ├── rigoristi.json
│   ├── indisponibili.json
│   ├── meta.json
│   ├── voti_storico.json             # voti reali per giornata (accumulo progressivo)
│   ├── titolarita_reale.json         # consensus titolarità (più fonti)
│   ├── storico_presenze.json         # presenze stagione precedente (statico, per TS)
│   ├── prezzi_reali_asta.json        # prezzi medi reali (Fantacalcio-Online)
│   └── fonti_titolarita/             # output grezzo per-fonte (input di titolarita_consensus.py)
└── .github/workflows/update-data.yml # automazione (2×/giorno, 6:00 e 18:00 UTC)
```

## Messa in funzione (una tantum, ~15 minuti)

1. Crea un repository su GitHub (es. `fantalitico`), anche privato*.
2. Carica questi file rispettando la struttura (la cartella `.github/workflows` è essenziale).
3. Tab **Actions** → abilita i workflow → seleziona "Aggiorna dati Fantalitico" → **Run workflow** per la prima esecuzione manuale.
4. Controlla che in `/data` compaiano i JSON e leggi `meta.json` per gli esiti.
5. **Settings → Pages** → Source: branch `main` → la PWA e i JSON saranno serviti da `https://<utente>.github.io/<repo>/`.
6. **Settings → Actions → General → Workflow permissions** → verifica che sia impostato "Read and write permissions" (necessario perché il workflow scrive i JSON aggiornati — su organizzazioni nuove a volte è disattivato di default).

*Con repo privato, GitHub Pages richiede un piano a pagamento: per l'hosting gratuito della PWA usa un repo pubblico.

## Esecuzione dei singoli script

```bash
pip install -r requirements.txt
python -m playwright install chromium --with-deps   # serve a probabili_formazioni_scraper.py

# Statistiche stagionali (automatico, 2×/giorno)
python scraper.py

# Titolarità + calendario + indisponibili SOS Fanta + prezzi asta (automatico, 2×/giorno)
python probabili_formazioni_scraper.py
python sosfanta_indisponibili_scraper.py
python sosfanta_titolarita_scraper.py
python fantacalcio_online_scraper.py
python titolarita_consensus.py

# Voti di una giornata conclusa (manuale, via workflow_dispatch con numero giornata)
python voti_giornata_scraper_v2.py 1
python integra_voti_storico.py data/voti_giornata_1.json 1
```

## Dati statici da caricare una tantum

- **`storico_presenze.json`** — costruito dall'ultimo export statistiche
  prima del reset stagionale, filtrato solo sui giocatori ancora in Serie A.
  Non cambia più durante la stagione, va caricato in `data/` una volta sola.
- **Listone quotazioni** — si importa dall'app stessa (Altro → Listone),
  non dalla pipeline GitHub. Da reimportare quando fantacalcio.it pubblica
  un listone aggiornato (es. dopo il calciomercato).

## Manutenzione prevista

- **Inizio stagione**: aggiornare `SEASON_ID` in `scraper.py` (vedi commento nel file).
- **Riattivare Understat** quando inizia il campionato: togliere i commenti
  ai relativi step in `update-data.yml` (disattivato fuori stagione, senza
  partite giocate non c'è nulla da elaborare).
- **Calendario di lega**: si genera/importa dall'app (Altro → Calendario
  Lega), resta valido tutta la stagione salvo correzioni manuali.
- Se una fonte HTML cambia struttura, il relativo job fallisce ma gli altri
  proseguono; l'ultimo JSON valido resta in uso dalla PWA. Gli errori sono
  registrati in `data/meta.json` e nel log del workflow.
- **Modificatore di Difesa / fasce Capitano**: i valori di default nel
  codice sono preset comuni — vanno corretti in Regole Lega con i valori
  reali della propria lega quando configurata.

## Segnalazioni

Dentro l'app: **Altro → Segnala un problema** — apre un'email precompilata
con contesto automatico (data dati, schermata, browser).

## Limiti noti

- La categoria "in dubbio" delle probabili formazioni non è disponibile
  per singola partita da SOS Fanta (limite della struttura della pagina
  sorgente, verificato) — solo squalificati/diffidati/infortunati.
- Il matching nome→id (`player_name_matcher.py`) serve alle fonti senza ID
  compatibili con fantacalcio.it (SOS Fanta, Fantacalcio-Online); va esteso
  con un parser dedicato per fonte quando se ne aggiunge una nuova.
- I prezzi reali d'asta (`fantacalcio_online_scraper.py`) hanno copertura
  parziale: giocatori poco comprati/nuovi possono non avere ancora un
  prezzo medio registrato, in quel caso si usa il ripiego FVM.

## Licenza

GPL-3.0 — vedi `LICENSE`.
