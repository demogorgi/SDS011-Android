# -*- coding: utf-8 -*-
"""Byte-Quelle fuer den SDS011.

Zwei Implementierungen hinter derselben Schnittstelle: die echte
Bluetooth-Verbindung ueber androidhelper und eine Simulation, mit der
das Programm ohne Geraet am PC laeuft.
"""

from __future__ import absolute_import

import base64
import random
import time

import config
import protocol
from logging_util import write_log


class Transport(object):
    """read() liefert bytes (moeglicherweise leer), close() raeumt auf."""

    def read(self, max_bytes):
        raise NotImplementedError

    def close(self):
        pass


class AndroidBluetoothTransport(Transport):
    """Liest den Sensor ueber das HC05/HC06-Modul.

    Gegenueber frueher: das Ergebnis von b64decode bleibt bytes. Der
    Umweg ueber str(...)[2:-1] und unicode_escape ist weg -- er hat die
    Bytes ueber ihre repr()-Darstellung verarbeitet und brach bei jedem
    Byte, das als Anfuehrungszeichen oder Backslash dargestellt wird.
    """

    def __init__(self, state, device_id=None, uuid=None):
        import androidhelper
        self._state = state
        self._device_id = device_id or config.SDS011_BLUETOOTH_DEVICE_ID
        self._uuid = uuid or config.SSP_UUID
        self._droid = androidhelper.Android()
        self._conn_id = None

    def _connected(self):
        try:
            return len(self._droid.bluetoothActiveConnections().result) > 0
        except Exception as exc:
            write_log(0, 'bluetoothActiveConnections fehlgeschlagen: {0}'.format(exc))
            return False

    def _connect(self):
        """Versucht genau einen Verbindungsaufbau. Liefert True bei Erfolg."""
        if self._conn_id is not None:
            try:
                self._droid.bluetoothStop(self._conn_id)
            except Exception:
                pass
            self._conn_id = None

        write_log(1, 'Verbinde mit Feinstaubsensor...')
        try:
            self._droid.toggleBluetoothState(True, False)
            result = self._droid.bluetoothConnect(self._uuid, self._device_id)
        except Exception as exc:
            self._state.report_error(u'Problem beim Verbinden mit Feinstaubsensor!')
            write_log(0, 'bluetoothConnect fehlgeschlagen: {0}'.format(exc))
            return False

        if result.error is None:
            self._conn_id = result.result
            self._state.clear_error()
            write_log(1, 'Verbunden')
            return True

        self._state.report_error(u'Problem beim Verbinden mit Feinstaubsensor!')
        write_log(0, 'bluetoothConnect meldet: {0}'.format(result.error))
        return False

    def read(self, max_bytes):
        if not self._connected() and not self._connect():
            # Kein blockierendes Warten -- der Aufrufer entscheidet.
            self._state.wait(1)
            return b''
        try:
            result = self._droid.bluetoothReadBinary(max_bytes, self._conn_id).result
        except Exception as exc:
            write_log(0, 'Bluetooth-Daten nicht lesbar: {0}'.format(exc))
            self._state.wait(1)
            return b''
        if not result:
            return b''
        try:
            data = base64.b64decode(result)
        except Exception as exc:
            write_log(0, 'base64-Dekodierung fehlgeschlagen: {0}'.format(exc))
            return b''
        write_log(3, 'bluetooth read {0} byte'.format(len(data)))
        return data

    def close(self):
        try:
            if self._conn_id is not None:
                self._droid.bluetoothStop(self._conn_id)
        except Exception as exc:
            write_log(0, 'bluetoothStop fehlgeschlagen: {0}'.format(exc))
        try:
            self._droid.exit()
        except Exception:
            pass
        write_log(0, 'bluetoothStop!')


class FakeTransport(Transport):
    """Simulierter Sensor.

    Die Werte sind bewusst verrauscht statt glatt. Eine perfekt
    gleichmaessige Messreihe ist in echten Feinstaubdaten ein Hinweis auf
    einen defekten Sensor -- eine Simulation, die so aussieht, traegt die
    falsche Erwartung ins Frontend und laesst die Grenzwertfarben nie
    ausloesen.

    Modelliert wird:
      * eine langsam driftende Grundlast (Random Walk)
      * die Grobfraktion, die den Abstand zwischen PM2.5 und PM10 macht
      * gelegentliche kurze Spitzen (vorbeifahrendes Auto, Baustelle),
        die vor allem PM10 hochziehen

    Physikalisch gilt immer PM10 >= PM2.5, weil PM10 die feineren
    Partikel einschliesst. Das haelt die Simulation ein.

    seed sorgt fuer Reproduzierbarkeit: derselbe Startwert ergibt
    dieselbe Messreihe. seed=None wuerfelt bei jedem Lauf neu.

    Mit noise=True kommt zusaetzlich Muell zwischen die Pakete, um die
    Resynchronisation des FrameDecoders zu ueben.
    """

    # Messbereich des SDS011.
    MIN_VALUE = 0.0
    MAX_VALUE = 999.9

    def __init__(self, interval=1.0, noise=False, clock=time.time, seed=42):
        self._interval = interval
        self._noise = noise
        self._clock = clock
        self._buffer = bytearray()
        self._next_frame = self._clock()
        self._step = 0

        self._random = random.Random(seed)
        # Ruhige Grundlast, wie sie an einem normalen Tag anliegt.
        self._base = 9.0
        self._spike_left = 0
        self._spike_height = 0.0

    def _values(self):
        self._step += 1
        rnd = self._random

        # Grundlast driftet langsam, bleibt aber in plausiblen Grenzen.
        self._base += rnd.gauss(0.0, 0.35)
        self._base = max(3.0, min(30.0, self._base))

        # Spitzen laufen ueber einige Sekunden aus.
        if self._spike_left > 0:
            self._spike_left -= 1
        elif rnd.random() < 0.04:
            self._spike_left = rnd.randint(3, 10)
            self._spike_height = rnd.uniform(10.0, 40.0)
        spike = self._spike_height * self._spike_left / 10.0

        pm_25 = self._base + rnd.gauss(0.0, 0.4) + spike * 0.35
        # Grobfraktion: der Anteil, der nur in PM10 steckt.
        coarse = self._base * rnd.uniform(0.5, 1.3) + spike
        pm_10 = pm_25 + max(0.0, coarse)

        return (self._clamp(pm_25), self._clamp(pm_10))

    def _clamp(self, value):
        value = max(self.MIN_VALUE, min(self.MAX_VALUE, value))
        # Der Sensor liefert Zehntel.
        return round(value, 1)

    def read(self, max_bytes):
        now = self._clock()
        if now >= self._next_frame:
            self._next_frame = now + self._interval
            if self._noise and self._step % 5 == 4:
                self._buffer.extend(b'\x00\xaa\x17')
            pm_25, pm_10 = self._values()
            self._buffer.extend(bytearray(protocol.build_frame(pm_25, pm_10)))
        if not self._buffer:
            return b''
        chunk = bytes(self._buffer[:max_bytes])
        del self._buffer[:max_bytes]
        return chunk

    def close(self):
        write_log(0, 'FakeTransport geschlossen')


def create_transport(state):
    """Waehlt die Implementierung anhand der Umgebung."""
    if config.use_fake_hardware():
        write_log(1, 'Benutze simulierten Sensor (FakeTransport)')
        return FakeTransport()
    return AndroidBluetoothTransport(state)
