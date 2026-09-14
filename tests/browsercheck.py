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

CONN_TEXT = "document.querySelector('#echoconnection').textContent"

BUTTON_STATE = """e => ({
    off: e.classList.contains('off'),
    aria: e.getAttribute('aria-disabled'),
    opacity: parseFloat(getComputedStyle(e).opacity),
    cursor: getComputedStyle(e).cursor
})"""


def server_get(path, attempts=5):
    """Ein GET auf den eigenen Server, mit Wiederholung.

    Der Webserver ist einfaedrig. Steht er gerade unter Last -- etwa
    weil die Seite gerade haeufig abfragt -- kann ein einzelner Aufruf
    ins Timeout laufen. Dann lieber noch einmal versuchen, statt den
    ganzen Durchlauf abzubrechen und die eigentliche Aussage des Tests
    hinter einem TimeoutError zu verstecken.
    """
    last = None
    for _ in range(attempts):
        try:
            return urlopen(BASE + path, timeout=10).read()
        except Exception as exc:
            last = exc
            time.sleep(0.5)
    raise RuntimeError('%s nicht erreichbar: %s' % (path, last))


def server_status():
    return json.loads(server_get('/status/').decode('utf-8'))


class Phase(object):
    """Eine Pruefgruppe, die scheitern darf, ohne die anderen
    mitzureissen.

    Ohne das versteckt ein einzelner Timeout die Aussage aller uebrigen
    Pruefungen -- und genau das passiert, wenn die Seite den einfaedrigen
    Server mit Anfragen flutet.
    """

    def __init__(self, result, name):
        self.result = result
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.result[self.name + '_error'] = '%s: %s' % (exc_type.__name__, exc)
            return True      # Fehler schlucken, naechste Phase laeuft
        return False


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

        # Zuerst, weil ein Fehler hier den Server ausbremst und danach
        # jede andere Pruefung ins Timeout liefe.
        with Phase(result, 'refresh'):
            status_hits = []
            page.on('request',
                    lambda r: status_hits.append(r.url) if '/status/' in r.url else None)
            # Entscheidend: zwischen den Umstellungen muss die Kette
            # mindestens einmal gefeuert und sich selbst neu armiert
            # haben -- nur dann kann startPeriodicRefresh() sie nicht
            # mehr abbrechen. Deshalb jeweils laenger warten als das
            # eingestellte Intervall.
            for value, pause in (('2', 2400), ('1', 1400), ('2', 2400)):
                await page.select_option('#refreshRate', value)
                await page.wait_for_timeout(pause)
            await page.select_option('#refreshRate', '1')
            await page.wait_for_timeout(1400)
            del status_hits[:]
            await page.wait_for_timeout(4000)
            result['refresh_hits_in_4s'] = len(status_hits)

        with Phase(result, 'connection'):
            # -- Verbindung ------------------------------------------------
            result['connection'] = {}
            result['connection']['initial'] = {
                'text': await page.text_content('#echoconnection'),
                'cls': await page.get_attribute('#echoconnection', 'class'),
                'devices': await page.eval_on_selector_all(
                    '#deviceSelect option', 'els => els.map(e => e.value)'),
                'connectBtn': await page.eval_on_selector('#connectBtn', BUTTON_STATE),
                'disconnectBtn': await page.eval_on_selector('#disconnectBtn', BUTTON_STATE),
                # Ohne Sensor darf nicht aufgezeichnet werden koennen.
                'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
                'startStatBtn': await page.eval_on_selector('#startStatBtn', BUTTON_STATE),
            }

            # Auf die Zustandsaenderung warten statt eine Dauer zu raten.
            await page.click('#connectBtn')
            await page.wait_for_function(CONN_TEXT + ".indexOf('verbunden') >= 0",
                                         timeout=15000)
            result['connection']['after_connect'] = {
                'text': await page.text_content('#echoconnection'),
                'cls': await page.get_attribute('#echoconnection', 'class'),
                'server_connection': server_status()['connection'],
                'server_wanted': server_status()['connection_wanted'],
                'connectBtn': await page.eval_on_selector('#connectBtn', BUTTON_STATE),
                'disconnectBtn': await page.eval_on_selector('#disconnectBtn', BUTTON_STATE),
                'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
                'startStatBtn': await page.eval_on_selector('#startStatBtn', BUTTON_STATE),
            }

            await page.click('#disconnectBtn')
            await page.wait_for_function(CONN_TEXT + ".indexOf('getrennt') >= 0",
                                         timeout=15000)
            result['connection']['after_disconnect'] = {
                'text': await page.text_content('#echoconnection'),
                'cls': await page.get_attribute('#echoconnection', 'class'),
                'server_connection': server_status()['connection'],
                'server_wanted': server_status()['connection_wanted'],
            }

            # Fuer den Rest der Pruefungen wieder verbinden.
            await page.click('#connectBtn')
            await page.wait_for_function(CONN_TEXT + ".indexOf('verbunden') >= 0",
                                         timeout=15000)

        with Phase(result, 'local'):
            warn = await page.query_selector('.warn')
            result['local'] = {
                'warn_text': (await warn.text_content()) if warn else '',
                'warn_visible': (await warn.is_visible()) if warn else False,
            }
            await page.fill('#placeInput', 'Kletterhalle Duisburg')
            await page.click('#startLocalBtn')
            await page.wait_for_timeout(1500)
            snap = server_status()
            result['local']['after_start'] = {
                'local': snap['local'],
                'stationary': snap['stationary'],
                'recording': snap['recording'],
                'place': snap['place'],
                'startBtn': await page.eval_on_selector('#startBtn', BUTTON_STATE),
                'startStatBtn': await page.eval_on_selector('#startStatBtn', BUTTON_STATE),
                'stoppLocalBtn': await page.eval_on_selector('#stoppLocalBtn', BUTTON_STATE),
            }
            await page.click('#stoppLocalBtn')
            await page.wait_for_timeout(1500)
            result['local']['after_stop'] = {'local': server_status()['local']}

        with Phase(result, 'buttons'):
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

        with Phase(result, 'chart'):
            # Chart
            before_points = await page.evaluate("myChart.data.datasets[0].data.length")
            await page.wait_for_timeout(3000)
            result['chart'] = {
                'before': before_points,
                'after': await page.evaluate("myChart.data.datasets[0].data.length"),
                'max_points': await page.evaluate("MAX_POINTS"),
            }

        with Phase(result, 'reload'):
            # Reload bei laufender Aufzeichnung
            server_get('/start/')
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
