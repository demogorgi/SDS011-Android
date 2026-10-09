# -*- coding: utf-8 -*-
"""Upload zu luftdaten.info -- gegen einen lokalen Server statt gegen
die echte API."""

from __future__ import absolute_import

import json
import threading
import unittest

try:                                   # Python 3
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:                    # Python 2
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

import recorder


class _Handler(BaseHTTPRequestHandler):
    status = 201
    seen = []

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        _Handler.seen.append((dict(self.headers.items()),
                              self.rfile.read(length)))
        self.send_response(_Handler.status)
        self.end_headers()

    def log_message(self, *args):
        pass


class PostJsonTest(unittest.TestCase):

    def setUp(self):
        _Handler.seen = []
        _Handler.status = 201
        self.server = HTTPServer(('127.0.0.1', 0), _Handler)
        self.url = 'http://127.0.0.1:%d/push' % self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever)
        thread.daemon = True
        thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_sends_body_and_headers(self):
        body = '{"sensordatavalues": [{"value_type": "P1", "value": "2.5"}]}'
        status = recorder.post_json(self.url, body, {
            'Content-Type': 'application/json', 'X-Sensor': 'raspi-1'})
        self.assertEqual(status, 201)
        headers, sent = _Handler.seen[0]
        headers = dict((k.lower(), v) for k, v in headers.items())
        self.assertEqual(headers['x-sensor'], 'raspi-1')
        self.assertEqual(headers['content-type'], 'application/json')
        self.assertEqual(json.loads(sent.decode('utf-8'))['sensordatavalues'][0]['value'], '2.5')

    def test_http_error_is_a_status_not_an_exception(self):
        _Handler.status = 403
        self.assertEqual(recorder.post_json(self.url, '{}', {}), 403)

    def test_network_error_raises(self):
        self.server.shutdown()
        self.server.server_close()
        with self.assertRaises(Exception):
            recorder.post_json(self.url, '{}', {}, timeout=2)
        # tearDown darf trotzdem aufraeumen.
        self.server = HTTPServer(('127.0.0.1', 0), _Handler)
        threading.Thread(target=self.server.serve_forever).start()


if __name__ == '__main__':
    unittest.main()
