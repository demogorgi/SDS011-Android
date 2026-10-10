# -*- coding: utf-8 -*-
"""Thread, der den SDS011 ausliest und den AppState fuellt.

Enthaelt zugleich die Verbindungsaufsicht: Verbinden ist explizit (der
Benutzer setzt state.connection_wanted), Verbunden-bleiben ist
automatisch. Reisst die Strecke mitten in der Messfahrt ab, raeumt der
Reader das von selbst auf -- mit wachsender Wartezeit, statt wie frueher
im Sekundentakt endlos neu zu versuchen.
"""

from __future__ import absolute_import

import threading

import state as state_module
from connection import Backoff
from logging_util import to_text, write_log
from protocol import FrameDecoder
from transport import TransportError


class SensorReader(threading.Thread):

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
        """Verbindung als weg markieren und den Grund anzeigen."""
        try:
            self._transport.disconnect()
        except Exception as exc:
            write_log(0, u'disconnect fehlgeschlagen: {0}'.format(to_text(exc)))
        self._decoder = FrameDecoder()
        if self._state.connection_wanted:
            self._state.set_connection(state_module.CONN_RETRYING, message)
        else:
            self._state.set_connection(state_module.CONN_DISCONNECTED, message)

    def _try_connect(self):
        """Ein Verbindungsversuch. Liefert True bei Erfolg."""
        device_id, _ = self._state.device()
        self._state.set_connection(state_module.CONN_CONNECTING, u'')
        try:
            self._transport.connect(device_id)
        except TransportError as exc:
            delay = self._backoff.next_delay()
            write_log(1, u'Verbindung fehlgeschlagen ({0}), naechster Versuch in {1:.0f}s'
                      .format(to_text(exc), delay))
            self._state.set_connection(state_module.CONN_RETRYING, to_text(exc))
            self._state.wait(delay)
            return False
        except Exception as exc:
            # Unerwartetes nicht verschlucken, aber auch nicht den Thread
            # mitreissen.
            delay = self._backoff.next_delay()
            write_log(0, u'Unerwarteter Fehler beim Verbinden: {0}'.format(to_text(exc)))
            self._state.set_connection(state_module.CONN_RETRYING,
                                       u'Unerwarteter Fehler: {0}'.format(to_text(exc)))
            self._state.wait(delay)
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
                # Nichts da -- kurz warten, statt zu busy-loopen.
                if self._state.wait(self._idle_wait):
                    break
                continue

            for reading in self._decoder.feed(chunk):
                self.frames_seen += 1
                self._state.set_measurement(reading.pm_25, reading.pm_10)
                write_log(3, u'pm_25={0}, pm_10={1}'.format(
                    reading.pm_25, reading.pm_10))

    def stop(self):
        self._running = False
        self._transport.close()
