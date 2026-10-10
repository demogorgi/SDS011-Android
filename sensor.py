# -*- coding: utf-8 -*-
"""Thread, der den SDS011 ausliest und die Messwerte in den AppState schreibt.

Zugleich die Verbindungsaufsicht: Der Benutzer aeussert nur den Wunsch
(die Weboberflaeche setzt state.connection_wanted). Aufbau und
Wiederverbinden nach einem Abbruch erledigt der Reader selbst -- nach
Fehlschlaegen mit wachsender Wartezeit (Backoff), damit ein
ausgeschalteter Sensor nicht Akku und Log belastet.
Die Hardware steckt hinter dem uebergebenen Transport.
"""

from __future__ import absolute_import

import threading

import state as state_module
from state import monotonic
from connection import Backoff
from logging_util import to_text, write_log
from protocol import FrameDecoder
from transport import TransportError


class SensorReader(threading.Thread):
    """Daemon-Thread: Verbindung halten, Bytes lesen, Pakete dekodieren."""

    # So viel wird pro Runde maximal angefordert. Der Sensor sendet
    # etwa ein 10-Byte-Paket pro Sekunde.
    READ_SIZE = 64

    def __init__(self, state, transport, idle_wait=0.2, backoff=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._transport = transport
        self._decoder = FrameDecoder()
        self._idle_wait = idle_wait
        self._backoff = backoff if backoff is not None else Backoff()
        self._running = True
        self.frames_seen = 0

    # -- Verbindung ---------------------------------------------------
    def _drop(self, message):
        """Verbindung trennen, Decoder zuruecksetzen und den Grund anzeigen.

        Halb empfangene Pakete gehoeren zur alten Verbindung, deshalb ein
        neuer Decoder.
        """
        try:
            self._transport.disconnect()
        except Exception as exc:
            write_log(0, u'disconnect fehlgeschlagen: {0}'.format(to_text(exc)))
        self._decoder = FrameDecoder()
        if self._state.connection_wanted:
            self._state.set_connection(state_module.CONN_RETRYING, message)
        else:
            self._state.set_connection(state_module.CONN_DISCONNECTED, message)

    def _wait_retry(self, delay, device_id):
        """Wartet bis zum naechsten Verbindungsversuch, endet aber sofort,
        wenn der Benutzer trennt, ein anderes Geraet waehlt oder die App
        beendet wird. Sonst reagierte die Oberflaeche nach einigen
        Fehlversuchen bis zu einer Minute lang nicht."""
        deadline = monotonic() + delay
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return
            if self._state.wait(min(self._idle_wait, remaining)):
                return
            if not self._state.connection_wanted:
                return
            if self._state.device()[0] != device_id:
                # Neues Geraet: gleich versuchen, ohne alte Wartezeit.
                self._backoff.reset()
                return

    def _try_connect(self):
        """Ein Verbindungsversuch. Liefert True bei Erfolg.

        Bei einem Fehler wartet die Methode selbst die Backoff-Zeit ab
        (state.wait, endet sofort beim Beenden) und liefert dann False.
        """
        device_id, _ = self._state.device()
        self._state.set_connection(state_module.CONN_CONNECTING, u'')
        try:
            self._transport.connect(device_id)
        except TransportError as exc:
            delay = self._backoff.next_delay()
            write_log(1, u'Verbindung fehlgeschlagen ({0}), naechster Versuch in {1:.0f}s'
                      .format(to_text(exc), delay))
            self._state.set_connection(state_module.CONN_RETRYING, to_text(exc))
            self._wait_retry(delay, device_id)
            return False
        except Exception as exc:
            # Unerwartetes protokollieren und anzeigen, aber den Thread
            # nicht beenden.
            delay = self._backoff.next_delay()
            write_log(0, u'Unerwarteter Fehler beim Verbinden: {0}'.format(to_text(exc)))
            self._state.set_connection(state_module.CONN_RETRYING,
                                       u'Unerwarteter Fehler: {0}'.format(to_text(exc)))
            self._wait_retry(delay, device_id)
            return False

        self._backoff.reset()
        self._decoder = FrameDecoder()
        self._state.set_connection(state_module.CONN_CONNECTED, u'')
        return True

    # -- Hauptschleife ------------------------------------------------
    def run(self):
        while self._running and self._state.sensing:
            # 1. Der Benutzer will keine Verbindung.
            if not self._state.connection_wanted:
                if self._transport.is_connected():
                    self._transport.disconnect()
                    write_log(1, 'Verbindung auf Wunsch getrennt')
                if self._state.connection()[0] != state_module.CONN_DISCONNECTED:
                    self._state.set_connection(state_module.CONN_DISCONNECTED, u'')
                self._backoff.reset()
                if self._state.wait(self._idle_wait):
                    break
                continue

            # 2. Verbindung gewuenscht, aber nicht da.
            if not self._transport.is_connected():
                self._try_connect()
                continue

            # 3. Verbunden -- lesen.
            try:
                chunk = self._transport.read(self.READ_SIZE)
            except TransportError as exc:
                write_log(0, u'Lesefehler: {0}'.format(to_text(exc)))
                self._drop(to_text(exc))
                continue
            except Exception as exc:
                write_log(0, u'Unerwarteter Lesefehler: {0}'.format(to_text(exc)))
                self._drop(u'Unerwarteter Lesefehler: {0}'.format(to_text(exc)))
                continue

            if not chunk:
                # Nichts da: kurz warten, sonst dreht die Schleife leer.
                if self._state.wait(self._idle_wait):
                    break
                continue

            for reading in self._decoder.feed(chunk):
                self.frames_seen += 1
                self._state.set_measurement(reading.pm_25, reading.pm_10)
                write_log(3, u'pm_25={0}, pm_10={1}'.format(
                    reading.pm_25, reading.pm_10))

    def stop(self):
        """Schleife beenden und den Transport schliessen."""
        self._running = False
        self._transport.close()
