# -*- coding: utf-8 -*-
"""Thread, der den SDS011 ausliest und den AppState fuellt."""

from __future__ import absolute_import

import threading

from logging_util import write_log
from protocol import FrameDecoder


class SensorReader(threading.Thread):

    # So viel wird pro Runde maximal angefordert. Der Sensor sendet
    # etwa ein 10-Byte-Paket pro Sekunde.
    READ_SIZE = 64

    def __init__(self, state, transport, idle_wait=0.2):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._transport = transport
        self._decoder = FrameDecoder()
        self._idle_wait = idle_wait
        self._running = True
        self.frames_seen = 0

    def run(self):
        while self._running and self._state.sensing:
            try:
                chunk = self._transport.read(self.READ_SIZE)
            except Exception as exc:
                write_log(0, 'Lesefehler am Sensor: {0}'.format(exc))
                if self._state.wait(1):
                    break
                continue

            if not chunk:
                # Nichts da -- kurz warten, statt zu busy-loopen.
                if self._state.wait(self._idle_wait):
                    break
                continue

            for reading in self._decoder.feed(chunk):
                self.frames_seen += 1
                self._state.set_measurement(reading.pm_25, reading.pm_10)
                write_log(3, 'pm_25={0}, pm_10={1}'.format(
                    reading.pm_25, reading.pm_10))

    def stop(self):
        self._running = False
        self._transport.close()
