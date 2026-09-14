# -*- coding: utf-8 -*-
"""Tests fuer den stoppbaren Webserver."""

from __future__ import absolute_import

import socket
import threading
import time
import unittest

import bottle

import server

try:
    from urllib.request import urlopen
except ImportError:                       # Python 2
    from urllib2 import urlopen

# Dauer der kuenstlich langsamen Route.
SLOW_SECONDS = 0.4


class StoppableServerTest(unittest.TestCase):

    def setUp(self):
        self.app = bottle.Bottle()

        @self.app.route('/ping')
        def ping():
            return {'ok': True}

        @self.app.route('/langsam')
        def langsam():
            # Steht stellvertretend fuer alles, was auf dem Geraet
            # dauern kann: eine Bluetooth-Abfrage, ein traeges Dateisystem.
            time.sleep(SLOW_SECONDS)
            return {'ok': True}

        # Port 0: das Betriebssystem sucht einen freien Port. Feste Ports
        # sind gefaehrlich, weil sich unter Windows dank SO_REUSEADDR
        # mehrere Prozesse an denselben Port binden koennen.
        self.srv = server.StoppableWSGIRefServer(host='127.0.0.1', port=0,
                                                 quiet=True)
        self.thread = threading.Thread(
            target=lambda: bottle.run(app=self.app, server=self.srv, quiet=True))
        self.thread.daemon = True
        self.thread.start()
        self.assertTrue(self.srv.started.wait(10), 'Server kam nicht hoch')

    def tearDown(self):
        self.srv.stop()
        self.thread.join(10)

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.srv.port, path)

    def test_serves_requests(self):
        body = urlopen(self._url('/ping'), timeout=5).read()
        self.assertIn(b'ok', body)

    def test_stop_returns_and_thread_ends(self):
        start = time.time()
        self.assertTrue(self.srv.stop())
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        # Ein Poll-Intervall plus etwas Luft.
        self.assertLess(time.time() - start,
                        server.StoppableWSGIRefServer.POLL_INTERVAL + 5)

    def test_stop_is_idempotent(self):
        self.assertTrue(self.srv.stop())
        self.assertTrue(self.srv.stop())
        self.assertTrue(self.srv.stop())

    def test_port_is_assigned_by_os(self):
        self.assertGreater(self.srv.port, 0)


class ConcurrencyTest(StoppableServerTest):
    """Der wsgiref-Server ist von Haus aus einfaedrig: eine Anfrage nach
    der anderen. Ein Browser oeffnet aber mehrere Verbindungen
    gleichzeitig, und die Seite fragt den Status im Sekundentakt ab --
    eine langsame Anfrage legte damit alles still."""

    def _fetch(self, path, results, key):
        started = time.time()
        try:
            urlopen(self._url(path), timeout=20).read()
            results[key] = time.time() - started
        except Exception as exc:
            results[key] = exc

    def test_requests_are_handled_in_parallel(self):
        count = 5
        results = {}
        threads = [threading.Thread(target=self._fetch,
                                    args=('/langsam', results, i))
                   for i in range(count)]
        started = time.time()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        elapsed = time.time() - started

        for key in range(count):
            self.assertNotIsInstance(results.get(key), Exception,
                                     'Anfrage %d: %r' % (key, results.get(key)))
        # Seriell waeren es count * SLOW_SECONDS. Grosszuegige Grenze,
        # aber deutlich unter der seriellen Dauer.
        serial = count * SLOW_SECONDS
        self.assertLess(elapsed, serial * 0.6,
                        'Anfragen laufen seriell: %.2fs fuer %d Anfragen '
                        '(seriell waeren %.2fs)' % (elapsed, count, serial))

    def test_slow_request_does_not_block_a_fast_one(self):
        """Der eigentliche Punkt: waehrend etwas Langsames laeuft, muss
        die Statusabfrage weiter durchkommen."""
        results = {}
        slow = threading.Thread(target=self._fetch,
                                args=('/langsam', results, 'slow'))
        slow.start()
        time.sleep(0.05)          # sicherstellen, dass die langsame laeuft

        started = time.time()
        urlopen(self._url('/ping'), timeout=20).read()
        fast_elapsed = time.time() - started

        slow.join(30)
        self.assertNotIsInstance(results.get('slow'), Exception)
        self.assertLess(fast_elapsed, SLOW_SECONDS * 0.7,
                        'schnelle Anfrage musste auf die langsame warten: %.2fs'
                        % fast_elapsed)


class HttpsAttemptTest(StoppableServerTest):
    """Chrome stuft Adressen gern selbsttaetig auf https hoch. Der
    Browser meldet dann "hat eine ungueltige Antwort gesendet" -- und
    ohne diesen Zweig blieb die Konsole stumm, der Server wartete auf
    eine Anfragezeile, die nie kommt."""

    def _send_client_hello(self):
        sock = socket.create_connection(('127.0.0.1', self.srv.port), timeout=5)
        try:
            # Anfang eines TLS-ClientHello, ohne Escape-Sequenzen
            # zusammengesetzt.
            hello = server._TLS_HANDSHAKE + bytes(bytearray(
                [3, 1, 0, 47] + [1] * 40))
            sock.sendall(hello)
            sock.settimeout(5)
            return sock.recv(200)
        finally:
            sock.close()

    def test_connection_is_closed_promptly(self):
        start = time.time()
        answer = self._send_client_hello()
        self.assertEqual(answer, b'', 'Server hat auf TLS geantwortet')
        self.assertLess(time.time() - start, 4,
                        'Server haengt am TLS-Handshake statt aufzulegen')

    def test_server_keeps_working_afterwards(self):
        self._send_client_hello()
        body = urlopen(self._url('/ping'), timeout=10).read()
        self.assertIn(b'ok', body)

    def test_normal_requests_are_unaffected(self):
        """HTTP-Methoden beginnen immer mit einem Buchstaben, nie mit
        0x16 -- die Erkennung darf nichts Echtes abweisen."""
        for path in ('/ping', '/ping', '/ping'):
            self.assertIn(b'ok', urlopen(self._url(path), timeout=10).read())


class StopBeforeStartTest(unittest.TestCase):

    def test_stop_without_run_does_not_hang(self):
        srv = server.StoppableWSGIRefServer(host='127.0.0.1', port=0)
        start = time.time()
        # Wurde nie gestartet -- stop() muss nach dem Timeout aufgeben,
        # statt ewig auf das started-Event zu warten.
        self.assertFalse(srv.stop(timeout=0.5))
        self.assertLess(time.time() - start, 5)


if __name__ == '__main__':
    unittest.main()
