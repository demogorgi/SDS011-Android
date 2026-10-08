# -*- coding: utf-8 -*-
"""Tests fuer die Bottle-Routen -- ohne echten Server, per WSGI-Aufruf."""

from __future__ import absolute_import

import json
import sys
import unittest
from io import BytesIO

import config
import webapp
from state import AppState


def call(app, path, method='GET'):
    """Ruft die WSGI-App direkt auf und liefert (status, body-dict).

    Query-String gehoert nach QUERY_STRING, nicht in PATH_INFO -- sonst
    findet bottle die Route nicht.
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
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured['status'] = status

    body = b''.join(app(environ, start_response))
    try:
        payload = json.loads(body.decode('utf-8'))
    except ValueError:
        payload = body
    return captured['status'], payload


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

    def test_start_clears_stationary(self):
        call(self.app, '/staton/')
        call(self.app, '/start/')
        self.assertTrue(self.state.recording)
        self.assertFalse(self.state.stationary)

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
                    'device', 'device_name'):
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

    def test_start_works_once_connected(self):
        self.state.set_connection(u'verbunden')
        status, payload = call(self.app, '/start/')
        self.assertFalse(payload.get('refused'))
        self.assertTrue(self.state.recording)
        self.assertEqual(self.state.error(), u'')

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
        self.state.set_connection(u'wartet auf naechsten Versuch')
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
        call(self.app, '/localon/?place=Halle')
        self.assertEqual((self.state.recording, self.state.local,
                          self.state.stationary), (False, True, False))

        call(self.app, '/staton/')
        self.assertEqual((self.state.recording, self.state.local,
                          self.state.stationary), (False, False, True))

        call(self.app, '/start/')
        self.assertEqual((self.state.recording, self.state.local,
                          self.state.stationary), (True, False, False))

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


if __name__ == '__main__':
    unittest.main()
