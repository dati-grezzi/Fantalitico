# -*- coding: utf-8 -*-
"""
DETERMINA GIORNATA DA PROCESSARE — decide in automatico se c'è una giornata
di voti da scaricare, senza bisogno di lanciarlo a mano ogni settimana.

Logica: data/calendario.json riporta la giornata "in vetrina" sulla pagina
probabili formazioni (quella futura/in corso). Se quella giornata è la N,
significa che la N-1 è verosimilmente conclusa — è quella di cui controllare
i voti. Se i voti di quella giornata sono già stati integrati in
data/voti_storico.json, non c'è nulla da fare.

Uso da workflow GitHub Actions: stampa "giornata=N" (o "giornata=") su
GITHUB_OUTPUT, così lo step successivo può essere condizionato al risultato.
"""

import json
import os
import sys

# Una giornata di Serie A è completa quando tutte e 20 le squadre hanno voti.
SQUADRE_ATTESE = 20


def main():
    github_output = os.environ.get("GITHUB_OUTPUT")

    def emetti(giornata):
        riga = f"giornata={giornata if giornata is not None else ''}\n"
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(riga)
        print(riga.strip())

    # Override manuale: se lanciato a mano specificando una giornata, usa
    # quella direttamente (utile per un recupero), saltando il controllo
    # "già fatta" — un override esplicito è un'intenzione deliberata.
    override = os.environ.get("GIORNATA_MANUALE", "").strip()
    if override:
        print(f"Giornata forzata manualmente: {override}")
        emetti(override)
        return 0

    if not os.path.exists("data/calendario.json"):
        print("⚠️  data/calendario.json non trovato, impossibile determinare la giornata")
        emetti(None)
        return 0

    with open("data/calendario.json", encoding="utf-8") as f:
        cal = json.load(f)
    giornata_in_vetrina = cal.get("giornata")
    if not giornata_in_vetrina or giornata_in_vetrina < 2:
        print(f"Giornata in vetrina: {giornata_in_vetrina} — nessuna giornata precedente da processare ancora")
        emetti(None)
        return 0

    giornata_candidata = giornata_in_vetrina - 1

    # Controllo "già COMPLETA" — RIATTIVATO il 29/08 (era stato disattivato il
    # 25/08 per facilitare i lanci ripetuti durante il debug del bug dei voti
    # duplicati, ora chiuso e confermato su più giornate). Senza questo
    # controllo la pipeline avrebbe rilavorato la Giornata 1 all'infinito,
    # senza mai passare alla successiva — bug scoperto durante la verifica
    # completa pre-deploy del 29/08.
    #
    # Non basta però chiedersi se la giornata è "già toccata": lo scraper
    # salva anche un turno parziale (salta le partite senza voti e fallisce
    # solo se sono vuote tutte e dieci). Se la pagina delle probabili passa
    # alla giornata successiva mentre un posticipo o un recupero non ha
    # ancora i voti, un solo giocatore integrato basterebbe a dichiarare
    # chiusa la giornata, e le partite mancanti non entrerebbero mai più.
    # Quindi la soglia è la copertura: finché non ci sono tutte e 20 le
    # squadre, la giornata si riprocessa e assorbe da sé le partite arrivate
    # nel frattempo.
    squadre_presenti = set()
    if os.path.exists("data/voti_storico.json"):
        with open("data/voti_storico.json", encoding="utf-8") as f:
            storico = json.load(f)
        chiave = str(giornata_candidata)
        for dati_giocatore in storico.values():
            if not isinstance(dati_giocatore, dict):
                continue
            if chiave in dati_giocatore.get("giornate", {}):
                squadra = (dati_giocatore.get("squadra") or "").strip()
                if squadra:
                    squadre_presenti.add(squadra)

    if len(squadre_presenti) >= SQUADRE_ATTESE:
        print(f"Giornata {giornata_candidata} già integrata e completa "
              f"({len(squadre_presenti)}/{SQUADRE_ATTESE} squadre) — nulla da fare")
        emetti(None)
        return 0

    if squadre_presenti:
        print(f"Giornata {giornata_candidata} presente ma INCOMPLETA: "
              f"{len(squadre_presenti)}/{SQUADRE_ATTESE} squadre "
              f"({', '.join(sorted(squadre_presenti))}). La riprocesso per "
              f"recuperare le partite mancanti.")

    print(f"Giornata da processare: {giornata_candidata}")
    emetti(giornata_candidata)
    return 0


if __name__ == "__main__":
    sys.exit(main())
