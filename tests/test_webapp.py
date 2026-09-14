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
    """Ruft die WSGI-App direkt auf und liefert (status, body-dict)."""
    environ = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'QUERY_STRING': '',
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
                    'recording', 'stationary'):
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


if __name__ == '__main__':
    unittest.main()
