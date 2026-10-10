# -*- coding: utf-8 -*-
"""GPS-Quelle und der Thread, der sie ausliest."""

from __future__ import absolute_import

import threading

import config
from connection import Backoff
from logging_util import to_text, write_log
from state import monotonic, utcnow


class GpsSource(object):
    """read_position() liefert (lat, lon) oder (0, 0), wenn kein Fix
    vorliegt."""

    # False: auf diesem Geraet gibt es gar kein GPS.
    available = True

    def read_position(self):
        raise NotImplementedError

    def read_fix(self):
        """(lat, lon, neu) -- neu ist True, wenn seit dem letzten Aufruf
        eine frische Position eingetroffen ist."""
        lat, lon = self.read_position()
        return (lat, lon, (lat, lon) != (0, 0))

    def restart(self):
        """Beim Betriebssystem ab- und wieder anmelden."""
        pass

    def close(self):
        pass


class AndroidGps(GpsSource):

    # min_distance 0: auch im Stand alle interval_ms eine Position.
    # Frueher 10 m -- wer stand, bekam keine neuen Positionen mehr und
    # war nicht von einem verlorenen GPS zu unterscheiden.
    def __init__(self, interval_ms=5000, min_distance=0):
        import androidhelper
        self._droid = androidhelper.Android()
        self._interval_ms = interval_ms
        self._min_distance = min_distance
        self._last_fix_time = None
        self._droid.startLocating(interval_ms, min_distance)

    def read_position(self):
        lat, lon, _ = self.read_fix()
        return (lat, lon)

    def read_fix(self):
        try:
            fix = _pick(self._droid.readLocation().result)
            if fix:
                # 'time' ist der Zeitpunkt der Messung in ms. Liefert
                # readLocation dieselbe Zeit wie zuletzt, ist nichts
                # Neues gekommen.
                fix_time = fix.get('time')
                new = fix_time is None or fix_time != self._last_fix_time
                self._last_fix_time = fix_time
                return (fix['latitude'], fix['longitude'], new)
            # Die letzte bekannte Position kann Stunden alt sein -- als
            # Anzeige besser als nichts, aber nie "neu".
            fix = _pick(self._droid.getLastKnownLocation().result)
            if fix:
                return (fix['latitude'], fix['longitude'], False)
            return (0, 0, False)
        except Exception as exc:
            write_log(0, u'GPS nicht lesbar: {0}'.format(to_text(exc)))
            return (0, 0, False)

    def restart(self):
        try:
            self._droid.stopLocating()
        except Exception as exc:
            write_log(1, u'stopLocating fehlgeschlagen: {0}'.format(to_text(exc)))
        try:
            self._droid.startLocating(self._interval_ms, self._min_distance)
        except Exception as exc:
            write_log(0, u'startLocating fehlgeschlagen: {0}'.format(to_text(exc)))

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


def _pick(loc):
    """Aus der SL4A-Antwort die GPS-Position, sonst die aus dem Netz."""
    if not loc:
        return None
    return loc.get('gps') or loc.get('network')


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

    available = False

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

    def __init__(self, state, source, interval=None, clock=None,
                 backoff=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._source = source
        self._interval = config.GPS_INT if interval is None else interval
        self._clock = clock or monotonic
        # Wartezeit bis zur naechsten Neuanmeldung. Waechst, solange das
        # GPS stumm bleibt -- in einer Halle kommt nie ein Signal, dann
        # muss nicht jede Minute neu angemeldet werden.
        self._backoff = backoff or Backoff(start=config.GPS_RESTART_AFTER,
                                           maximum=config.GPS_RESTART_MAX)
        self._silent_since = self._clock()
        self.restarts = 0
        self._running = True
        self._state.set_gps_available(source.available)
        # Einmal sofort lesen, damit direkt nach dem Start etwas dasteht.
        self.step()

    def step(self):
        """Eine Runde: Position lesen, bei langer Stille neu anmelden."""
        lat, lon, new = self._source.read_fix()
        # Zeitstempel wandert mit; er wurde frueher nur einmal im
        # Konstruktor gesetzt.
        self._state.set_position(lat, lon, utcnow())
        now = self._clock()
        if new:
            self._state.mark_gps_fix(now)
            self._silent_since = now
            self._backoff.reset()
            return
        if not self._source.available:
            return
        if now - self._silent_since >= self._backoff.peek():
            write_log(1, u'GPS seit {0:.0f}s stumm, melde neu an'.format(
                now - self._silent_since))
            self._source.restart()
            self.restarts += 1
            self._backoff.next_delay()
            self._silent_since = now

    def run(self):
        # Frueher wurde hier die globale Variable t_gps abgefragt statt
        # self -- die Klasse war an ihren Instanznamen gebunden.
        while self._running and self._state.sensing:
            self.step()
            if self._state.wait(self._interval):
                break

    def stop(self):
        self._running = False
        self._source.close()
