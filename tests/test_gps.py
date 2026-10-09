# -*- coding: utf-8 -*-
"""GPS: frische Positionen erkennen und ein verstummtes GPS neu anmelden.

Die Uhr ist eingespeist, damit die Tests nicht minutenlang warten.
"""

from __future__ import absolute_import

import sys
import types
import unittest

import gps
import webapp
from state import AppState
from tests.test_webapp import call


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ScriptedGps(gps.GpsSource):
    """Liefert frische Positionen, solange fresh True ist."""

    def __init__(self):
        self.fresh = True
        self.restarts = 0

    def read_fix(self):
        return (51.0, 6.0, self.fresh)

    def restart(self):
        self.restarts += 1


class GpsReaderTest(unittest.TestCase):

    def setUp(self):
        self.state = AppState()
        self.clock = Clock()
        self.source = ScriptedGps()
        self.reader = gps.GpsReader(self.state, self.source, clock=self.clock)

    def advance(self, seconds, step=5):
        for _ in range(int(seconds // step)):
            self.clock.now += step
            self.reader.step()

    def test_fresh_fix_is_recorded(self):
        self.advance(10)
        self.assertEqual(self.state.gps_age(now=self.clock.now), 0)

    def test_no_restart_while_fixes_arrive(self):
        self.advance(300)
        self.assertEqual(self.source.restarts, 0)

    def test_restart_after_a_minute_of_silence(self):
        self.source.fresh = False
        self.advance(55)
        self.assertEqual(self.source.restarts, 0)
        self.advance(5)
        self.assertEqual(self.source.restarts, 1)
        # Das Alter waechst weiter -- die Anzeige zeigt die Stille.
        self.assertEqual(self.state.gps_age(now=self.clock.now), 60)

    def test_restarts_back_off_while_silent(self):
        """In einer Halle: 60 s, dann 120 s, 240 s ... bis 600 s."""
        self.source.fresh = False
        self.advance(60 + 120 + 240)
        self.assertEqual(self.source.restarts, 3)
        self.advance(480)
        self.assertEqual(self.source.restarts, 4)

    def test_fix_resets_the_back_off(self):
        self.source.fresh = False
        self.advance(60 + 120)
        self.assertEqual(self.source.restarts, 2)
        self.source.fresh = True
        self.advance(5)
        self.source.fresh = False
        self.advance(60)
        self.assertEqual(self.source.restarts, 3)

    def test_no_restarts_without_gps(self):
        state = AppState()
        source = gps.NoGps()
        reader = gps.GpsReader(state, source, clock=self.clock)
        for _ in range(100):
            self.clock.now += 5
            reader.step()
        self.assertEqual(reader.restarts, 0)
        self.assertFalse(state.snapshot()['gps_available'])


class Result(object):
    def __init__(self, result=None):
        self.result = result
        self.error = None


class FakeDroid(object):
    location = None
    last_known = None
    calls = []

    def readLocation(self):
        return Result(FakeDroid.location)

    def getLastKnownLocation(self):
        return Result(FakeDroid.last_known)

    def startLocating(self, *args):
        FakeDroid.calls.append(('start',) + args)
        return Result()

    def stopLocating(self):
        FakeDroid.calls.append(('stop',))
        return Result()


class AndroidGpsTest(unittest.TestCase):

    def setUp(self):
        module = types.ModuleType('androidhelper')
        module.Android = FakeDroid
        self._saved = sys.modules.get('androidhelper')
        sys.modules['androidhelper'] = module
        FakeDroid.location = None
        FakeDroid.last_known = None
        FakeDroid.calls = []
        self.gps = gps.AndroidGps()

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('androidhelper', None)
        else:
            sys.modules['androidhelper'] = self._saved

    @staticmethod
    def fix(time_ms, lat=51.4, lon=6.7):
        return {'gps': {'latitude': lat, 'longitude': lon, 'time': time_ms}}

    def test_updates_even_when_standing_still(self):
        self.assertEqual(FakeDroid.calls[0], ('start', 5000, 0))

    def test_same_fix_time_is_not_new(self):
        FakeDroid.location = self.fix(1000)
        self.assertTrue(self.gps.read_fix()[2])
        self.assertFalse(self.gps.read_fix()[2])
        FakeDroid.location = self.fix(6000)
        self.assertTrue(self.gps.read_fix()[2])

    def test_last_known_location_is_never_new(self):
        FakeDroid.last_known = self.fix(1000)
        self.assertEqual(self.gps.read_fix(), (51.4, 6.7, False))

    def test_restart_stops_and_starts(self):
        self.gps.restart()
        self.assertEqual(FakeDroid.calls[-2:],
                         [('stop',), ('start', 5000, 0)])


class StatusRouteTest(unittest.TestCase):

    def test_gps_fields(self):
        state = AppState()
        app = webapp.create_app(state)
        _, payload = call(app, '/status/')
        self.assertTrue(payload['gps_available'])
        self.assertIsNone(payload['gps_age'])
        state.mark_gps_fix()
        _, payload = call(app, '/status/')
        self.assertEqual(payload['gps_age'], 0)


if __name__ == '__main__':
    unittest.main()
