# -*- coding: utf-8 -*-
"""Tests fuer den stoppbaren Webserver."""

from __future__ import absolute_import

import threading
import time
import unittest

import bottle

import server

try:
    from urllib.request import urlopen
except ImportError:                       # Python 2
    from urllib2 import urlopen


class StoppableServerTest(unittest.TestCase):

    def setUp(self):
        self.app = bottle.Bottle()

        @self.app.route('/ping')
        def ping():
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
