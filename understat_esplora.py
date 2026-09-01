# -*- coding: utf-8 -*-
"""
FANTALITICO — sonda 2: attivare le colonne dei tiri su Understat.

COSA SAPPIAMO (sonda 1, 1/09/2026)
----------------------------------
- I tiri NON sono in un JSON incorporato né in una chiamata di rete.
- Esiste pero' un selettore di colonne: pannelli ".table-options" con una riga
  ".table-options-row" per colonna. Quello letto dalla prima sonda era della
  tabella SQUADRE (N, Team, M, W, D, L, G, GA, PTS, xG...).
- Dopo 4 secondi era renderizzata solo la tabella squadre: serve attendere di
  piu' perche' compaia quella dei giocatori.

COSA FA QUESTA
--------------
1. Aspetta la tabella giocatori (intestazione con xG90).
2. Elenca TUTTI i pannelli di opzioni con le rispettive righe.
3. Prova ad attivare Sh90 e KP90 e ristampa le intestazioni.
Se al punto 3 le colonne compaiono, la stessa sequenza va messa in
understat_pull.py e il problema e' chiuso.
"""

import asyncio
import sys

from playwright.async_api import async_playwright

URL = "https://understat.com/league/Serie_A/2026"
VOLUTE = ("sh90", "kp90")


async def intestazioni(page):
    return await page.evaluate("""
        () => {
            const t = Array.from(document.querySelectorAll('table'))
                .find(t => Array.from(t.querySelectorAll('th'))
                    .some(th => th.textContent.toLowerCase().includes('xg90')));
            return t ? Array.from(t.querySelectorAll('th'))
                .map(th => th.textContent.trim()).filter(Boolean) : [];
        }
    """)


async def main_async():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Apro {URL} ...")
        await page.goto(URL, wait_until="load", timeout=45000)

        # La tabella giocatori arriva dopo quella delle squadre.
        try:
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('th'))
                        .some(th => th.textContent.toLowerCase().includes('xg90'))""",
                timeout=25000)
            print("Tabella giocatori comparsa.")
        except Exception:
            print("ATTENZIONE: la tabella giocatori non e' comparsa entro 25s")
        await page.wait_for_timeout(2500)

        print("\n" + "=" * 64)
        print("A. INTESTAZIONI ATTUALI")
        print("=" * 64)
        print(" ", await intestazioni(page))

        print("\n" + "=" * 64)
        print("B. PANNELLI DI OPZIONI COLONNE")
        print("=" * 64)
        pannelli = await page.evaluate("""
            () => Array.from(document.querySelectorAll('.table-options')).map((p, i) => ({
                indice: i,
                classe: p.className,
                righe: Array.from(p.querySelectorAll('.table-options-row'))
                        .map(r => r.textContent.trim()).filter(Boolean),
                visibile: !!(p.offsetWidth || p.offsetHeight)
            }))
        """)
        for pa in pannelli:
            print(f"\n  pannello #{pa['indice']} (visibile: {pa['visibile']}) "
                  f"class=\"{pa['classe']}\"")
            print(f"  {len(pa['righe'])} righe: {pa['righe']}")
        if not pannelli:
            print("  Nessun pannello .table-options trovato.")

        print("\n" + "=" * 64)
        print("C. TENTATIVO DI ATTIVARE Sh90 e KP90")
        print("=" * 64)
        esito = await page.evaluate("""
            (volute) => {
                const log = [];
                const righe = Array.from(document.querySelectorAll('.table-options-row'));
                log.push('righe totali disponibili: ' + righe.length);
                for (const v of volute) {
                    const r = righe.find(x => x.textContent.trim().toLowerCase() === v);
                    if (!r) { log.push(v + ': RIGA NON TROVATA'); continue; }
                    const box = r.querySelector('input[type=checkbox]');
                    if (box) {
                        if (!box.checked) { box.click(); log.push(v + ': checkbox attivata'); }
                        else log.push(v + ': gia attiva');
                    } else {
                        r.click();
                        log.push(v + ': cliccata la riga (nessuna checkbox)');
                    }
                }
                return log;
            }
        """, list(VOLUTE))
        for r in esito:
            print(" ", r)

        await page.wait_for_timeout(3000)
        dopo = await intestazioni(page)
        print("\n  Intestazioni dopo il tentativo:")
        print(" ", dopo)
        ok = [v for v in VOLUTE if any(v == h.lower() for h in dopo)]
        print(f"\n  RISULTATO: {'attivate ' + ', '.join(ok) if ok else 'nessuna colonna aggiunta'}")

        print("\n" + "=" * 64)
        print("D. LINK A PAGINE GIOCATORE")
        print("=" * 64)
        link = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href*="/player/"]'))
                    .slice(0, 3).map(a => a.href)
        """)
        print(" ", link or "nessuno")

        await browser.close()
    print("\nFatto. Incolla tutto l'output.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception as e:
        print(f"Errore: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
