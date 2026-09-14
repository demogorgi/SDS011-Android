# -*- coding: utf-8 -*-
"""Oberflaechentests mit einem echten Browser.

Wird uebersprungen, wenn Playwright oder ein Chrome fehlen -- wie beim
Python-2-Check. Die Browsersteuerung selbst liegt in
tests/browsercheck.py und laeuft als eigener Prozess: dessen
async-Syntax wuerde die Suite unter Python 2 beim Einsammeln zerlegen.

Diese Tests fangen genau das, was die statischen Pruefungen in
test_frontend.py nicht sehen koennen -- ob eine Zustandsaenderung im
Browser auch tatsaechlich sichtbar wird.
"""

from __future__ import absolute_import

import json
import os
import socket
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(REPO, 'tests', 'browsercheck.py')


def free_port():
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1', 0))
        return str(sock.getsockname()[1])
    finally:
        sock.close()


def playwright_available():
    """Prueft Playwright und einen startbaren Browser in einem eigenen
    Prozess -- ein fehlender Browser soll die Suite nicht mitreissen."""
    code = (
        'import asyncio, sys\n'
        'from playwright.async_api import async_playwright\n'
        'async def go():\n'
        '    async with async_playwright() as p:\n'
        '        b = await p.chromium.launch(channel="chrome")\n'
        '        await b.close()\n'
        'asyncio.run(go())\n'
    )
    try:
        proc = subprocess.Popen([sys.executable, '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate()
        return proc.returncode == 0
    except (OSError, IOError):
        return False


_RESULT = {}


def browser_result():
    """Laeuft einmal pro Testlauf, nicht pro Testmethode."""
    if 'value' in _RESULT:
        return _RESULT['value']
    env = dict(os.environ, SDS011_PORT=free_port())
    proc = subprocess.Popen([sys.executable, HELPER], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise AssertionError('browsercheck.py fehlgeschlagen:\n%s'
                             % err.decode('utf-8', 'replace')[-2000:])
    _RESULT['value'] = json.loads(out.decode('utf-8'))
    return _RESULT['value']


class BrowserTest(unittest.TestCase):

    def _phase(self, name):
        """Liefert das Ergebnis einer Pruefgruppe oder laesst den Test mit
        der Ursache scheitern. browsercheck.py kapselt jede Gruppe, damit
        ein Timeout nicht die Aussage aller uebrigen verdeckt."""
        error = self.result.get(name + '_error')
        if error:
            self.fail('Pruefgruppe %r fehlgeschlagen: %s' % (name, error))
        return self.result


    @classmethod
    def setUpClass(cls):
        if sys.version_info[0] < 3:
            raise unittest.SkipTest('Playwright braucht Python 3')
        try:
            import playwright            # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright nicht installiert')
        if not playwright_available():
            raise unittest.SkipTest('kein startbarer Chrome fuer Playwright')
        cls.result = browser_result()

    # -- JavaScript ---------------------------------------------------
    def test_no_javascript_errors(self):
        """Frueher warf setInterval alle 3 Sekunden einen ReferenceError."""
        self.assertEqual(self.result['page_errors'], [])

    # -- Sichtbarer Zustand der Buttons -------------------------------
    def test_disabled_button_is_visibly_different(self):
        """Der eigentliche Punkt: prop('disabled') an einem <div> aendert
        die Darstellung nicht -- der Zustand war unsichtbar."""
        result = self._phase('buttons')
        active = result['before']['startBtn']
        blocked = result['after_start']['startBtn']

        self.assertFalse(active['off'])
        self.assertTrue(blocked['off'])
        self.assertLess(blocked['opacity'], active['opacity'],
                        'gesperrter Button sieht aus wie ein aktiver')
        self.assertEqual(blocked['cursor'], 'default')
        self.assertEqual(active['cursor'], 'pointer')

    def test_aria_disabled_is_set(self):
        result = self._phase('buttons')
        self.assertEqual(result['before']['startBtn']['aria'], 'false')
        self.assertEqual(result['after_start']['startBtn']['aria'], 'true')

    def test_start_and_stopp_are_mutually_exclusive(self):
        result = self._phase('buttons')
        before = result['before']
        after = result['after_start']
        self.assertTrue(before['stoppBtn']['off'])
        self.assertFalse(before['startBtn']['off'])
        self.assertFalse(after['stoppBtn']['off'])
        self.assertTrue(after['startBtn']['off'])

    # -- Verhalten ----------------------------------------------------
    def test_click_reaches_the_server(self):
        result = self._phase('buttons')
        self.assertFalse(result['before']['server_recording'])
        self.assertTrue(result['after_start']['server_recording'])
        self.assertEqual(result['after_start']['start_calls'], 1)
        self.assertFalse(result['after_stop']['server_recording'])

    def test_second_click_is_swallowed(self):
        self.assertEqual(self._phase('buttons')['second_click_calls'], 0,
                         'gesperrter Button loest trotzdem aus')

    def test_state_survives_reload(self):
        """Frueher wurde der Buttonzustand nur im Klick-Handler gesetzt
        und stimmte nach einem Reload nicht mehr."""
        after = self._phase('reload')['after_reload']
        self.assertTrue(after['server_recording'])
        self.assertTrue(after['startBtn']['off'])

    # -- Sensorverbindung ---------------------------------------------
    def test_device_list_is_offered(self):
        """Die MAC-Adresse soll nicht mehr im Quelltext stehen muessen."""
        devices = self._phase('connection')['connection']['initial']['devices']
        self.assertTrue(devices, 'keine Geraete zur Auswahl')
        self.assertTrue(all(d for d in devices))

    def test_connection_state_is_visible(self):
        """Der Kern der Aenderung: 'Sensor fehlt' und 'Sensor misst 0'
        waren vorher nicht unterscheidbar."""
        result = self._phase('connection')
        initial = result['connection']['initial']
        connected = result['connection']['after_connect']

        self.assertIn(u'getrennt', initial['text'])
        self.assertIn('aus', initial['cls'])

        self.assertIn(u'verbunden', connected['text'])
        self.assertIn('an', connected['cls'])
        self.assertNotEqual(initial['cls'], connected['cls'])

    def test_connect_button_toggles(self):
        result = self._phase('connection')
        initial = result['connection']['initial']
        connected = result['connection']['after_connect']
        self.assertFalse(initial['connectBtn']['off'])
        self.assertTrue(initial['disconnectBtn']['off'])
        self.assertTrue(connected['connectBtn']['off'])
        self.assertFalse(connected['disconnectBtn']['off'])

    def test_connect_reaches_the_server(self):
        connected = self._phase('connection')['connection']['after_connect']
        self.assertTrue(connected['server_wanted'])
        self.assertEqual(connected['server_connection'], u'verbunden')

    def test_disconnect_reaches_the_server(self):
        after = self._phase('connection')['connection']['after_disconnect']
        self.assertFalse(after['server_wanted'])
        self.assertEqual(after['server_connection'], u'getrennt')
        self.assertIn(u'getrennt', after['text'])

    def test_recording_is_blocked_without_sensor(self):
        """Ohne verbundenen Sensor entstuenden Dateien voller Nullen --
        die sehen aus wie eine echte Messung."""
        result = self._phase('connection')
        before = result['connection']['initial']
        after = result['connection']['after_connect']

        self.assertTrue(before['startBtn']['off'],
                        'Start ist ohne Sensor anklickbar')
        self.assertTrue(before['startStatBtn']['off'],
                        'Stationaerer Modus ist ohne Sensor anklickbar')
        self.assertLess(before['startBtn']['opacity'],
                        after['startBtn']['opacity'],
                        'gesperrter Start sieht aus wie ein freigegebener')

        self.assertFalse(after['startBtn']['off'],
                         'Start bleibt nach dem Verbinden gesperrt')
        self.assertFalse(after['startStatBtn']['off'])

    # -- Lokale Messung -----------------------------------------------
    def test_upload_warning_is_shown(self):
        """Der stationaere Modus ist der einzige, der Daten aus der Hand
        gibt -- das muss man sehen, bevor man drauftippt."""
        local = self._phase('local')['local']
        self.assertTrue(local['warn_visible'], 'Warnhinweis nicht sichtbar')
        text = local['warn_text']
        self.assertIn(u'luftdaten', text.lower())
        self.assertIn(u'raspi-', text, 'Sensor-ID fehlt im Hinweis')

    def test_local_mode_records_without_upload(self):
        """Die Kletterhallen-Messung darf den Upload nicht anschalten."""
        after = self._phase('local')['local']['after_start']
        self.assertTrue(after['local'])
        self.assertFalse(after['stationary'], 'lokale Messung hat Upload aktiviert')
        self.assertFalse(after['recording'])
        self.assertEqual(after['place'], 'Kletterhalle Duisburg')

    def test_active_mode_blocks_the_others(self):
        after = self._phase('local')['local']['after_start']
        self.assertTrue(after['startBtn']['off'],
                        'Messfahrt startbar, obwohl lokale Messung laeuft')
        self.assertTrue(after['startStatBtn']['off'],
                        'Upload startbar, obwohl lokale Messung laeuft')
        self.assertFalse(after['stoppLocalBtn']['off'])

    def test_local_mode_can_be_stopped(self):
        self.assertFalse(self._phase('local')['local']['after_stop']['local'])

    # -- Aktualisierung -----------------------------------------------
    def test_refresh_rate_change_does_not_stack_timers(self):
        """periodicRefresh() merkte sein Timer-Handle nicht, also konnte
        startPeriodicRefresh() die laufende Kette nicht abbrechen. Jede
        Aenderung der Rate startete eine zusaetzliche Kette: nach fuenf
        Umstellungen lief die Abfrage fuenffach -- dauerhaft, auf einem
        Geraet mit Akku."""
        hits = self._phase('refresh')['refresh_hits_in_4s']
        # Bei 1 Sekunde erwarten wir etwa 4 Anfragen in 4 Sekunden.
        self.assertLessEqual(hits, 8,
                             'Timer-Ketten stapeln sich: %d Anfragen in 4s' % hits)
        self.assertGreaterEqual(hits, 2,
                                'Aktualisierung laeuft gar nicht: %d Anfragen' % hits)

    # -- Chart --------------------------------------------------------
    def test_chart_receives_data(self):
        chart = self._phase('chart')['chart']
        self.assertGreater(chart['after'], chart['before'])
        self.assertLessEqual(chart['after'], chart['max_points'])


if __name__ == '__main__':
    unittest.main()
