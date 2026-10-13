# -*- coding: utf-8 -*-
"""Tests fuer die Bottle-Routen -- ohne echten Server, per WSGI-Aufruf."""

from __future__ import absolute_import

import json
import math
import os
import re
import sys
import time
import unittest
from io import BytesIO
from xml.etree import ElementTree

import config
import webapp
from state import AppState, monotonic


def call_raw(app, path, method='GET', **extra):
    """Ruft die WSGI-App direkt auf und liefert (status, Koepfe, body).

    Query-String gehoert nach QUERY_STRING, nicht in PATH_INFO -- sonst
    findet bottle die Route nicht. extra landet im environ (etwa
    HTTP_IF_MODIFIED_SINCE). Die Koepfe als dict mit kleinen Namen.
    """
    if '?' in path:
        path, query = path.split('?', 1)
    else:
        query = ''
    environ = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'QUERY_STRING': query,
        'SERVER_NAME': 'testhost',
        'SERVER_PORT': '8080',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.input': BytesIO(),
        'wsgi.errors': sys.stderr,
        'wsgi.url_scheme': 'http',
    }
    environ.update(extra)
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured['status'] = status
        captured['headers'] = {name.lower(): value for name, value in headers}

    result = app(environ, start_response)
    try:
        body = b''.join(result)
    finally:
        # Wie ein WSGI-Server: schliesst die Datei hinter /static/.
        if hasattr(result, 'close'):
            result.close()
    return captured['status'], captured['headers'], body


def call(app, path, method='GET'):
    """Wie call_raw, liefert aber (status, body-dict); ist der Body kein
    JSON, die Bytes."""
    status, _headers, body = call_raw(app, path, method)
    try:
        payload = json.loads(body.decode('utf-8'))
    except ValueError:
        payload = body
    return status, payload


class IndexFromOtherDirectoryTest(unittest.TestCase):
    """Altes QPython startet nicht im Projektordner -- die Seite muss
    trotzdem gefunden werden."""

    def setUp(self):
        import bottle
        import tempfile
        self._cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)
        bottle.TEMPLATES.clear()

    def tearDown(self):
        import shutil
        os.chdir(self._cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_index_renders(self):
        status, body = call(webapp.create_app(AppState()), '/')
        self.assertTrue(status.startswith('200'), status)
        self.assertIn(b'deviceSelect', body)


class RouteTest(unittest.TestCase):

    def setUp(self):
        self.state = AppState()
        self.app = webapp.create_app(self.state)
        # Aufzeichnen setzt einen verbundenen Sensor voraus.
        self.state.set_connection(u'verbunden')

    def test_start_and_stopp_toggle_recording(self):
        self.assertFalse(self.state.recording)
        status, payload = call(self.app, '/start/')
        self.assertTrue(status.startswith('200'))
        self.assertTrue(self.state.recording)
        self.assertIn('value', payload)

        call(self.app, '/stopp/')
        self.assertFalse(self.state.recording)

    def test_stationary_routes(self):
        call(self.app, '/staton/')
        self.assertTrue(self.state.stationary)
        # Stationaer und mobil schliessen sich aus.
        self.assertFalse(self.state.recording)

        call(self.app, '/statoff/')
        self.assertFalse(self.state.stationary)

    def test_start_refused_while_stationary(self):
        """Die Modi schliessen sich aus -- auch serverseitig, damit eine
        veraltete Seite nicht einfach umschaltet."""
        call(self.app, '/staton/')
        status, payload = call(self.app, '/start/')
        self.assertTrue(payload.get('refused'))
        self.assertIn(u'erst Stationärer Modus beenden', payload['value'])
        self.assertFalse(self.state.recording)
        self.assertTrue(self.state.stationary)

        call(self.app, '/statoff/')
        status, payload = call(self.app, '/start/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.recording)

    def test_every_other_mode_blocks_every_start(self):
        """Alle sechs Kombinationen: abgelehnt, Flags und Ort bleiben."""
        starts = {'recording': '/start/', 'local': '/localon/?place=Neu',
                  'stationary': '/staton/'}
        for active in starts:
            for flag, route in starts.items():
                if flag == active:
                    continue
                state = AppState()
                state.set_connection(u'verbunden')
                state.set_place(u'Alt')
                setattr(state, active, True)
                app = webapp.create_app(state)
                status, payload = call(app, route)
                self.assertTrue(payload.get('refused'), (active, route))
                self.assertEqual(
                    [k for k in starts if getattr(state, k)], [active], (active, route))
                self.assertEqual(state.place(), u'Alt', (active, route))
                # Nur in der Antwort -- kein bleibender roter Hinweis.
                self.assertEqual(state.error(), u'', (active, route))

    def test_starting_the_same_mode_again_is_fine(self):
        call(self.app, '/start/')
        status, payload = call(self.app, '/start/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.recording)

    def test_status_contract(self):
        """Die Schluessel muessen exakt die sein, die index.html liest."""
        self.state.set_measurement(12.3, 45.6)
        self.state.set_position(51.4385, 6.7882)
        status, payload = call(self.app, '/status/')
        self.assertTrue(status.startswith('200'))
        for key in ('value', 'lat', 'lon', 'pm_10', 'pm_10_color',
                    'pm_25', 'pm_25_color', 'error_msg',
                    'recording', 'stationary', 'connection',
                    'connection_error', 'connection_wanted',
                    'device', 'device_name', 'gps_available', 'gps_age',
                    'gps_max_age', 'local', 'place', 'trip_name',
                    # Fuer die Oberflaeche mit Server-Diagramm:
                    'interval', 'intervals', 'stationary_intervals',
                    'measurement_age',
                    'measurement_usable', 'pm_25_level', 'pm_10_level',
                    'history_rev', 'raw_history_rev',
                    'next_point_in', 'session', 'upload', 'outdir',
                    'stat_interval', 'stationary_position_ok',
                    'stationary_distance_m', 'stationary_max_distance_m'):
            self.assertIn(key, payload)
        self.assertEqual(payload['lat'], '51.43850')
        self.assertEqual(payload['pm_10'].strip(), '45.6')

    def test_status_error_field_stays_empty_without_error(self):
        """Frueher landete hier die letzte Logzeile statt eines Fehlers."""
        from logging_util import write_log
        write_log(0, 'Verbinde mit Feinstaubsensor...')
        status, payload = call(self.app, '/status/')
        self.assertEqual(payload['error_msg'], u'')

    def test_status_reflects_mode(self):
        status, payload = call(self.app, '/status/')
        self.assertFalse(payload['recording'])
        self.assertFalse(payload['stationary'])

        call(self.app, '/start/')
        status, payload = call(self.app, '/status/')
        self.assertTrue(payload['recording'])
        self.assertFalse(payload['stationary'])

        call(self.app, '/stopp/')
        call(self.app, '/staton/')
        status, payload = call(self.app, '/status/')
        self.assertFalse(payload['recording'])
        self.assertTrue(payload['stationary'])

    def test_status_shows_reported_error(self):
        self.state.report_error(u'Problem beim Verbinden mit Feinstaubsensor!')
        status, payload = call(self.app, '/status/')
        self.assertIn(u'Feinstaubsensor', payload['error_msg'])

    def test_status_survives_negative_values(self):
        self.state.set_measurement(-1.0, -1.0)
        status, payload = call(self.app, '/status/')
        self.assertTrue(status.startswith('200'))
        self.assertTrue(payload['pm_10_color'].startswith('#'))

    def test_exit_route_answers_immediately_and_stops(self):
        calls = []
        app = webapp.create_app(self.state, on_shutdown=lambda: calls.append(1))
        status, payload = call(app, '/__exit')
        self.assertTrue(status.startswith('200'))
        self.assertFalse(self.state.sensing)
        self.assertTrue(self.state.stop_event.is_set())

    def test_index_renders(self):
        status, body = call(self.app, '/')
        self.assertTrue(status.startswith('200'))
        self.assertIn(b'Feinstaub', body)


class SensorRequiredTest(unittest.TestCase):
    """Ohne verbundenen Sensor entstuenden Dateien voller Nullen -- und
    Nullen sehen aus wie eine echte Messung."""

    def setUp(self):
        self.state = AppState()
        self.app = webapp.create_app(self.state)

    def test_start_is_refused_without_sensor(self):
        status, payload = call(self.app, '/start/')
        self.assertTrue(status.startswith('200'))
        self.assertTrue(payload.get('refused'))
        self.assertFalse(self.state.recording)
        self.assertIn(u'kein Sensor verbunden', self.state.error())

    def test_stationary_is_refused_without_sensor(self):
        """Besonders wichtig: der stationaere Modus laedt zu
        api.luftdaten hoch. Nullen landeten in einem oeffentlichen
        Datensatz."""
        status, payload = call(self.app, '/staton/')
        self.assertTrue(payload.get('refused'))
        self.assertFalse(self.state.stationary)

    def test_stationary_is_refused_far_from_configured_position(self):
        self.state.set_connection(u'verbunden')
        self.state.set_position(52.5200, 13.4050)
        self.state.mark_gps_fix()
        status, payload = call(self.app, '/staton/')
        self.assertTrue(payload.get('refused'))
        self.assertFalse(self.state.stationary)
        self.assertGreater(payload['distance_m'], config.STATIONARY_MAX_DISTANCE_M)
        self.assertIn(u'GPS-Position', payload['value'])

    def test_stationary_is_allowed_near_configured_position(self):
        self.state.set_connection(u'verbunden')
        self.state.set_position(51.43994724975504, 6.781089452019765)
        self.state.mark_gps_fix()
        status, payload = call(self.app, '/staton/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.stationary)

    def test_stationary_is_allowed_without_gps(self):
        self.state.set_connection(u'verbunden')
        self.state.set_gps_available(False)
        status, payload = call(self.app, '/staton/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.stationary)

    def test_start_works_once_connected(self):
        self.state.set_connection(u'verbunden')
        status, payload = call(self.app, '/start/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.recording)
        self.assertEqual(self.state.error(), u'')

    def test_start_sets_trip_name(self):
        self.state.set_connection(u'verbunden')
        status, payload = call(self.app, '/start/?name=Von%20Essen%20nach%20Duisburg')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.recording)
        self.assertEqual(self.state.trip_name(), u'Von Essen nach Duisburg')

    def test_status_reports_trip_name_while_recording(self):
        self.state.set_connection(u'verbunden')
        call(self.app, '/start/?name=A40')
        status, payload = call(self.app, '/status/')
        self.assertEqual(payload['place'], u'A40')
        self.assertEqual(payload['trip_name'], u'A40')

    def test_start_without_name_clears_previous_place(self):
        self.state.set_connection(u'verbunden')
        self.state.set_trip_name(u'Alter Name')
        status, payload = call(self.app, '/start/')
        self.assertFalse(payload.get('refused'))
        self.assertEqual(self.state.trip_name(), u'')

    def test_stopp_works_even_without_sensor(self):
        """Stoppen muss immer gehen -- auch wenn die Verbindung
        unterwegs abgerissen ist."""
        self.state.set_connection(u'verbunden')
        call(self.app, '/start/')
        self.state.set_connection(u'getrennt')
        call(self.app, '/stopp/')
        self.assertFalse(self.state.recording)

    def test_dropout_during_recording_does_not_stop_it(self):
        """Ein kurzer Aussetzer soll die Fahrt nicht abbrechen -- der
        SensorReader verbindet selbst wieder."""
        self.state.set_connection(u'verbunden')
        call(self.app, '/start/')
        self.state.set_connection(u'wartet auf nächsten Versuch')
        self.assertTrue(self.state.recording)


class LocalModeRouteTest(unittest.TestCase):
    """Lokale Messung: an einem Ort mitschreiben, nichts hochladen."""

    def setUp(self):
        self.state = AppState()
        self.state.set_connection(u'verbunden')
        self.app = webapp.create_app(self.state)

    def test_localon_sets_mode_and_place(self):
        status, payload = call(self.app, '/localon/?place=Kletterhalle')
        self.assertTrue(status.startswith('200'))
        self.assertTrue(self.state.local)
        self.assertEqual(self.state.place(), u'Kletterhalle')

    def test_localon_never_enables_upload(self):
        """Die Zusage: aus der Kletterhalle geht nichts nach luftdaten."""
        call(self.app, '/localon/?place=Kletterhalle')
        self.assertFalse(self.state.stationary)
        self.assertFalse(self.state.recording)

    def test_answer_says_nothing_is_uploaded(self):
        status, payload = call(self.app, '/localon/')
        self.assertIn(u'nichts hochgeladen', payload['value'])

    def test_localoff_stops_it(self):
        call(self.app, '/localon/?place=Halle')
        call(self.app, '/localoff/')
        self.assertFalse(self.state.local)

    def test_modes_are_mutually_exclusive(self):
        def modes():
            return (self.state.recording, self.state.local, self.state.stationary)

        call(self.app, '/localon/?place=Halle')
        self.assertEqual(modes(), (False, True, False))

        # Ohne Stop wird nicht umgeschaltet.
        for route in ('/staton/', '/start/'):
            status, payload = call(self.app, route)
            self.assertTrue(payload.get('refused'), route)
            self.assertEqual(modes(), (False, True, False))

        call(self.app, '/localoff/')
        call(self.app, '/staton/')
        self.assertEqual(modes(), (False, False, True))
        call(self.app, '/statoff/')
        call(self.app, '/start/')
        self.assertEqual(modes(), (True, False, False))

    def test_localon_requires_a_sensor(self):
        state = AppState()
        app = webapp.create_app(state)
        status, payload = call(app, '/localon/?place=Halle')
        self.assertTrue(payload.get('refused'))
        self.assertFalse(state.local)

    def test_place_with_spaces_and_umlauts(self):
        call(self.app, '/localon/?place=B%C3%BCro%20Flur')
        # Kein Umlaut-Literal im Test: geprueft wird die ganze
        # Kette von der URL-Dekodierung bis zum Dateinamen.
        from recorder import slugify
        self.assertEqual(slugify(self.state.place()), 'buero_flur')

    def test_status_reports_local_mode(self):
        call(self.app, '/localon/?place=Halle')
        status, payload = call(self.app, '/status/')
        self.assertTrue(payload['local'])
        self.assertFalse(payload['stationary'])
        self.assertEqual(payload['place'], u'Halle')


class ConnectionRouteTest(unittest.TestCase):

    def setUp(self):
        from transport import FakeTransport
        self.state = AppState()
        self.transport = FakeTransport()
        self.app = webapp.create_app(self.state, transport=self.transport)

    def test_devices_lists_transport_devices(self):
        status, payload = call(self.app, '/devices/')
        self.assertTrue(status.startswith('200'))
        self.assertTrue(payload['devices'])
        self.assertIn('id', payload['devices'][0])
        self.assertIn('name', payload['devices'][0])
        # Ohne Auswahl wird das erste Geraet vorgeschlagen.
        self.assertEqual(payload['selected'], payload['devices'][0]['id'])

    def test_devices_prefers_configured_module(self):
        """Am PC stehen Kopfhoerer und Co. vor dem HC-06 -- vorgeschlagen
        wird trotzdem das Modul aus config.py."""
        class Desktop(object):
            def available_devices(self):
                return [{'id': '10:94:97:35:97:B6', 'name': 'Logitech'},
                        {'id': config.SDS011_BLUETOOTH_DEVICE_ID,
                         'name': 'DSDTECH HC-06'}]

        app = webapp.create_app(AppState(), transport=Desktop())
        status, payload = call(app, '/devices/')
        self.assertEqual(payload['selected'],
                         config.SDS011_BLUETOOTH_DEVICE_ID)

    def test_devices_without_transport(self):
        app = webapp.create_app(AppState())
        status, payload = call(app, '/devices/')
        self.assertTrue(status.startswith('200'))
        self.assertEqual(payload['devices'], [])

    def test_devices_survives_broken_transport(self):
        """Eine kaputte Geraeteliste darf die Seite nicht mitreissen."""
        class Broken(object):
            def available_devices(self):
                raise RuntimeError('Bluetooth aus')

        app = webapp.create_app(self.state, transport=Broken())
        status, payload = call(app, '/devices/')
        self.assertTrue(status.startswith('200'))
        self.assertEqual(payload['devices'], [])
        self.assertIn(u'Bluetooth aus', self.state.error())

    def test_connect_sets_wish_and_device(self):
        self.assertFalse(self.state.connection_wanted)
        device = self.transport.available_devices()[1]
        status, payload = call(self.app, '/connect/?device=' + device['id'])
        self.assertTrue(status.startswith('200'))
        self.assertTrue(self.state.connection_wanted)
        self.assertEqual(self.state.device(), (device['id'], device['name']))

    def test_connect_does_not_block(self):
        """Die Route aeussert nur den Wunsch -- der Aufbau passiert im
        SensorReader. Sonst haengt die Antwort am Verbindungsversuch."""
        import time
        start = time.time()
        call(self.app, '/connect/?device=x')
        self.assertLess(time.time() - start, 1.0)

    def test_disconnect_clears_wish(self):
        call(self.app, '/connect/')
        self.assertTrue(self.state.connection_wanted)
        call(self.app, '/disconnect/')
        self.assertFalse(self.state.connection_wanted)

    def test_status_reports_connection(self):
        status, payload = call(self.app, '/status/')
        self.assertEqual(payload['connection'], u'getrennt')
        self.assertFalse(payload['connection_wanted'])

        call(self.app, '/connect/')
        self.state.set_connection(u'verbunden')
        status, payload = call(self.app, '/status/')
        self.assertEqual(payload['connection'], u'verbunden')
        self.assertTrue(payload['connection_wanted'])

    def test_shutdown_clears_connection_wish(self):
        call(self.app, '/connect/')
        self.state.shutdown()
        self.assertFalse(self.state.connection_wanted)


class IntervalRouteTest(unittest.TestCase):
    """Das Messintervall aus der Oberflaeche: sofort im AppState und in
    der Einstellungsdatei, damit es einen Neustart ueberlebt."""

    def setUp(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.path = os.path.join(tmp, 'einstellungen.json')
        saved = config.SETTINGS_FILE
        config.SETTINGS_FILE = self.path
        self.addCleanup(setattr, config, 'SETTINGS_FILE', saved)
        self.state = AppState(record_interval=5)
        self.app = webapp.create_app(self.state)

    def test_valid_interval_is_set_and_saved(self):
        import settings
        status, payload = call(self.app, '/interval/?seconds=30')
        self.assertTrue(status.startswith('200'))
        self.assertEqual(payload, {'value': u'Messintervall: 30 s.', 'interval': 30})
        self.assertEqual(self.state.record_interval(), 30)
        self.assertEqual(settings.load(), {'record_interval': 30})

    def test_minutes_are_named_as_such(self):
        status, payload = call(self.app, '/interval/?seconds=300')
        self.assertEqual(payload['value'], u'Messintervall: 5 min.')

    def test_other_settings_are_kept(self):
        import settings
        settings.save({'record_interval': 10, 'anderes': u'bleibt'})
        call(self.app, '/interval/?seconds=60')
        self.assertEqual(settings.load(), {'record_interval': 60, 'anderes': u'bleibt'})

    def test_invalid_interval_is_refused(self):
        for query in ('seconds=7', 'seconds=abc', 'seconds=', '', 'seconds=-5',
                      'seconds=30.5'):
            status, payload = call(self.app, '/interval/?' + query)
            self.assertTrue(status.startswith('200'), query)
            self.assertTrue(payload.get('refused'), query)
            self.assertEqual(payload['value'], u'Ungültiges Messintervall.')
            self.assertEqual(payload['interval'], 5, query)
        self.assertEqual(self.state.record_interval(), 5)
        self.assertFalse(os.path.exists(self.path))

    def test_unsaved_interval_still_applies(self):
        """Kein Schreibrecht: das Intervall gilt trotzdem, nur nicht nach
        einem Neustart -- und die Antwort sagt das."""
        config.SETTINGS_FILE = os.path.join(self.path, 'fehlt', 'x.json')
        status, payload = call(self.app, '/interval/?seconds=10')
        self.assertFalse(payload.get('refused'))
        self.assertEqual(self.state.record_interval(), 10)
        self.assertIn(u'nicht dauerhaft gespeichert', payload['value'])

    def test_status_shows_interval_and_choices(self):
        call(self.app, '/interval/?seconds=60')
        status, payload = call(self.app, '/status/')
        self.assertEqual(payload['interval'], 60)
        self.assertEqual(payload['intervals'], list(config.RECORD_INT_CHOICES))
        self.assertEqual(payload['stationary_intervals'],
                         list(config.STATIONARY_RECORD_INT_CHOICES))

    def test_stationary_start_defaults_to_five_minutes(self):
        self.state.set_connection(u'verbunden')
        self.state.set_gps_available(False)
        self.state.set_record_interval(10)
        status, payload = call(self.app, '/staton/')
        self.assertFalse(payload.get('refused'))
        self.assertEqual(self.state.record_interval(), 300)
        self.assertFalse(os.path.exists(self.path))

    def test_stationary_start_keeps_fifteen_minutes(self):
        self.state.set_connection(u'verbunden')
        self.state.set_gps_available(False)
        self.state.set_record_interval(900)
        status, payload = call(self.app, '/staton/')
        self.assertFalse(payload.get('refused'))
        self.assertEqual(self.state.record_interval(), 900)

    def test_stationary_restricts_interval_choices(self):
        self.state.set_connection(u'verbunden')
        self.state.set_gps_available(False)
        call(self.app, '/staton/')
        status, payload = call(self.app, '/interval/?seconds=60')
        self.assertTrue(payload.get('refused'))
        self.assertEqual(self.state.record_interval(), 300)
        status, payload = call(self.app, '/interval/?seconds=900')
        self.assertFalse(payload.get('refused'))
        self.assertEqual(self.state.record_interval(), 900)


class HistoryRouteTest(unittest.TestCase):

    def setUp(self):
        import time
        self.now = time.time()
        self.state = AppState()
        self.state.add_history_point(self.now - 7200, 1.0, 2.0, 5, False)
        self.state.add_history_point(self.now - 20, 3.0, 4.0, 5, True)
        self.state.add_history_point(self.now - 10, 5.0, 6.0, 30, True)
        self.app = webapp.create_app(self.state)

    def test_all_points_without_range(self):
        for path in ('/history/', '/history/?range=0', '/history/?range=xyz'):
            status, payload = call(self.app, path)
            self.assertTrue(status.startswith('200'), path)
            self.assertEqual(len(payload['points']), 3, path)
        self.assertEqual(payload['rev'], 3)
        self.assertEqual(payload['interval'], 5)
        self.assertAlmostEqual(payload['now'], self.now, delta=5)
        first = payload['points'][0]
        self.assertAlmostEqual(first[0], self.now - 7200, delta=0.01)
        self.assertEqual(first[1:], [1.0, 2.0, 5, 0])
        self.assertEqual(payload['points'][2][1:], [5.0, 6.0, 30, 1])

    def test_range_limits_the_points(self):
        status, payload = call(self.app, '/history/?range=600')
        self.assertEqual([p[1] for p in payload['points']], [3.0, 5.0])

    def test_empty_history(self):
        status, payload = call(webapp.create_app(AppState()), '/history/')
        self.assertEqual(payload['points'], [])
        self.assertEqual(payload['rev'], 0)


class StaticFilesTest(unittest.TestCase):
    """Skript und Stylesheet duerfen nach einem Update nicht ungefragt aus
    dem Browser-Cache kommen, sonst laeuft altes app.js zum neuen
    Template."""

    def setUp(self):
        self.app = webapp.create_app(AppState())

    def test_static_files_are_revalidated(self):
        for name in ('app.js', 'app.css'):
            status, headers, body = call_raw(self.app, '/static/' + name)
            self.assertTrue(status.startswith('200'), (name, status))
            self.assertTrue(body, name)
            self.assertEqual(headers.get('cache-control'), 'no-cache', name)
            # Darauf beruht die billige Nachfrage.
            self.assertIn('last-modified', headers, name)

    def test_not_modified_keeps_the_header(self):
        """Die Nachfrage endet meist mit 304 -- auch das muss den Kopf
        tragen, sonst cacht der Browser ab dann wieder heuristisch."""
        status, headers, body = call_raw(self.app, '/static/app.js')
        status, headers, body = call_raw(
            self.app, '/static/app.js',
            HTTP_IF_MODIFIED_SINCE=headers['last-modified'])
        self.assertTrue(status.startswith('304'), status)
        self.assertEqual(headers.get('cache-control'), 'no-cache')

    def test_missing_file(self):
        status, headers, body = call_raw(self.app, '/static/gibt-es-nicht.js')
        self.assertTrue(status.startswith('404'), status)
        self.assertEqual(headers.get('cache-control'), 'no-cache')


class _ShiftedClock(object):
    """Ersatz fuer das Modul time in webapp: die Uhr laeuft offset
    Sekunden vor, localtime bleibt das echte."""

    def __init__(self, offset):
        self.offset = offset

    def time(self):
        return time.time() + self.offset

    def localtime(self, *args):
        return time.localtime(*args)


class ChartRouteTest(unittest.TestCase):
    """/chart.svg und die Meldung im leeren Diagramm."""

    def setUp(self):
        self.state = AppState(record_interval=900)
        self.app = webapp.create_app(self.state)

    def label(self):
        """Die Beschriftung des SVG; sie enthaelt die Meldung."""
        status, headers, body = call_raw(self.app, '/chart.svg?range=3600&w=400&h=240')
        self.assertTrue(status.startswith('200'), status)
        self.assertEqual(headers['content-type'], 'image/svg+xml; charset=utf-8')
        self.assertEqual(headers.get('cache-control'), 'no-store')
        root = ElementTree.fromstring(body)
        self.assertEqual(root.get('width'), '400')
        return root.get('aria-label')

    def test_without_sensor(self):
        self.state.set_next_point_at(time.time() + 870)
        self.assertIn(u'Kein Sensor verbunden', self.label())

    def test_connected_names_the_time_of_the_first_point(self):
        """Die Seite laedt das Bild bis zu einer Minute lang nicht neu.
        Ein "in 870 s" stuende so lange still -- die Uhrzeit nicht."""
        due = time.time() + 870
        self.state.set_connection(u'verbunden')
        self.state.set_next_point_at(due)
        label = self.label()
        clock = time.strftime('%H:%M:%S', time.localtime(math.ceil(due)))
        self.assertIn(u'Erster Mittelwert um ' + clock, label)
        self.assertIsNone(re.search(r'in \d+ s', label), label)

    def test_message_does_not_age(self):
        """Dasselbe Bild eine Minute spaeter: die Meldung stimmt noch."""
        self.state.set_connection(u'verbunden')
        self.state.set_next_point_at(time.time() + 870)
        first = self.label()
        try:
            webapp.time = _ShiftedClock(60)
            later = self.label()
        finally:
            webapp.time = time
        self.assertIn(u'Erster Mittelwert', first)
        self.assertEqual(first, later)

    def test_no_first_point_message_once_there_are_points(self):
        self.state.set_connection(u'verbunden')
        self.state.set_next_point_at(time.time() + 870)
        self.state.add_history_point(time.time() - 30, 3.0, 4.0, 900, False)
        self.assertNotIn(u'Erster Mittelwert', self.label())

    def test_no_first_point_message_without_schedule(self):
        self.state.set_connection(u'verbunden')
        label = self.label()
        self.assertNotIn(u'Erster Mittelwert', label)
        self.assertNotIn(u'Kein Sensor verbunden', label)

    def test_raw_chart_uses_raw_values(self):
        self.state.set_connection(u'verbunden')
        self.state.set_measurement(12.3, 45.6)
        status, headers, body = call_raw(
            self.app, '/chart.svg?range=3600&w=400&h=240&series=raw')
        self.assertTrue(status.startswith('200'), status)
        self.assertEqual(headers['content-type'], 'image/svg+xml; charset=utf-8')
        self.assertIn(b'45,6', body)


class StatusFieldsTest(unittest.TestCase):
    """Die Felder fuer die neue Oberflaeche."""

    def setUp(self):
        self.state = AppState(record_interval=10)
        self.app = webapp.create_app(self.state)

    def status(self):
        status, payload = call(self.app, '/status/')
        self.assertTrue(status.startswith('200'))
        return payload

    def test_defaults_without_sensor(self):
        payload = self.status()
        self.assertIsNone(payload['measurement_age'])
        self.assertEqual(payload['pm_25_level'], 'none')
        self.assertEqual(payload['pm_10_level'], 'none')
        self.assertEqual(payload['history_rev'], 0)
        self.assertEqual(payload['raw_history_rev'], 0)
        self.assertIsNone(payload['next_point_in'])
        self.assertIsNone(payload['session'])
        self.assertIsNone(payload['upload'])
        self.assertEqual(payload['outdir'], config.OUTDIR)
        self.assertEqual(payload['stat_interval'], config.STAT_INT)
        self.assertEqual(payload['interval'], 10)

    def test_levels_follow_the_thresholds(self):
        self.state.set_measurement(30.0, 45.0)
        payload = self.status()
        self.assertEqual(payload['measurement_age'], 0)
        self.assertEqual(payload['pm_25_level'], 'elevated')
        self.assertEqual(payload['pm_10_level'], 'elevated')
        self.state.set_measurement(10.0, 55.0)
        payload = self.status()
        self.assertEqual(payload['pm_25_level'], 'good')
        self.assertEqual(payload['pm_10_level'], 'high')

    def test_stale_value_has_no_level(self):
        """Nach einem Abbruch bleibt der letzte Wert stehen -- er darf
        nicht weiter "gut" anzeigen."""
        from state import monotonic
        self.state.set_measurement(10.0, 20.0, at=monotonic() - 100)
        payload = self.status()
        self.assertEqual(payload['measurement_age'], 100)
        self.assertEqual(payload['pm_25_level'], 'none')
        self.assertEqual(payload['pm_10_level'], 'none')

    def test_settling_value_is_marked_but_still_visible(self):
        self.state.set_record_interval(300)
        self.state.set_connection(u'verbunden')
        self.state.set_measurement(10.0, 20.0, usable=False)
        payload = self.status()
        self.assertEqual(payload['measurement_age'], 0)
        self.assertFalse(payload['measurement_usable'])
        self.assertEqual(payload['pm_25'].strip(), '10.0')
        self.assertEqual(payload['pm_10'].strip(), '20.0')

    def test_power_save_sleep_value_keeps_level(self):
        """Im Sleep/Wake-Modus ist ein aelterer Wert waehrend des geplanten
        Sensorzyklus nicht veraltet."""
        from state import monotonic
        self.state.set_record_interval(300)
        self.state.set_connection(u'verbunden')
        self.state.set_measurement(10.0, 20.0, at=monotonic() - 100)
        payload = self.status()
        self.assertEqual(payload['measurement_age'], 100)
        self.assertEqual(payload['pm_25_level'], 'good')
        self.assertEqual(payload['pm_10_level'], 'good')

        too_old = 300 + config.SDS011_POWER_SAVE_SILENCE_SLACK + 1
        self.state.set_measurement(10.0, 20.0, at=monotonic() - too_old)
        payload = self.status()
        self.assertEqual(payload['pm_25_level'], 'none')
        self.assertEqual(payload['pm_10_level'], 'none')

    def test_history_and_next_point(self):
        import time
        self.state.add_history_point(time.time(), 1.0, 2.0, 10, False)
        self.state.set_next_point_at(time.time() + 7.2)
        payload = self.status()
        self.assertEqual(payload['history_rev'], 1)
        self.assertEqual(payload['raw_history_rev'], 0)
        self.assertEqual(payload['next_point_in'], 8)
        # Ein ueberfaelliger Termin wird nicht negativ.
        self.state.set_next_point_at(time.time() - 3)
        self.assertEqual(self.status()['next_point_in'], 0)

    def test_session_with_elapsed_and_rounded_means(self):
        import time
        started = time.time() - 125
        self.state.set_session({
            'mode': 'lokal', 'active': True, 'started': started, 'ended': None,
            'points': 3, 'avg_pm25': 12.345678, 'avg_pm10': 20.06,
            'file': u'feinstaub_halle_x.csv', 'place': u'Halle'})
        session = self.status()['session']
        self.assertTrue(124 <= session['elapsed'] <= 127, session['elapsed'])
        self.assertEqual(session['avg_pm25'], 12.3)
        self.assertEqual(session['avg_pm10'], 20.1)
        self.assertEqual(session['file'], u'feinstaub_halle_x.csv')
        self.assertEqual(session['place'], u'Halle')
        self.assertTrue(session['active'])

    def test_ended_session_keeps_its_duration(self):
        self.state.set_session({
            'mode': 'messfahrt', 'active': False, 'started': 1000.0, 'ended': 1600.0,
            'points': 0, 'avg_pm25': None, 'avg_pm10': None, 'file': u'', 'place': u''})
        session = self.status()['session']
        self.assertEqual(session['elapsed'], 600)
        self.assertIsNone(session['avg_pm25'])

    def test_upload_with_next_in(self):
        import time
        self.state.set_upload_info({'last_at': time.time() - 10, 'last_ok': True,
                                    'last_message': u'ok', 'next_at': time.time() + 229.5,
                                    'last_pm25': 12.345, 'last_pm10': 45.67})
        upload = self.status()['upload']
        self.assertEqual(upload['next_in'], 230)
        self.assertTrue(upload['last_ok'])
        self.assertEqual(upload['last_pm25'], 12.3)
        self.assertEqual(upload['last_pm10'], 45.7)
        self.state.set_upload_info({'last_at': None, 'last_ok': None,
                                    'last_message': u'', 'next_at': None})
        self.assertIsNone(self.status()['upload']['next_in'])



class OpenLinkTest(unittest.TestCase):
    """/open/: das WebView von QPython oeffnet keine neuen Fenster, also
    oeffnet der Server die Links unter Android im Browser des Systems."""

    def setUp(self):
        self.opened = []
        self.state = AppState()
        self.app = webapp.create_app(self.state, open_url=self.opened.append)

    def test_opens_known_link(self):
        status, body = call(self.app, '/open/?link=uba')
        self.assertTrue(status.startswith('200'), status)
        self.assertTrue(body['opened'])
        self.assertEqual(self.opened, [config.LINKS['uba']])

    def test_position_map_uses_current_gps_fix(self):
        self.state.set_position(52.123456, 13.987654)
        self.state.mark_gps_fix()
        status, body = call(self.app, '/open/?link=karte_position')
        self.assertTrue(status.startswith('200'), status)
        self.assertTrue(body['opened'])
        self.assertEqual(
            self.opened[-1],
            'https://deutschland.maps.sensor.community/#16/52.12346/13.98765')

    def test_position_map_falls_back_without_fresh_gps(self):
        self.state.set_position(52.123456, 13.987654)
        self.state.mark_gps_fix(monotonic() - config.GPS_MAX_AGE - 1)
        status, body = call(self.app, '/open/?link=karte_position')
        self.assertTrue(status.startswith('200'), status)
        self.assertTrue(body['opened'])
        self.assertEqual(self.opened[-1], config.LINKS['karte_position'])

    def test_refuses_unknown_name_and_raw_urls(self):
        """Nur Namen aus config.LINKS -- sonst koennte jede Seite, die den
        Server erreicht, beliebige Adressen auf dem Handy oeffnen."""
        for query in ('link=gibtsnicht', 'link=https%3A%2F%2Fexample.com', 'link=', ''):
            status, body = call(self.app, '/open/?' + query)
            self.assertTrue(status.startswith('200'), status)
            self.assertTrue(body['refused'], query)
            self.assertFalse(body['opened'], query)
        self.assertEqual(self.opened, [])

    def test_without_opener_the_browser_follows_the_link(self):
        """Am PC gibt es keinen Opener: die Route oeffnet nichts und nennt
        nur die Adresse."""
        status, body = call(webapp.create_app(AppState()), '/open/?link=karte')
        self.assertFalse(body['opened'])
        self.assertNotIn('refused', body)
        self.assertEqual(body['url'], config.LINKS['karte'])

    def test_without_opener_position_map_returns_dynamic_url(self):
        state = AppState()
        state.set_position(52.123456, 13.987654)
        state.mark_gps_fix()
        status, body = call(webapp.create_app(state), '/open/?link=karte_position')
        self.assertFalse(body['opened'])
        self.assertEqual(
            body['url'],
            'https://deutschland.maps.sensor.community/#16/52.12346/13.98765')

    def test_failure_is_reported(self):
        def broken(url):
            raise RuntimeError('kein Browser')
        status, body = call(webapp.create_app(AppState(), open_url=broken), '/open/?link=uba')
        self.assertTrue(status.startswith('200'), status)
        self.assertTrue(body['refused'])
        self.assertIn(u'kein Browser', body['value'])

    def test_index_tells_the_page_whether_to_use_the_route(self):
        _status, body = call(self.app, '/')
        self.assertIn(b'data-open-external="1"', body)
        _status, body = call(webapp.create_app(AppState()), '/')
        self.assertIn(b'data-open-external="0"', body)


class UrlOpenerTest(unittest.TestCase):
    """main.make_url_opener: droid.view() schickt die Adresse als Intent
    an Android und meldet Fehler im Ergebnis, nicht als Ausnahme."""

    class FakeDroid(object):
        def __init__(self, error=None):
            self.viewed = []
            self.error = error

        def view(self, url):
            self.viewed.append(url)

            class Result(object):
                pass
            result = Result()
            result.id, result.result, result.error = 1, None, self.error
            return result

    def test_passes_url_to_droid_view(self):
        import main
        droid = self.FakeDroid()
        main.make_url_opener(droid)(config.LINKS['uba'])
        self.assertEqual(droid.viewed, [config.LINKS['uba']])

    def test_android_error_becomes_exception(self):
        import main
        opener = main.make_url_opener(self.FakeDroid(error=u'No Activity found'))
        with self.assertRaises(RuntimeError):
            opener(config.LINKS['uba'])


if __name__ == '__main__':
    unittest.main()
