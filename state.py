# -*- coding: utf-8 -*-
"""Gemeinsamer Zustand zwischen Mess-Threads und Webserver.

Ersetzt die frueheren Modul-Globals. Alle Zugriffe laufen ueber einen
Lock, weil GPS-Thread, Sensor-Thread, Aufzeichnungs-Thread und die
Bottle-Request-Threads gleichzeitig darauf zugreifen.
"""

from __future__ import absolute_import

import datetime
import threading


# datetime.timezone gibt es erst ab Python 3.2; datetime.utcnow() ist
# ab 3.12 abgekuendigt. Einmal beim Import entscheiden, was benutzt wird.
_UTC = getattr(datetime, 'timezone', None)


def utcnow():
    """Naives UTC-Datum -- auf beiden Python-Generationen warnungsfrei."""
    if _UTC is not None:
        return datetime.datetime.now(_UTC.utc).replace(tzinfo=None)
    return datetime.datetime.utcnow()


class AppState(object):

    def __init__(self):
        self._lock = threading.Lock()
        # Laufzeit-Flaggen. 'recording' hiess frueher 'run' und
        # kollidierte mit bottle.run.
        self.recording = False
        self.stationary = False
        self.sensing = True
        # Signal zum Beenden; ersetzt blockierende time.sleep()-Aufrufe.
        self.stop_event = threading.Event()

        self._pm_10 = 0.0
        self._pm_25 = 0.0
        self._lat = 0.0
        self._lon = 0.0
        self._utc = utcnow()
        self._status_text = u'inaktiv'
        self._error_msg = u''

    # -- Messwerte ----------------------------------------------------
    def set_measurement(self, pm_25, pm_10):
        with self._lock:
            self._pm_25 = pm_25
            self._pm_10 = pm_10

    def measurement(self):
        with self._lock:
            return (self._pm_25, self._pm_10)

    # -- Position -----------------------------------------------------
    def set_position(self, lat, lon, utc=None):
        with self._lock:
            self._lat = lat
            self._lon = lon
            # Wurde frueher nur einmal beim Thread-Start gesetzt, so dass
            # alle KML-Zeitstempel die Startzeit trugen.
            self._utc = utc if utc is not None else utcnow()

    def position(self):
        with self._lock:
            return (self._lat, self._lon, self._utc)

    # -- Anzeige ------------------------------------------------------
    def set_status(self, text):
        with self._lock:
            self._status_text = text

    def status(self):
        with self._lock:
            return self._status_text

    def report_error(self, text):
        with self._lock:
            self._error_msg = text

    def clear_error(self):
        with self._lock:
            self._error_msg = u''

    def error(self):
        with self._lock:
            return self._error_msg

    # -- Fuer die /status/-Route --------------------------------------
    def snapshot(self):
        """Ein konsistenter Blick auf alles, was das Frontend braucht."""
        with self._lock:
            return {
                'pm_25': self._pm_25,
                'pm_10': self._pm_10,
                'lat': self._lat,
                'lon': self._lon,
                'utc': self._utc,
                'status_text': self._status_text,
                'error_msg': self._error_msg,
                'recording': self.recording,
                'stationary': self.stationary,
            }

    # -- Lebenszyklus -------------------------------------------------
    def wait(self, seconds):
        """Wie time.sleep(), bricht aber beim Beenden sofort ab.
        Liefert True, wenn abgebrochen wurde."""
        return self.stop_event.wait(seconds)

    def shutdown(self):
        self.recording = False
        self.stationary = False
        self.sensing = False
        self.stop_event.set()
