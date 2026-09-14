# -*- coding: utf-8 -*-
"""Treibt die Weboberflaeche mit einem echten Browser und gibt das
Ergebnis als JSON auf stdout aus.

Laeuft als eigener Prozess, nicht als importiertes Testmodul: die
async-Syntax hier wuerde die Testsuite unter Python 2 beim Einsammeln
zerlegen. Aufrufer ist tests/test_frontend_browser.py.

Die Sync-API von Playwright kann hier nicht benutzt werden -- sie
haengt an greenlet, das auf Python 3.14 abstuerzt. Deshalb async_api.
Playwrights eigenes Chromium ist nicht installiert, wir nehmen den
System-Chrome ueber channel='chrome'.
"""

import asyncio
import json
import os
import subprocess
import sys
import time

from urllib.request import urlopen

from playwright.async_api import async_playwright

PORT = os.environ.get('SDS011_PORT', '8091')
BASE = 'http://127.0.0.1:' + PORT
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUTTON_STATE = """e => ({
    off: e.classList.contains('off'),
    aria: e.getAttribute('aria-disabled'),
    opacity: parseFloat(getComputedStyle(e).opacity),
    cursor: getComputedStyle(e).cursor
})"""


def server_status():
    return json.loads(urlopen(BASE + '/status/', timeout=5).read().decode('utf-8'))


async def collect():
    result = {}
    page_errors = []
    requests = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome')
        page = await browser.new_page(viewport={'width': 430, 'height': 900})
        page.on('pageerror', lambda e: page_errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url.replace(BASE, '')))

        await page.goto(BASE + '/', wait_until='domcontentloaded')
        await page.select_option('#refreshRate', '1')
        await page.wait_for_timeout(2000)

        result['page_errors'] = page_errors
        result['failed_own_requests'] = []

        # Zustand vor dem Klick
        result['before'] = {
            'server_recording': server_status()['recording'],
            'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
            'stoppBtn': await page.eval_on_selector('#stoppBtn', BUTTON_STATE),
        }

        # Klick auf Start
        del requests[:]
        await page.click('#startBtn')
        await page.wait_for_timeout(1200)
        result['after_start'] = {
            'server_recording': server_status()['recording'],
            'start_calls': len([r for r in requests if r.startswith('/start/')]),
            'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
            'stoppBtn': await page.eval_on_selector('#stoppBtn', BUTTON_STATE),
        }

        # Zweiter Klick -- die Sperre muss ihn schlucken
        del requests[:]
        await page.click('#startBtn')
        await page.wait_for_timeout(1000)
        result['second_click_calls'] = len([r for r in requests if r.startswith('/start/')])

        # Stop
        await page.click('#stoppBtn')
        await page.wait_for_timeout(1200)
        result['after_stop'] = {'server_recording': server_status()['recording']}

        # Chart
        before_points = await page.evaluate("myChart.data.datasets[0].data.length")
        await page.wait_for_timeout(3000)
        result['chart'] = {
            'before': before_points,
            'after': await page.evaluate("myChart.data.datasets[0].data.length"),
            'max_points': await page.evaluate("MAX_POINTS"),
        }

        # Reload bei laufender Aufzeichnung
        urlopen(BASE + '/start/', timeout=5).read()
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(1500)
        result['after_reload'] = {
            'server_recording': server_status()['recording'],
            'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
        }

        await browser.close()
    return result


def main():
    env = dict(os.environ, SDS011_FAKE='1', SDS011_PORT=PORT)
    proc = subprocess.Popen([sys.executable, 'main.py'], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urlopen(BASE + '/status/', timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError('Server kam nicht hoch')

        result = asyncio.run(collect())
        sys.stdout.write(json.dumps(result))
    finally:
        try:
            urlopen(BASE + '/__exit', timeout=5).read()
        except Exception:
            pass
        time.sleep(1)
        if proc.poll() is None:
            proc.kill()
            proc.wait()


if __name__ == '__main__':
    main()
