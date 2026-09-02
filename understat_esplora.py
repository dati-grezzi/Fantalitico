# -*- coding: utf-8 -*-
"""
FANTALITICO — sonda 3: leggere le etichette del selettore colonne di Understat.

COSA SAPPIAMO (sonde 1 e 2, 1/09/2026)
--------------------------------------
- I tiri non stanno in un JSON incorporato ne' in una chiamata di rete.
- Esistono due pannelli ".table-options": #0 e' della tabella squadre,
  #1 della tabella giocatori e ha 20 righe.
- Non ci sono link alle pagine dei singoli giocatori.
- Il confronto sul testo della riga fallisce perche' la riga "Player" contiene
  un filtro con TUTTI i nomi: il suo textContent e' lunghissimo e sporca
  qualunque confronto.

COSA FA QUESTA
--------------
Legge l'ETICHETTA di ogni riga (solo i nodi di testo diretti, non i figli),
la stampa, e prova ad attivare quelle dei tiri e dei passaggi chiave
riconoscendole in modo tollerante.
"""

import asyncio
import sys

from playwright.async_api import async_playwright

URL = "https://understat.com/league/Serie_A/2026"


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
        try:
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('th'))
                        .some(th => th.textContent.toLowerCase().includes('xg90'))""",
                timeout=25000)
        except Exception:
            print("ATTENZIONE: tabella giocatori non comparsa")
        await page.wait_for_timeout(2500)

        print("\n" + "=" * 64)
        print("A. ETICHETTE DELLE RIGHE DEL PANNELLO GIOCATORI (#1)")
        print("=" * 64)
        righe = await page.evaluate("""
            () => {
                const pannelli = document.querySelectorAll('.table-options');
                const p = pannelli[1] || pannelli[0];
                if (!p) return [];
                return Array.from(p.querySelectorAll('.table-options-row')).map((r, i) => {
                    // Solo i nodi di testo DIRETTI: cosi' la riga "Player",
                    // che contiene il filtro con tutti i nomi, non sporca nulla.
                    const diretti = Array.from(r.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim()).join(' ').trim();
                    const box = r.querySelector('input[type=checkbox]');
                    return {
                        i,
                        etichetta: diretti || r.textContent.trim().slice(0, 25),
                        classe: r.className,
                        checkbox: !!box,
                        attiva: box ? box.checked : null,
                        html: r.outerHTML.slice(0, 160)
                    };
                });
            }
        """)
        for r in righe:
            print(f"  #{r['i']:2d} {r['etichetta']!r:14s} checkbox={r['checkbox']} attiva={r['attiva']}")
        if righe:
            print(f"\n  esempio di markup: {righe[0]['html']!r}")

        print("\n" + "=" * 64)
        print("B. TENTATIVO DI ATTIVAZIONE")
        print("=" * 64)
        esito = await page.evaluate("""
            () => {
                const log = [];
                const pannelli = document.querySelectorAll('.table-options');
                const p = pannelli[1] || pannelli[0];
                if (!p) return ['nessun pannello'];
                const righe = Array.from(p.querySelectorAll('.table-options-row'));
                const cerca = ['sh90', 'sh', 'kp90', 'kp', 'shots', 'key passes'];
                for (const chiave of cerca) {
                    const r = righe.find(x => {
                        const d = Array.from(x.childNodes).filter(n => n.nodeType === 3)
                            .map(n => n.textContent.trim()).join(' ').trim().toLowerCase();
                        return d === chiave;
                    });
                    if (!r) { log.push(chiave + ': non trovata'); continue; }
                    const box = r.querySelector('input[type=checkbox]');
                    if (box && !box.checked) { box.click(); log.push(chiave + ': ATTIVATA'); }
                    else if (box) { log.push(chiave + ': gia attiva'); }
                    else { r.click(); log.push(chiave + ': riga cliccata'); }
                }
                return log;
            }
        """)
        for e in esito:
            print(" ", e)

        await page.wait_for_timeout(3000)
        dopo = await intestazioni(page)
        print("\n  Intestazioni dopo:", dopo)

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
