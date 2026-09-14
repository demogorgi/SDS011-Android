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


class TransportError(Exception):
    """Verbindungsaufbau oder Lesen fehlgeschlagen. Die Meldung landet
    unveraendert in der Oberflaeche, also bitte verstaendlich halten."""


class Transport(object):
    """Byte-Quelle mit explizitem Verbindungszustand.

    Das Verbinden ist Sache des Aufrufers (SensorReader), nicht mehr ein
    Nebeneffekt von read(). Frueher versuchte read() bei jedem Aufruf
    neu zu verbinden -- endlos, im Sekundentakt, ohne dass die
    Oberflaeche davon etwas mitbekam.
    """

    def available_devices(self):
        """Liste von {'id': ..., 'name': ...}. Leer, wenn die Plattform
        keine Geraeteliste liefert."""
        return []

    def connect(self, device_id=None):
        """Baut die Verbindung auf. Wirft TransportError bei Misserfolg."""
        raise NotImplementedError

    def disconnect(self):
        pass

    def is_connected(self):
        return False

    def read(self, max_bytes):
        """Liefert bytes (moeglicherweise leer). Wirft TransportError,
        wenn die Verbindung weg ist."""
        raise NotImplementedError

    def close(self):
        self.disconnect()


class AndroidBluetoothTransport(Transport):
    """Liest den Sensor ueber das HC05/HC06-Modul unter QPython.

    Gegenueber frueher: das Ergebnis von b64decode bleibt bytes. Der
    Umweg ueber str(...)[2:-1] und unicode_escape ist weg -- er hat die
    Bytes ueber ihre repr()-Darstellung verarbeitet und brach bei jedem
    Byte, das als Anfuehrungszeichen oder Backslash dargestellt wird.
    """

    def __init__(self, device_id=None, uuid=None):
        import androidhelper
        self._default_device = device_id or config.SDS011_BLUETOOTH_DEVICE_ID
        self._uuid = uuid or config.SSP_UUID
        self._droid = androidhelper.Android()
        self._conn_id = None

    # -- Geraeteliste -------------------------------------------------
    def available_devices(self):
        """Gekoppelte Geraete, damit die MAC nicht im Quelltext stehen muss.

        androidhelper leitet jeden Methodennamen per RPC weiter, je nach
        QPython-Version existiert die Gegenstelle also oder eben nicht.
        Deshalb defensiv: was nicht geht, faellt auf die konfigurierte
        Adresse zurueck.
        """
        devices = []
        for method in ('bluetoothGetBondedDevices', 'bluetoothGetDiscoveredDevices'):
            try:
                result = getattr(self._droid, method)()
            except Exception as exc:
                write_log(2, '{0} nicht verfuegbar: {1}'.format(method, exc))
                continue
            if getattr(result, 'error', None) or not result.result:
                continue
            for entry in result.result:
                if isinstance(entry, dict):
                    address = entry.get('address') or entry.get('Address')
                    name = entry.get('name') or entry.get('Name') or address
                else:
                    address, name = entry, entry
                if address and address not in [d['id'] for d in devices]:
                    devices.append({'id': address, 'name': name})
            if devices:
                break

        if not devices:
            write_log(1, 'Keine Geraeteliste verfuegbar, benutze konfigurierte Adresse')
            devices = [{'id': self._default_device,
                        'name': self._default_device + ' (aus config.py)'}]
        return devices

    # -- Verbindung ---------------------------------------------------
    def is_connected(self):
        if self._conn_id is None:
            return False
        try:
            return len(self._droid.bluetoothActiveConnections().result) > 0
        except Exception as exc:
            write_log(0, 'bluetoothActiveConnections fehlgeschlagen: {0}'.format(exc))
            return False

    def connect(self, device_id=None):
        address = device_id or self._default_device
        self.disconnect()
        write_log(1, 'Verbinde mit {0}...'.format(address))
        try:
            self._droid.toggleBluetoothState(True, False)
            result = self._droid.bluetoothConnect(self._uuid, address)
        except Exception as exc:
            raise TransportError(u'Bluetooth nicht ansprechbar: {0}'.format(exc))

        if getattr(result, 'error', None):
            raise TransportError(u'Verbindung abgelehnt: {0}'.format(result.error))
        if not result.result:
            raise TransportError(u'Sensor {0} nicht erreichbar.'.format(address))

        self._conn_id = result.result
        write_log(1, 'Verbunden mit {0}'.format(address))

    def disconnect(self):
        if self._conn_id is None:
            return
        try:
            self._droid.bluetoothStop(self._conn_id)
        except Exception as exc:
            write_log(0, 'bluetoothStop fehlgeschlagen: {0}'.format(exc))
        self._conn_id = None

    # -- Daten --------------------------------------------------------
    def read(self, max_bytes):
        if self._conn_id is None:
            raise TransportError(u'Nicht verbunden.')
        try:
            result = self._droid.bluetoothReadBinary(max_bytes, self._conn_id).result
        except Exception as exc:
            raise TransportError(u'Verbindung zum Sensor verloren: {0}'.format(exc))
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
        self.disconnect()
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

    # Geraete, die die Simulation "findet".
    DEVICES = [
        {'id': '00:14:03:05:59:17', 'name': 'HC-06 (simuliert)'},
        {'id': '00:14:03:05:59:18', 'name': 'Zweiter Sensor (simuliert)'},
    ]

    def __init__(self, interval=1.0, noise=False, clock=time.time, seed=42,
                 fail_connects=0, drop_after=None):
        self._interval = interval
        self._noise = noise
        self._clock = clock
        self._buffer = bytearray()
        self._next_frame = self._clock()
        self._step = 0

        # Zum Ueben der Verbindungslogik: die ersten fail_connects
        # Versuche schlagen fehl, nach drop_after Lesevorgaengen reisst
        # die Verbindung ab.
        self._fail_connects = fail_connects
        self._drop_after = drop_after
        self._connected = False
        self._device = None
        self._reads = 0
        self.connect_attempts = 0

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

    # -- Verbindung ---------------------------------------------------
    def available_devices(self):
        return [dict(d) for d in self.DEVICES]

    def is_connected(self):
        return self._connected

    def connect(self, device_id=None):
        self.connect_attempts += 1
        if self._fail_connects > 0:
            self._fail_connects -= 1
            raise TransportError(
                u'Sensor nicht erreichbar (simulierter Fehlversuch %d).'
                % self.connect_attempts)
        self._device = device_id or self.DEVICES[0]['id']
        self._connected = True
        self._reads = 0
        del self._buffer[:]
        write_log(1, 'FakeTransport verbunden mit {0}'.format(self._device))

    def disconnect(self):
        if self._connected:
            write_log(1, 'FakeTransport getrennt')
        self._connected = False

    # -- Daten --------------------------------------------------------
    def read(self, max_bytes):
        if not self._connected:
            raise TransportError(u'Nicht verbunden.')
        self._reads += 1
        if self._drop_after is not None and self._reads > self._drop_after:
            self._connected = False
            raise TransportError(u'Verbindung zum Sensor verloren (simuliert).')

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
        self.disconnect()
        write_log(0, 'FakeTransport geschlossen')


def create_transport():
    """Waehlt die Implementierung anhand der Umgebung."""
    if config.use_fake_hardware():
        write_log(1, 'Benutze simulierten Sensor (FakeTransport)')
        return FakeTransport()
    return AndroidBluetoothTransport()
