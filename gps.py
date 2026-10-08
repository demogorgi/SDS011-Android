# -*- coding: utf-8 -*-
"""GPS-Quelle und der Thread, der sie ausliest."""

from __future__ import absolute_import

import threading

import config
from logging_util import write_log
from state import utcnow


class GpsSource(object):
    """read_position() liefert (lat, lon) oder (0, 0), wenn kein Fix
    vorliegt."""

    def read_position(self):
        raise NotImplementedError

    def close(self):
        pass


class AndroidGps(GpsSource):

    def __init__(self, interval_ms=5000, min_distance=10):
        import androidhelper
        self._droid = androidhelper.Android()
        self._droid.startLocating(interval_ms, min_distance)

    def read_position(self):
        try:
            loc = self._droid.readLocation().result
            if not loc:
                loc = self._droid.getLastKnownLocation().result
            if not loc:
                return (0, 0)
            fix = loc.get('gps') or loc.get('network')
            if not fix:
                return (0, 0)
            return (fix['latitude'], fix['longitude'])
        except Exception as exc:
            write_log(0, 'GPS nicht lesbar: {0}'.format(exc))
            return (0, 0)

    def close(self):
        try:
            self._droid.stopLocating()
        except Exception:
            pass
        try:
            self._droid.exit()
        except Exception:
            pass
        write_log(0, 'locatingStop!')


class FakeGps(GpsSource):
    """Faehrt eine kleine Runde, damit KML-Linien entstehen."""

    def __init__(self, lat=51.4385, lon=6.7882, step=0.0002):
        self._lat = lat
        self._lon = lon
        self._step = step
        self._n = 0

    def read_position(self):
        self._n += 1
        return (self._lat + self._step * self._n,
                self._lon + self._step * (self._n % 7))

    def close(self):
        write_log(0, 'FakeGps geschlossen')


class NoGps(GpsSource):
    """Echter Sensor am PC oder Laptop: dort gibt es kein GPS, also
    nie einen Fix."""

    def read_position(self):
        return (0, 0)


def create_gps(state):
    if config.use_fake_hardware():
        write_log(1, 'Benutze simuliertes GPS (FakeGps)')
        return FakeGps()
    if config.on_android():
        return AndroidGps()
    # Echter Sensor am PC: androidhelper gibt es hier nicht.
    write_log(1, 'Kein GPS auf diesem Rechner')
    return NoGps()


class GpsReader(threading.Thread):
    """Haelt die Position im AppState aktuell."""

    def __init__(self, state, source, interval=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._source = source
        self._interval = config.GPS_INT if interval is None else interval
        self._running = True
        # Einmal sofort lesen, damit direkt nach dem Start etwas dasteht.
        lat, lon = self._source.read_position()
        self._state.set_position(lat, lon, utcnow())

    def run(self):
        # Frueher wurde hier die globale Variable t_gps abgefragt statt
        # self -- die Klasse war an ihren Instanznamen gebunden.
        while self._running and self._state.sensing:
            lat, lon = self._source.read_position()
            # Zeitstempel wandert mit; er wurde frueher nur einmal im
            # Konstruktor gesetzt.
            self._state.set_position(lat, lon, utcnow())
            if self._state.wait(self._interval):
                break

    def stop(self):
        self._running = False
        self._source.close()
