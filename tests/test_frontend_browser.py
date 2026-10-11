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
import re
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


def hex_to_rgb(value):
    """'#19a3c4' -> 'rgb(25, 163, 196)', wie getComputedStyle es liefert."""
    value = value.strip().lstrip('#')
    return 'rgb(%d, %d, %d)' % tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


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

    # -- Seite --------------------------------------------------------
    def test_no_javascript_errors(self):
        self.assertEqual(self.result['page_errors'], [])

    def test_mobile_layout_does_not_scroll_sideways(self):
        """Mobil zuerst: bei 400 und 320 px Breite kein seitliches
        Scrollen."""
        layout = self._phase('layout')['layout']
        for name in ('dark', 'narrow'):
            self.assertLessEqual(layout[name]['scrollWidth'], layout[name]['innerWidth'],
                                 'seitliches Scrollen bei %s' % name)

    def test_theme_follows_system(self):
        """Dunkel als Standard, hell ueber prefers-color-scheme; die
        Diagrammfarben wechseln mit."""
        layout = self._phase('layout')['layout']
        self.assertNotEqual(layout['dark']['bg'], layout['light']['bg'])
        self.assertTrue(layout['dark']['pm25'])
        self.assertTrue(layout['light']['pm25'])
        self.assertNotEqual(layout['dark']['pm25'], layout['light']['pm25'])

    # -- Statusabfrage ------------------------------------------------
    def test_status_polled_every_two_seconds(self):
        """Fest alle 2 s; die alte Auswahl "Aktualisierung" ist weg."""
        hits = self._phase('polling')['status_hits_in_6s']
        self.assertGreaterEqual(hits, 2, 'Abfrage laeuft gar nicht: %d' % hits)
        self.assertLessEqual(hits, 5, 'zu viele Abfragen: %d in 6 s' % hits)

    def test_commands_do_not_stack_polling(self):
        """Frueher startete jede Umstellung eine weitere Timer-Kette --
        dauerhaft, auf einem Geraet mit Akku. Nach allen Befehlen muss
        es bei einer Kette bleiben."""
        hits = self._phase('polling_after')['status_hits_after_in_6s']
        self.assertGreaterEqual(hits, 2)
        self.assertLessEqual(hits, 5, 'Timer-Ketten stapeln sich: %d in 6 s' % hits)

    # -- Sensorverbindung ---------------------------------------------
    def test_device_list_is_offered(self):
        """Die MAC-Adresse soll nicht im Quelltext stehen muessen."""
        devices = self._phase('connection')['connection']['initial']['devices']
        self.assertTrue(devices, 'keine Geraete zur Auswahl')
        self.assertTrue(all(d for d in devices))

    def test_connection_state_is_visible(self):
        """'Sensor fehlt' und 'Sensor misst 0' muessen unterscheidbar
        sein."""
        conn = self._phase('connection')['connection']
        self.assertIn(u'getrennt', conn['initial']['text'])
        self.assertEqual(conn['initial']['state'], 'off')
        self.assertIn(u'verbunden', conn['after_connect']['text'])
        self.assertEqual(conn['after_connect']['state'], 'on')
        self.assertIn(u'getrennt', conn['after_disconnect']['text'])
        self.assertEqual(conn['after_disconnect']['state'], 'off')

    def test_no_values_without_sensor(self):
        """Ohne Sensor ein Strich statt 0,0 -- 0 saehe aus wie saubere
        Luft."""
        initial = self._phase('connection')['connection']['initial']
        self.assertEqual(initial['pm25'], u'–')
        self.assertIn(u'kein Sensor', initial['live_age'])

    def test_connect_and_disconnect_buttons(self):
        """Getrennt: Verbinden sichtbar und frei, Trennen nicht da.
        Verbunden: umgekehrt."""
        conn = self._phase('connection')['connection']
        initial, connected = conn['initial'], conn['after_connect']
        self.assertEqual(initial['connectBtn']['tag'], 'button')
        self.assertTrue(initial['connectBtn']['visible'])
        self.assertFalse(initial['connectBtn']['disabled'])
        self.assertFalse(initial['disconnectBtn']['visible'])
        self.assertTrue(initial['disconnectBtn']['disabled'])

        self.assertFalse(connected['connectBtn']['visible'])
        self.assertTrue(connected['connectBtn']['disabled'])
        self.assertTrue(connected['disconnectBtn']['visible'])
        self.assertFalse(connected['disconnectBtn']['disabled'])

        self.assertTrue(conn['after_disconnect']['connectBtn']['visible'])

    def test_connect_reaches_the_server(self):
        connected = self._phase('connection')['connection']['after_connect']
        self.assertTrue(connected['server_wanted'])
        self.assertEqual(connected['server_connection'], u'verbunden')

    def test_disconnect_reaches_the_server(self):
        after = self._phase('connection')['connection']['after_disconnect']
        self.assertFalse(after['server_wanted'])
        self.assertEqual(after['server_connection'], u'getrennt')

    def test_command_answer_as_toast(self):
        toast = self._phase('connection')['connection']['toast']
        self.assertIn(u'Verbindung', toast)

    def test_live_values(self):
        """Zahl mit Dezimalkomma, Einstufung als Text, "live · vor N s"."""
        live = self._phase('connection')['connection']['live']
        self.assertRegex(live['pm25'], r'^\d+,\d$')
        self.assertRegex(live['pm10'], r'^\d+,\d$')
        self.assertIn(live['level25'], ('good', 'elevated', 'high'))
        self.assertIn(live['level25_text'], (u'gut', u'erhöht', u'hoch'))
        self.assertTrue(live['live_age'].startswith(u'live'))
        self.assertTrue(live['gps'].startswith(u'GPS'))

    # -- Gesperrte Knoepfe --------------------------------------------
    def test_recording_is_blocked_without_sensor(self):
        """Ohne verbundenen Sensor entstuenden Dateien voller Nullen --
        die sehen aus wie eine echte Messung. Der Grund steht dabei."""
        conn = self._phase('connection')['connection']
        before, after = conn['initial'], conn['after_connect']
        self.assertTrue(before['startBtn']['disabled'], 'Start ohne Sensor anklickbar')
        self.assertTrue(before['start_hint_visible'])
        self.assertIn(u'Sensor verbinden', before['start_hint'])
        self.assertFalse(after['startBtn']['disabled'], 'Start bleibt nach Verbinden gesperrt')
        self.assertFalse(after['start_hint_visible'])

    def test_disabled_button_is_visibly_different(self):
        conn = self._phase('connection')['connection']
        blocked, free = conn['initial']['startBtn'], conn['after_connect']['startBtn']
        self.assertLess(blocked['opacity'], free['opacity'],
                        'gesperrter Knopf sieht aus wie ein freier')
        self.assertEqual(blocked['cursor'], 'not-allowed')
        self.assertEqual(free['cursor'], 'pointer')

    # -- Meldungen ----------------------------------------------------
    def test_error_banner_shows_server_error(self):
        """Ein abgelehnter Start ohne Sensor erscheint als Banner ..."""
        text = self._phase('banner')['banner']['text']
        self.assertIn(u'kein Sensor verbunden', text)

    def test_error_banner_clears_on_start(self):
        """... und verschwindet, sobald ein Modus startet."""
        after = self._phase('local')['local']['after_start']
        self.assertFalse(after['banner_visible'])

    def test_offline_banner(self):
        """Antwortet der Server nicht mehr, sagt die Seite das, statt
        kommentarlos beim letzten Wert stehen zu bleiben."""
        offline = self._phase('offline')['offline']
        self.assertTrue(offline['banner_visible'])
        self.assertIn('is-offline', offline['banner_class'])

    # -- Messintervall ------------------------------------------------
    def test_interval_change_reaches_server(self):
        interval = self._phase('interval')['interval']
        self.assertEqual(interval['buttons'], ['5', '10', '30', '60', '300', '900'])
        self.assertEqual(interval['server'], interval['target'])
        self.assertEqual(interval['pressed'], [str(interval['target'])])
        self.assertIn(u'Mittelwerte je %d s' % interval['target'], interval['caption'])

    def test_server_writes_to_its_own_outdir(self):
        """Der Testserver schreibt nicht ins echte output/: dort laege
        sonst das umgestellte Messintervall in einstellungen.json und
        haette Vorrang vor RECORD_INT. Hinterher ist alles geloescht."""
        info = self._phase('interval')['outdir']
        outdir = info['server']
        self.assertNotEqual(os.path.normcase(os.path.abspath(outdir)),
                            os.path.normcase(os.path.join(REPO, 'output')))
        self.assertTrue(info['settings_written'],
                        'Messintervall nicht im eigenen Verzeichnis gespeichert')
        self.assertFalse(os.path.exists(outdir), 'nicht aufgeraeumt: %s' % outdir)

    # -- Diagramm -----------------------------------------------------
    def test_chart_svg_appears(self):
        """Das SVG vom Server steht inline im Dokument, pixelgenau so breit
        wie sein Platz."""
        chart = self._phase('chart')['chart']
        self.assertIn('pm-chart', chart['cls'])
        self.assertAlmostEqual(chart['width'], max(240, chart['box']), delta=1)

    def test_empty_chart_follows_connection(self):
        """Nach dem Verbinden steht im leeren Diagramm nicht weiter "Kein
        Sensor verbunden", sondern die Uhrzeit des ersten Mittelwerts --
        eine Uhrzeit veraltet nicht wie ein "in 870 s". Nach dem Trennen
        wieder umgekehrt. Bei 15 min Intervall kommt kein Punkt dazwischen,
        neu laden muss die Verbindung allein."""
        conn = self._phase('connection')['connection']
        self.assertIn(u'Kein Sensor verbunden', conn['chart_before'])
        after = conn['chart_after_connect']
        self.assertNotIn(u'Kein Sensor verbunden', after)
        self.assertRegex(after, r'Erster Mittelwert um \d\d:\d\d:\d\d')
        self.assertIn(u'Kein Sensor verbunden', conn['chart_after_disconnect'])

    def test_chart_uses_page_colors(self):
        """Die Linien lesen die --pmc-*-Farben der Seite (Theme)."""
        chart = self._phase('chart')['chart']
        if chart['stroke25'] is None:
            self.skipTest('noch keine PM2.5-Linie im Diagramm')
        self.assertEqual(chart['stroke25'], hex_to_rgb(chart['expected25']))

    def test_chart_not_reloaded_on_every_poll(self):
        """Neu geladen wird nur, wenn sich der Verlauf aendert -- bei 5 s
        Intervall also hoechstens jede zweite Abfrage."""
        chart = self._phase('chart')['chart']
        self.assertGreaterEqual(chart['chart_hits_in_8s'], 1)
        self.assertLess(chart['chart_hits_in_8s'], chart['status_hits_in_8s'])
        self.assertEqual(len(chart['requested_widths']), 1,
                         'Diagramm in wechselnden Breiten angefordert')

    def test_range_switch_loads_new_chart(self):
        rng = self._phase('range')['range']
        self.assertEqual(rng['pressed'], ['600'])
        self.assertTrue(rng['requested'], 'kein neues Diagramm fuer 10 min')
        self.assertEqual(rng['stored'], '600')

    def test_range_survives_reload(self):
        self.assertEqual(self._phase('reload')['after_reload']['range_pressed'], ['600'])

    # -- Moduskarten --------------------------------------------------
    def test_stationary_card_shows_warning(self):
        """Der stationaere Modus ist der einzige, der Daten aus der Hand
        gibt -- das muss man sehen, bevor man startet."""
        card = self._phase('stat_card')['stat_card']
        self.assertTrue(card['checked'])
        self.assertTrue(card['warn_visible'], 'Warnhinweis nicht sichtbar')
        self.assertIn(u'sensor.community', card['warn_text'])
        self.assertIn(u'raspi-', card['warn_text'], 'Sensor-ID fehlt im Hinweis')
        self.assertFalse(card['place_visible'])

    def test_local_card_shows_place_field(self):
        local = self._phase('local')['local']
        self.assertTrue(local['place_visible'])
        self.assertFalse(local['warn_visible'], 'Upload-Warnung bei lokaler Messung')
        self.assertIn(u'Lokale Messung', local['start_text'])

    def test_local_mode_records_without_upload(self):
        """Die Kletterhallen-Messung darf den Upload nicht anschalten."""
        after = self._phase('local')['local']['after_start']
        self.assertTrue(after['local'])
        self.assertFalse(after['stationary'], 'lokale Messung hat Upload aktiviert')
        self.assertFalse(after['recording'])
        self.assertEqual(after['place'], 'Kletterhalle Duisburg')

    def test_active_mode_blocks_the_others(self):
        """Die Modi schliessen sich aus: waehrend einer laeuft, gibt es
        keinen Start, nur Stoppen."""
        after = self._phase('local')['local']['after_start']
        self.assertTrue(after['startBtn']['disabled'])
        self.assertFalse(after['startBtn']['visible'])
        self.assertFalse(after['setup_visible'], 'Moduswahl waehrend der Messung')
        self.assertTrue(after['stopBtn']['visible'])
        self.assertFalse(after['stopBtn']['disabled'])

    def test_session_panel(self):
        """Laufende Messung: Modus, Laufzeit (zaehlt), Punkte, Datei."""
        local = self._phase('local')['local']
        after = local['after_start']
        self.assertTrue(after['session_visible'])
        self.assertTrue(after['head_visible'], 'Laufzeit fehlt in der Kopfzeile')
        self.assertIn(u'Lokale Messung', after['session_mode'])
        self.assertIn(u'Kletterhalle Duisburg', after['session_mode'])
        first, second = local['elapsed']
        self.assertRegex(second, r'^\d\d:\d\d:\d\d$')
        self.assertNotEqual(first, second, 'Laufzeit zaehlt nicht')
        self.assertGreater(int(local['points']), 0)
        self.assertTrue(local['file'].endswith('.csv'), local['file'])
        self.assertIn('kletterhalle', local['file'])
        self.assertTrue(re.match(r'^\d+,\d$', local['avg25']), local['avg25'])

    def test_local_mode_can_be_stopped(self):
        after = self._phase('local')['local']['after_stop']
        self.assertFalse(after['local'])
        self.assertTrue(after['last_visible'], 'keine Zusammenfassung nach Stop')
        self.assertIn(u'Lokale Messung', after['last_text'])
        self.assertFalse(after['startBtn']['disabled'])

    # -- Start/Stopp --------------------------------------------------
    def test_start_and_stop_are_mutually_exclusive(self):
        result = self._phase('buttons')
        before, after = result['before'], result['after_start']
        self.assertTrue(before['startBtn']['visible'])
        self.assertFalse(before['startBtn']['disabled'])
        self.assertFalse(before['stopBtn']['visible'])
        self.assertTrue(before['stopBtn']['disabled'])
        self.assertTrue(after['startBtn']['disabled'])
        self.assertTrue(after['stopBtn']['visible'])
        self.assertFalse(after['stopBtn']['disabled'])

    def test_click_reaches_the_server(self):
        result = self._phase('buttons')
        self.assertFalse(result['before']['server_recording'])
        self.assertTrue(result['after_start']['server_recording'])
        self.assertEqual(result['after_start']['start_calls'], 1)
        self.assertFalse(result['after_stop']['server_recording'])

    def test_second_click_is_swallowed(self):
        self.assertEqual(self._phase('buttons')['second_click_calls'], 0,
                         'gesperrter Knopf loest trotzdem aus')

    def test_state_survives_reload(self):
        """Der Knopfzustand kommt vom Server und stimmt auch nach einem
        Reload."""
        after = self._phase('reload')['after_reload']
        self.assertTrue(after['server_recording'])
        self.assertTrue(after['startBtn']['disabled'])
        self.assertTrue(after['stopBtn']['visible'])
        self.assertTrue(after['session_visible'])
        self.assertTrue(after['trip_checked'])


if __name__ == '__main__':
    unittest.main()
