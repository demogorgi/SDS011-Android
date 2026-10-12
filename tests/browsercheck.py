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

Der stationaere Modus wird nur angewaehlt, nie gestartet: er wuerde
auch mit simuliertem Sensor oeffentlich zu sensor.community hochladen.

Der Server schreibt in ein eigenes temporaeres Verzeichnis
(SDS011_OUTDIR), nicht ins echte output/: dort laegen sonst CSV-Dateien
und das umgestellte Messintervall in einstellungen.json, das Vorrang vor
RECORD_INT hat.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from urllib.request import urlopen

from playwright.async_api import async_playwright

PORT = os.environ.get('SDS011_PORT', '8091')
BASE = 'http://127.0.0.1:' + PORT
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONN_TEXT = "document.querySelector('#connStatus').textContent"
# Verbunden heisst die Pille "verbunden" -- oder "simuliert", denn dieser
# Lauf nutzt SDS011_FAKE, und das gilt als simulierter Sensor.
CONNECTED = ("document.querySelector('#connStatus').getAttribute('data-state') === 'on'")

# Beschriftung des Diagramms; im leeren Diagramm steht dort die Meldung.
CHART_LABEL = ("(function () { var s = document.querySelector('#chart svg');"
               " return s ? s.getAttribute('aria-label') || '' : ''; })()")

# Zustand eines Knopfs: gesperrt, sichtbar und wie er aussieht.
BUTTON_STATE = """e => ({
    tag: e.tagName.toLowerCase(),
    disabled: e.disabled,
    visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
    opacity: parseFloat(getComputedStyle(e).opacity),
    cursor: getComputedStyle(e).cursor
})"""

VISIBLE = """e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)"""

PRESSED = """els => els.filter(e => e.getAttribute('aria-pressed') === 'true')
                   .map(e => e.getAttribute('data-seconds') || e.getAttribute('data-range'))"""


def server_get(path, attempts=5):
    """Ein GET auf den eigenen Server, mit Wiederholung.

    Steht der Server gerade unter Last, kann ein einzelner Aufruf ins
    Timeout laufen. Dann lieber noch einmal versuchen, statt den ganzen
    Durchlauf abzubrechen und die eigentliche Aussage des Tests hinter
    einem TimeoutError zu verstecken.
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
    mitzureissen. Ohne das versteckt ein einzelner Timeout die Aussage
    aller uebrigen Pruefungen."""

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


async def button(page, selector):
    return await page.eval_on_selector(selector, BUTTON_STATE)


async def visible(page, selector):
    return await page.eval_on_selector(selector, VISIBLE)


async def text(page, selector):
    return (await page.text_content(selector) or '').strip()


async def chart_label_containing(page, needle, seconds=6):
    """Wartet, bis die Beschriftung des Diagramms needle enthaelt. Kommt
    es nicht, kein Abbruch: der Test vergleicht die Beschriftung und
    meldet so, was stattdessen dasteht."""
    try:
        await page.wait_for_function(
            "%s.indexOf('%s') >= 0" % (CHART_LABEL, needle), timeout=int(seconds * 1000))
    except Exception:
        pass


async def count_status_requests(page, seconds):
    hits = []

    def on_request(req):
        if '/status/' in req.url:
            hits.append(req.url)

    page.on('request', on_request)
    await page.wait_for_timeout(500)
    del hits[:]
    await page.wait_for_timeout(int(seconds * 1000))
    page.remove_listener('request', on_request)
    return len(hits)


async def collect():
    result = {}
    page_errors = []
    requests = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome')
        # Handybreite: die Oberflaeche ist mobil zuerst gebaut.
        page = await browser.new_page(viewport={'width': 400, 'height': 860})
        await page.emulate_media(color_scheme='dark')
        page.on('pageerror', lambda e: page_errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url.replace(BASE, '')))

        await page.goto(BASE + '/', wait_until='domcontentloaded')
        await page.wait_for_timeout(2500)
        result['page_errors'] = page_errors

        with Phase(result, 'layout'):
            measure = """() => ({
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
                bg: getComputedStyle(document.body).backgroundColor,
                pm25: getComputedStyle(document.documentElement)
                        .getPropertyValue('--pmc-pm25').trim()
            })"""
            layout = {'dark': await page.evaluate(measure)}
            await page.emulate_media(color_scheme='light')
            layout['light'] = await page.evaluate(measure)
            await page.emulate_media(color_scheme='dark')
            await page.set_viewport_size({'width': 320, 'height': 700})
            await page.wait_for_timeout(300)
            layout['narrow'] = await page.evaluate(measure)
            await page.set_viewport_size({'width': 400, 'height': 860})
            await page.wait_for_timeout(300)
            result['layout'] = layout

        with Phase(result, 'polling'):
            result['status_hits_in_6s'] = await count_status_requests(page, 6)

        with Phase(result, 'connection'):
            conn = result['connection'] = {}
            conn['initial'] = {
                'text': await text(page, '#connStatus'),
                'state': await page.get_attribute('#connStatus', 'data-state'),
                'devices': await page.eval_on_selector_all(
                    '#deviceSelect option', 'els => els.map(e => e.value)'),
                'connectBtn': await button(page, '#connectBtn'),
                'disconnectBtn': await button(page, '#disconnectBtn'),
                # Ohne Sensor darf nicht aufgezeichnet werden koennen.
                'startBtn': await button(page, '#startBtn'),
                'start_hint': await text(page, '#startHint'),
                'start_hint_visible': await visible(page, '#startHint'),
                'pm25': await text(page, '#pm25Value'),
                'live_age': await text(page, '#liveAge'),
            }

        with Phase(result, 'banner'):
            # Ein Start ohne Sensor wird abgelehnt und als Fehler gemeldet.
            server_get('/start/')
            await page.wait_for_selector('#errorBanner', state='visible', timeout=8000)
            result['banner'] = {'text': await text(page, '#errorBanner')}

        with Phase(result, 'connection'):
            conn = result['connection']
            # Langes Intervall: nach dem Verbinden kommt so bald kein
            # Punkt, das leere Diagramm muss allein wegen der Verbindung
            # neu laden.
            server_get('/interval/?seconds=900')
            await chart_label_containing(page, 'Kein Sensor verbunden')
            conn['chart_before'] = await page.evaluate(CHART_LABEL)
            await page.click('#connectBtn')
            await page.wait_for_selector('#toast.is-shown', timeout=3000)
            conn['toast'] = await text(page, '#toast')
            # Auf die Zustandsaenderung warten statt eine Dauer zu raten.
            await page.wait_for_function(CONNECTED, timeout=15000)
            conn['pill_connected'] = await page.evaluate(CONN_TEXT)
            conn['sim_badge_visible'] = await page.evaluate(
                "!document.getElementById('simBadge').hidden")
            # Laengstens eine Abfrage spaeter; ohne die Verbindung im
            # Schluessel kaeme das neue Bild erst nach einer Minute.
            await chart_label_containing(page, 'Erster Mittelwert')
            conn['chart_after_connect'] = await page.evaluate(CHART_LABEL)
            await page.wait_for_timeout(500)
            snap = server_status()
            conn['after_connect'] = {
                'text': await text(page, '#connStatus'),
                'state': await page.get_attribute('#connStatus', 'data-state'),
                'server_connection': snap['connection'],
                'server_wanted': snap['connection_wanted'],
                'connectBtn': await button(page, '#connectBtn'),
                'disconnectBtn': await button(page, '#disconnectBtn'),
                'startBtn': await button(page, '#startBtn'),
                'start_hint_visible': await visible(page, '#startHint'),
            }

            # Live-Werte: Zahl mit Dezimalkomma, Einstufung, "live"
            await page.wait_for_function(
                "document.querySelector('#liveAge').textContent.indexOf('live') === 0",
                timeout=10000)
            conn['live'] = {
                'pm25': await text(page, '#pm25Value'),
                'pm10': await text(page, '#pm10Value'),
                'level25': await page.get_attribute('#pm25Level', 'data-level'),
                'level25_text': await text(page, '#pm25Level'),
                'live_age': await text(page, '#liveAge'),
                'gps': await text(page, '#gpsStatus'),
            }

            await page.click('#disconnectBtn')
            await page.wait_for_function(CONN_TEXT + ".indexOf('getrennt') >= 0",
                                         timeout=15000)
            await chart_label_containing(page, 'Kein Sensor verbunden')
            conn['chart_after_disconnect'] = await page.evaluate(CHART_LABEL)
            snap = server_status()
            conn['after_disconnect'] = {
                'text': await text(page, '#connStatus'),
                'state': await page.get_attribute('#connStatus', 'data-state'),
                'server_connection': snap['connection'],
                'server_wanted': snap['connection_wanted'],
                'connectBtn': await button(page, '#connectBtn'),
            }

            # Fuer den Rest der Pruefungen wieder verbinden.
            await page.click('#connectBtn')
            await page.wait_for_function(CONNECTED, timeout=15000)

        with Phase(result, 'interval'):
            original = server_status()['interval']
            target = 10 if original != 10 else 30
            selector = '#intervalSelect [data-seconds="%d"]' % target
            await page.click(selector)
            await page.wait_for_function(
                "document.querySelector('%s').getAttribute('aria-pressed') === 'true'"
                % selector.replace("'", "\\'"), timeout=8000)
            result['interval'] = {
                'original': original,
                'target': target,
                'server': server_status()['interval'],
                'buttons': await page.eval_on_selector_all(
                    '#intervalSelect button', 'els => els.map(e => e.getAttribute("data-seconds"))'),
                'pressed': await page.eval_on_selector_all('#intervalSelect button', PRESSED),
                'caption': await text(page, '#chartCaption'),
            }
            # Gespeichert wird im eigenen Verzeichnis des Testservers.
            outdir = server_status()['outdir']
            result['outdir'] = {
                'server': outdir,
                'settings_written': os.path.isfile(os.path.join(outdir, 'einstellungen.json')),
            }
            # Fuer die folgenden Pruefungen kurz takten: ein Punkt alle 5 s.
            server_get('/interval/?seconds=5')

        with Phase(result, 'chart'):
            await page.wait_for_selector('#chart svg', timeout=10000)
            try:
                # Waehrend der Verbindungspruefung lief das 15-min-Intervall,
                # eine Linie braucht erst zwei Punkte im 5-s-Takt.
                await page.wait_for_selector('#chart svg .pmc-s25', timeout=15000)
            except Exception:
                pass                     # test_chart_uses_page_colors meldet es
            result['chart'] = await page.evaluate("""() => {
                const box = document.querySelector('#chart');
                const svg = box.querySelector('svg');
                const line = svg.querySelector('.pmc-s25');
                return {
                    cls: svg.getAttribute('class') || '',
                    width: parseFloat(svg.getAttribute('width')),
                    box: box.clientWidth,
                    stroke25: line ? getComputedStyle(line).stroke : null,
                    expected25: getComputedStyle(document.documentElement)
                                  .getPropertyValue('--pmc-pm25').trim()
                };
            }""")
            # Neu geladen wird nur bei neuem Verlauf, nicht bei jeder Abfrage.
            chart_hits = []
            status_hits = []

            def on_request(req):
                if '/chart.svg' in req.url:
                    chart_hits.append(req.url)
                elif '/status/' in req.url:
                    status_hits.append(req.url)

            page.on('request', on_request)
            await page.wait_for_timeout(8000)
            page.remove_listener('request', on_request)
            result['chart']['chart_hits_in_8s'] = len(chart_hits)
            result['chart']['status_hits_in_8s'] = len(status_hits)
            result['chart']['requested_widths'] = sorted({
                u.split('w=')[1].split('&')[0] for u in chart_hits if 'w=' in u})

        with Phase(result, 'range'):
            del requests[:]
            await page.click('#rangeSelect [data-range="600"]')
            await page.wait_for_timeout(1500)
            result['range'] = {
                'pressed': await page.eval_on_selector_all('#rangeSelect button', PRESSED),
                'requested': any(r.startswith('/chart.svg') and 'range=600' in r
                                 for r in requests),
                'stored': await page.evaluate("localStorage.getItem('feinstaub.range')"),
            }

        with Phase(result, 'stat_card'):
            # Nur anwaehlen, nicht starten (oeffentlicher Upload!).
            await page.click('#modeStat')
            result['stat_card'] = {
                'checked': await page.eval_on_selector('#modeStat input', 'e => e.checked'),
                'warn_visible': await visible(page, '#statWarn'),
                'warn_text': await text(page, '#statWarn'),
                'place_visible': await visible(page, '#placeField'),
                'start_text': await text(page, '#startBtn'),
            }

        with Phase(result, 'local'):
            await page.click('#modeLocal')
            local = result['local'] = {
                'place_visible': await visible(page, '#placeField'),
                'warn_visible': await visible(page, '#statWarn'),
                'start_text': await text(page, '#startBtn'),
            }
            await page.fill('#placeInput', 'Kletterhalle Duisburg')
            await page.click('#startBtn')
            await page.wait_for_function(
                "!document.querySelector('#sessionPanel').hasAttribute('hidden')",
                timeout=8000)
            await page.wait_for_timeout(500)
            snap = server_status()
            local['after_start'] = {
                'local': snap['local'],
                'stationary': snap['stationary'],
                'recording': snap['recording'],
                'place': snap['place'],
                'startBtn': await button(page, '#startBtn'),
                'stopBtn': await button(page, '#stopBtn'),
                'setup_visible': await visible(page, '#setupPanel'),
                'session_visible': await visible(page, '#sessionPanel'),
                'session_mode': await text(page, '#sessionMode'),
                'head_visible': await visible(page, '#headMode'),
                'banner_visible': await visible(page, '#errorBanner'),
            }
            # Laufzeit zaehlt clientseitig hoch, Punkte kommen vom Server.
            # Erst warten, bis der Recorder die Sitzung angelegt hat.
            await page.wait_for_function(
                "document.querySelector('#sessionElapsed').textContent !== '00:00:00'",
                timeout=8000)
            first = await text(page, '#sessionElapsed')
            await page.wait_for_timeout(2500)
            local['elapsed'] = [first, await text(page, '#sessionElapsed')]
            await page.wait_for_function(
                "['0', '–'].indexOf(document.querySelector('#sessionPoints').textContent) < 0",
                timeout=20000)
            local['points'] = await text(page, '#sessionPoints')
            local['file'] = await text(page, '#sessionFile')
            local['avg25'] = await text(page, '#sessionAvg25')

            await page.click('#stopBtn')
            await page.wait_for_function(
                "document.querySelector('#sessionPanel').hasAttribute('hidden')",
                timeout=8000)
            try:
                # Die Zusammenfassung kommt, sobald der Recorder die
                # Sitzung beendet hat (naechster Durchlauf + Abfrage).
                await page.wait_for_selector('#lastSession', state='visible', timeout=8000)
            except Exception:
                pass                     # der Test meldet es
            local['after_stop'] = {
                'local': server_status()['local'],
                'last_visible': await visible(page, '#lastSession'),
                'last_text': await text(page, '#lastSession'),
                'startBtn': await button(page, '#startBtn'),
            }

        with Phase(result, 'buttons'):
            await page.click('#modeTrip')
            result['before'] = {
                'server_recording': server_status()['recording'],
                'startBtn': await button(page, '#startBtn'),
                'stopBtn': await button(page, '#stopBtn'),
            }

            del requests[:]
            await page.click('#startBtn')
            await page.wait_for_timeout(1500)
            result['after_start'] = {
                'server_recording': server_status()['recording'],
                'start_calls': len([r for r in requests if r.startswith('/start/')]),
                'startBtn': await button(page, '#startBtn'),
                'stopBtn': await button(page, '#stopBtn'),
            }

            # Zweiter Klick -- der gesperrte Knopf muss ihn schlucken.
            # Per Skript, weil Playwright auf gesperrte Knoepfe wartet.
            del requests[:]
            await page.eval_on_selector('#startBtn', 'e => e.click()')
            await page.wait_for_timeout(1000)
            result['second_click_calls'] = len([r for r in requests
                                                if r.startswith('/start/')])

            await page.click('#stopBtn')
            await page.wait_for_timeout(1500)
            result['after_stop'] = {'server_recording': server_status()['recording']}

        with Phase(result, 'reload'):
            # Reload bei laufender Aufzeichnung
            server_get('/start/')
            await page.reload(wait_until='domcontentloaded')
            await page.wait_for_timeout(2500)
            result['after_reload'] = {
                'server_recording': server_status()['recording'],
                'startBtn': await button(page, '#startBtn'),
                'stopBtn': await button(page, '#stopBtn'),
                'session_visible': await visible(page, '#sessionPanel'),
                'trip_checked': await page.eval_on_selector('#modeTrip input',
                                                            'e => e.checked'),
                'range_pressed': await page.eval_on_selector_all('#rangeSelect button',
                                                                 PRESSED),
            }
            server_get('/stopp/')

        with Phase(result, 'polling_after'):
            # Nach all den Befehlen darf die Abfrage nicht gestapelt laufen.
            result['status_hits_after_in_6s'] = await count_status_requests(page, 6)

        with Phase(result, 'offline'):
            server_get('/__exit')
            await page.wait_for_function(
                "document.querySelector('#errorBanner').textContent"
                ".indexOf('Keine Verbindung zur Messanwendung') >= 0",
                timeout=15000)
            result['offline'] = {
                'banner_visible': await visible(page, '#errorBanner'),
                'banner_class': await page.get_attribute('#errorBanner', 'class'),
            }

        await browser.close()
    return result


def main():
    # Eigenes Ausgabeverzeichnis, siehe oben; wird hinterher geloescht.
    outdir = tempfile.mkdtemp(prefix='sds011-browser-')
    env = dict(os.environ, SDS011_FAKE='1', SDS011_PORT=PORT, SDS011_OUTDIR=outdir)
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, 'main.py'], cwd=REPO, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        if proc is not None:
            try:
                urlopen(BASE + '/__exit', timeout=5).read()
            except Exception:
                pass
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        # Erst nach dem Ende des Servers: unter Windows laesst sich das
        # offene Log sonst nicht loeschen.
        shutil.rmtree(outdir, ignore_errors=True)


if __name__ == '__main__':
    main()
