# -*- coding: utf-8 -*-
"""Gemeinsamer Zustand zwischen Mess-Threads und Webserver.

Ersetzt die frueheren Modul-Globals. Alle Zugriffe laufen ueber einen
Lock, weil GPS-Thread, Sensor-Thread, Aufzeichnungs-Thread und die
Bottle-Request-Threads gleichzeitig darauf zugreifen.
"""

from __future__ import absolute_import

import datetime
import threading
import time


# datetime.timezone gibt es erst ab Python 3.2; datetime.utcnow() ist
# ab 3.12 abgekuendigt. Einmal beim Import entscheiden, was benutzt wird.
_UTC = getattr(datetime, 'timezone', None)


# Verbindungszustand des Sensors. Frueher war nicht unterscheidbar,
# ob der Sensor fehlt oder 0 ug/m3 misst -- beides sah in der
# Oberflaeche gleich aus.
CONN_DISCONNECTED = u'getrennt'
CONN_CONNECTING = u'verbinde'
CONN_CONNECTED = u'verbunden'
CONN_RETRYING = u'wartet auf nächsten Versuch'


# Fuer Zeitabstaende: springt nicht, wenn die Uhr gestellt wird.
# time.monotonic gibt es erst ab Python 3.3.
monotonic = getattr(time, 'monotonic', time.time)


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
        # Drei Modi, die sich gegenseitig ausschliessen:
        #   recording  -- Messfahrt: KML-Spur und CSV, braucht GPS
        #   local      -- Lokale Messung an einem Ort: nur CSV,
        #                 kein GPS noetig, KEIN Upload
        #   stationary -- Upload zu luftdaten.info
        self.recording = False
        self.local = False
        self.stationary = False
        self.sensing = True
        # Signal zum Beenden; ersetzt blockierende time.sleep()-Aufrufe.
        self.stop_event = threading.Event()

        self._pm_10 = 0.0
        self._pm_25 = 0.0
        # Wann der letzte Messwert kam (monotonic), None = noch keiner.
        self._pm_at = None
        self._lat = 0.0
        self._lon = 0.0
        self._utc = utcnow()
        # GPS: gibt es eins, und wann kam die letzte neue Position
        # (monotonic)? None = seit dem Start noch keine.
        self._gps_available = True
        self._gps_fix_at = None
        self._status_text = u'inaktiv'
        self._error_msg = u''

        # Verbindung. 'wanted' ist der Wunsch des Benutzers, der Rest
        # beschreibt, wo der Verbindungsaufbau gerade steht. Das
        # Verbinden ist explizit, das Verbunden-bleiben automatisch.
        self.connection_wanted = False
        self._connection = CONN_DISCONNECTED
        self._connection_error = u''
        self._device = None
        self._device_name = u''
        # Freitext fuer die lokale Messung, landet im Dateinamen.
        self._place = u''

    # -- Messwerte ----------------------------------------------------
    def set_measurement(self, pm_25, pm_10, at=None):
        with self._lock:
            self._pm_25 = pm_25
            self._pm_10 = pm_10
            self._pm_at = monotonic() if at is None else at

    def measurement_age(self, now=None):
        """Sekunden seit dem letzten Messwert, None ohne Messwert.

        Auch None, wenn die Uhr zurueckgestellt wurde: unter Python 2 ist
        monotonic nur time.time, und ein auf 0 geklemmtes Alter liesse
        einen alten Wert frisch aussehen.
        """
        with self._lock:
            pm_at = self._pm_at
        if pm_at is None:
            return None
        age = (monotonic() if now is None else now) - pm_at
        return age if age >= 0 else None

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

    def set_gps_available(self, available):
        with self._lock:
            self._gps_available = bool(available)

    def mark_gps_fix(self, at=None):
        """Eine neue Position ist eingetroffen."""
        with self._lock:
            self._gps_fix_at = monotonic() if at is None else at

    def gps_age(self, now=None):
        """Sekunden seit der letzten neuen Position, None ohne Fix --
        auch nach einer zurueckgestellten Uhr (siehe measurement_age)."""
        with self._lock:
            fix_at = self._gps_fix_at
        if fix_at is None:
            return None
        age = (monotonic() if now is None else now) - fix_at
        return age if age >= 0 else None

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

    # -- Verbindung ---------------------------------------------------
    def set_connection(self, conn_state, error=None):
        with self._lock:
            self._connection = conn_state
            if error is not None:
                self._connection_error = error
            elif conn_state == CONN_CONNECTED:
                self._connection_error = u''

    def connection(self):
        with self._lock:
            return (self._connection, self._connection_error)

    def is_connected(self):
        with self._lock:
            return self._connection == CONN_CONNECTED

    def set_device(self, device_id, name=u''):
        with self._lock:
            self._device = device_id
            self._device_name = name

    def device(self):
        with self._lock:
            return (self._device, self._device_name)

    # -- Ortsangabe ---------------------------------------------------
    def set_place(self, place):
        with self._lock:
            self._place = place or u''

    def place(self):
        with self._lock:
            return self._place

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
                'gps_available': self._gps_available,
                'gps_fix_at': self._gps_fix_at,
                'status_text': self._status_text,
                'error_msg': self._error_msg,
                'recording': self.recording,
                'local': self.local,
                'stationary': self.stationary,
                'place': self._place,
                'connection': self._connection,
                'connection_error': self._connection_error,
                'connection_wanted': self.connection_wanted,
                'device': self._device,
                'device_name': self._device_name,
            }

    # -- Lebenszyklus -------------------------------------------------
    def wait(self, seconds):
        """Wie time.sleep(), bricht aber beim Beenden sofort ab.
        Liefert True, wenn abgebrochen wurde."""
        return self.stop_event.wait(seconds)

    def shutdown(self):
        self.connection_wanted = False
        # Drei Modi, die sich gegenseitig ausschliessen:
        #   recording  -- Messfahrt: KML-Spur und CSV, braucht GPS
        #   local      -- Lokale Messung an einem Ort: nur CSV,
        #                 kein GPS noetig, KEIN Upload
        #   stationary -- Upload zu luftdaten.info
        self.recording = False
        self.local = False
        self.stationary = False
        self.sensing = False
        self.stop_event.set()
