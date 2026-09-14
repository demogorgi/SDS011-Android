# -*- coding: utf-8 -*-
"""Tests fuer die Bottle-Routen -- ohne echten Server, per WSGI-Aufruf."""

from __future__ import absolute_import

import json
import sys
import unittest
from io import BytesIO

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
