# -*- coding: utf-8 -*-
"""Gemeinsamer Zustand zwischen Mess-Threads und Webserver.

GPS-, Sensor- und Aufzeichnungs-Thread schreiben hinein; die Request-
Threads des Webservers lesen ihn, schalten die Modi und setzen den
Verbindungswunsch. Messwerte, Position, Anzeige und Verbindung laufen
deshalb ueber einen Lock. Dazu die Zeithelfer utcnow und monotonic fuer
Python 2 und 3.
"""

from __future__ import absolute_import

import datetime
import threading
import time


# datetime.timezone gibt es erst ab Python 3.2, datetime.utcnow() ist
# ab 3.12 abgekuendigt. Darum beim Import entscheiden, was benutzt wird.
_UTC = getattr(datetime, 'timezone', None)


# Verbindungszustand des Sensors. Eigene Werte, damit die Oberflaeche
# "Sensor fehlt" von "Sensor misst 0 ug/m3" unterscheiden kann.
CONN_DISCONNECTED = u'getrennt'
CONN_CONNECTING = u'verbinde'
CONN_CONNECTED = u'verbunden'
CONN_RETRYING = u'wartet auf nächsten Versuch'


# Fuer Zeitabstaende: springt nicht, wenn die Uhr gestellt wird.
# time.monotonic gibt es erst ab Python 3.3; unter Python 2 bleibt nur
# time.time, das beim Stellen der Uhr springen kann.
monotonic = getattr(time, 'monotonic', time.time)


def utcnow():
    """Naives UTC-Datum -- auf beiden Python-Generationen warnungsfrei."""
    if _UTC is not None:
        return datetime.datetime.now(_UTC.utc).replace(tzinfo=None)
    return datetime.datetime.utcnow()


class AppState(object):
    """Thread-sicherer Zustand der App; main.py legt genau eine Instanz an."""

    def __init__(self):
        self._lock = threading.Lock()
        # Laufzeit-Flaggen: einfache Attribute ohne Lock (bool-Zuweisungen
        # sind atomar). Dass immer nur ein Modus laeuft, stellt webapp.py
        # mit einem eigenen Lock sicher.
        # Drei Modi, die sich gegenseitig ausschliessen:
        #   recording  -- Messfahrt: KML-Spur und CSV, braucht GPS
        #   local      -- Lokale Messung an einem Ort: nur CSV,
        #                 kein GPS noetig, KEIN Upload
        #   stationary -- Upload zu luftdaten.info
        self.recording = False
        self.local = False
        self.stationary = False
        # Solange True, laufen die Threads; shutdown() setzt es auf False.
        self.sensing = True
        # Signal zum Beenden. Die Threads warten ueber wait() darauf statt
        # mit time.sleep(), damit das Programm sofort beendet werden kann.
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

        # Verbindung. connection_wanted ist der Wunsch des Benutzers, der
        # Rest beschreibt, wo der Verbindungsaufbau gerade steht. Aufbau
        # und Wiederverbinden erledigt der SensorReader.
        self.connection_wanted = False
        self._connection = CONN_DISCONNECTED
        self._connection_error = u''
        self._device = None
        self._device_name = u''
        # Freitext fuer die lokale Messung, landet im Dateinamen.
        self._place = u''

    # -- Messwerte ----------------------------------------------------
    def set_measurement(self, pm_25, pm_10, at=None):
        """Neuen Messwert speichern; at (monotonic) nur fuer Tests."""
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
        """Letzter Messwert als (pm_25, pm_10); 0.0, solange keiner kam."""
        with self._lock:
            return (self._pm_25, self._pm_10)

    # -- Position -----------------------------------------------------
    def set_position(self, lat, lon, utc=None):
        with self._lock:
            self._lat = lat
            self._lon = lon
            # Zeitstempel bei jeder Position neu setzen: die KML-Spur
            # braucht die Zeit jedes einzelnen Punkts.
            self._utc = utc if utc is not None else utcnow()

    def position(self):
        """(lat, lon, utc) der letzten Position; ob sie aktuell ist,
        sagt gps_age()."""
        with self._lock:
            return (self._lat, self._lon, self._utc)

    def set_gps_available(self, available):
        with self._lock:
            self._gps_available = bool(available)

    def mark_gps_fix(self, at=None):
        """Eine neue Position ist eingetroffen; Grundlage fuer gps_age()."""
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
        """Verbindungszustand setzen. Ohne error bleibt der alte
        Fehlertext stehen, ausser bei CONN_CONNECTED: dann wird er
        geloescht."""
        with self._lock:
            self._connection = conn_state
            if error is not None:
                self._connection_error = error
            elif conn_state == CONN_CONNECTED:
                self._connection_error = u''

    def connection(self):
        """(Zustand, Fehlertext); Zustand ist eine der CONN_-Konstanten."""
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
        """Verbindungswunsch und alle Modi zuruecknehmen, die Threads
        anhalten und per stop_event aus ihren Wartezeiten wecken."""
        self.connection_wanted = False
        self.recording = False
        self.local = False
        self.stationary = False
        self.sensing = False
        self.stop_event.set()
