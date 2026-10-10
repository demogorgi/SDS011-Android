# -*- coding: utf-8 -*-
"""Tests fuer Verbindungsaufsicht und Wartezeiten."""

from __future__ import absolute_import

import time
import unittest

import state as state_module
from connection import Backoff
from sensor import SensorReader
from state import AppState
from transport import FakeTransport, TransportError


class BackoffTest(unittest.TestCase):
    """Reine Rechnerei -- ohne echte Wartezeit pruefbar."""

    def test_grows_exponentially(self):
        backoff = Backoff(start=1.0, factor=2.0, maximum=60.0)
        self.assertEqual([backoff.next_delay() for _ in range(5)],
                         [1.0, 2.0, 4.0, 8.0, 16.0])

    def test_is_capped(self):
        backoff = Backoff(start=1.0, factor=2.0, maximum=10.0)
        delays = [backoff.next_delay() for _ in range(10)]
        self.assertEqual(max(delays), 10.0)
        self.assertEqual(delays[-1], 10.0)

    def test_reset_starts_over(self):
        backoff = Backoff(start=1.0, factor=2.0, maximum=60.0)
        for _ in range(4):
            backoff.next_delay()
        backoff.reset()
        self.assertEqual(backoff.next_delay(), 1.0)

    def test_peek_does_not_advance(self):
        backoff = Backoff(start=2.0, factor=3.0)
        self.assertEqual(backoff.peek(), 2.0)
        self.assertEqual(backoff.peek(), 2.0)
        self.assertEqual(backoff.next_delay(), 2.0)
        self.assertEqual(backoff.peek(), 6.0)

    def test_no_tight_loop(self):
        """Frueher wurde jede Sekunde neu versucht, endlos -- auf dem
        Handy kostet das Akku und flutet das Log."""
        backoff = Backoff()
        total = sum(backoff.next_delay() for _ in range(10))
        self.assertGreater(total, 60.0,
                           'zehn Fehlversuche duerfen nicht in Sekunden durchrauschen')


class FakeTransportConnectionTest(unittest.TestCase):

    def test_read_without_connect_raises(self):
        fake = FakeTransport(interval=0.0)
        self.assertRaises(TransportError, fake.read, 64)

    def test_connect_then_read(self):
        fake = FakeTransport(interval=0.0)
        fake.connect()
        self.assertTrue(fake.is_connected())
        self.assertTrue(len(fake.read(64)) > 0)

    def test_failing_connects(self):
        fake = FakeTransport(interval=0.0, fail_connects=2)
        self.assertRaises(TransportError, fake.connect)
        self.assertRaises(TransportError, fake.connect)
        fake.connect()
        self.assertTrue(fake.is_connected())
        self.assertEqual(fake.connect_attempts, 3)

    def test_dropout(self):
        fake = FakeTransport(interval=0.0, drop_after=2)
        fake.connect()
        fake.read(64)
        fake.read(64)
        self.assertRaises(TransportError, fake.read, 64)
        self.assertFalse(fake.is_connected())

    def test_available_devices(self):
        devices = FakeTransport().available_devices()
        self.assertTrue(devices)
        for entry in devices:
            self.assertIn('id', entry)
            self.assertIn('name', entry)


class SupervisorTest(unittest.TestCase):
    """SensorReader gegen den Fake -- ohne Hardware."""

    def _reader(self, fake, **kwargs):
        state = AppState()
        backoff = Backoff(start=0.02, factor=2.0, maximum=0.1)
        reader = SensorReader(state, fake, idle_wait=0.01, backoff=backoff, **kwargs)
        return state, reader

    def _wait_for(self, predicate, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_does_not_connect_unasked(self):
        """Verbinden ist explizit -- ohne Klick passiert nichts."""
        fake = FakeTransport(interval=0.01)
        state, reader = self._reader(fake)
        reader.start()
        time.sleep(0.3)
        self.assertEqual(state.connection()[0], state_module.CONN_DISCONNECTED)
        self.assertEqual(fake.connect_attempts, 0)
        self.assertFalse(fake.is_connected())
        state.shutdown()
        reader.join(3)

    def test_connects_on_request(self):
        fake = FakeTransport(interval=0.01)
        state, reader = self._reader(fake)
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected()))
        self.assertTrue(self._wait_for(lambda: reader.frames_seen > 0))
        state.shutdown()
        reader.join(3)

    def test_retries_until_success(self):
        fake = FakeTransport(interval=0.01, fail_connects=3)
        state, reader = self._reader(fake)
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected()))
        self.assertEqual(fake.connect_attempts, 4)
        state.shutdown()
        reader.join(3)

    def _slow_retry_reader(self):
        """Erster Versuch scheitert, danach 30 s Wartezeit."""
        fake = FakeTransport(interval=0.01, fail_connects=1)
        state = AppState()
        reader = SensorReader(state, fake, idle_wait=0.01,
                              backoff=Backoff(start=30.0, maximum=60.0))
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(
            lambda: state.connection()[0] == state_module.CONN_RETRYING))
        return fake, state, reader

    def test_disconnect_interrupts_the_retry_wait(self):
        """Trennen und neu Verbinden wirkt sofort, nicht erst nach der
        Wartezeit des letzten Fehlversuchs."""
        fake, state, reader = self._slow_retry_reader()
        state.connection_wanted = False
        self.assertTrue(self._wait_for(
            lambda: state.connection()[0] == state_module.CONN_DISCONNECTED, timeout=1.0))
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected(), timeout=1.0))
        state.shutdown()
        reader.join(3)

    def test_other_device_interrupts_the_retry_wait(self):
        fake, state, reader = self._slow_retry_reader()
        state.set_device('11:22:33:44:55:66')
        self.assertTrue(self._wait_for(lambda: state.is_connected(), timeout=1.0))
        self.assertEqual(fake.connect_attempts, 2)
        state.shutdown()
        reader.join(3)

    def test_failure_is_visible_in_state(self):
        """Der Grund muss in der Oberflaeche ankommen, nicht nur im Log."""
        fake = FakeTransport(interval=0.01, fail_connects=50)
        state, reader = self._reader(fake)
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(
            lambda: state.connection()[0] == state_module.CONN_RETRYING))
        conn_state, error = state.connection()
        self.assertIn(u'nicht erreichbar', error)
        state.shutdown()
        reader.join(3)

    def test_reconnects_after_dropout(self):
        """Reisst die Strecke mitten in der Fahrt ab, muss der Reader das
        von selbst aufraeumen."""
        fake = FakeTransport(interval=0.01, drop_after=3)
        state, reader = self._reader(fake)
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected()))
        # Abbruch provozieren und auf die zweite Verbindung warten
        self.assertTrue(self._wait_for(lambda: fake.connect_attempts >= 2, timeout=8),
                        'keine Wiederverbindung nach Abbruch')
        state.shutdown()
        reader.join(3)

    def test_disconnect_on_request(self):
        fake = FakeTransport(interval=0.01)
        state, reader = self._reader(fake)
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected()))

        state.connection_wanted = False
        self.assertTrue(self._wait_for(
            lambda: state.connection()[0] == state_module.CONN_DISCONNECTED))
        self.assertFalse(fake.is_connected())
        state.shutdown()
        reader.join(3)

    def test_selected_device_is_used(self):
        fake = FakeTransport(interval=0.01)
        state, reader = self._reader(fake)
        second = FakeTransport.DEVICES[1]['id']
        state.set_device(second, u'Zweiter')
        reader.start()
        state.connection_wanted = True
        self.assertTrue(self._wait_for(lambda: state.is_connected()))
        self.assertEqual(fake._device, second)
        state.shutdown()
        reader.join(3)


if __name__ == '__main__':
    unittest.main()
