# -*- coding: utf-8 -*-
"""SDS011-Protokoll. Reine Byte-Arithmetik, keine Hardware, keine
Threads -- deshalb vollstaendig am PC testbar.

Ein Datenpaket ist 10 Byte lang:

    AA C0 | PM25_L PM25_H PM10_L PM10_H ID1 ID2 | CHK AB

CHK ist die Summe der sechs Nutzbytes modulo 256. Die Pruefsumme wurde
frueher zwar mitgelesen, aber nie geprueft.

Portabilitaet: bytearray[i] liefert unter Python 2 und 3 ein int,
bytearray.find(b'..') funktioniert ebenfalls in beiden. Deshalb hier
durchgehend bytearray statt str/bytes.
"""

from __future__ import absolute_import

HEAD = 0xAA
COMMANDER_NO = 0xC0
TAIL = 0xAB
FRAME_LEN = 10

_HEAD_BYTES = b'\xaa'


class Reading(object):
    """Ein gueltiges Messpaket."""

    __slots__ = ('pm_25', 'pm_10', 'device_id')

    def __init__(self, pm_25, pm_10, device_id):
        self.pm_25 = pm_25
        self.pm_10 = pm_10
        self.device_id = device_id

    def __repr__(self):
        return 'Reading(pm_25=%r, pm_10=%r, device_id=0x%04x)' % (
            self.pm_25, self.pm_10, self.device_id)

    def __eq__(self, other):
        if not isinstance(other, Reading):
            return NotImplemented
        return (self.pm_25 == other.pm_25
                and self.pm_10 == other.pm_10
                and self.device_id == other.device_id)

    def __ne__(self, other):      # Python 2 leitet das nicht ab
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result


def checksum(payload):
    """Pruefsumme ueber die sechs Nutzbytes."""
    return sum(bytearray(payload)) % 256


def parse_frame(frame):
    """Prueft und zerlegt genau ein 10-Byte-Paket.

    Liefert ein Reading oder None, wenn Kopf, Ende oder Pruefsumme
    nicht stimmen.
    """
    data = bytearray(frame)
    if len(data) != FRAME_LEN:
        return None
    if data[0] != HEAD or data[1] != COMMANDER_NO or data[9] != TAIL:
        return None
    if checksum(data[2:8]) != data[8]:
        return None
    pm_25 = (data[2] | (data[3] << 8)) / 10.0
    pm_10 = (data[4] | (data[5] << 8)) / 10.0
    device_id = (data[6] << 8) | data[7]
    return Reading(round(pm_25, 3), round(pm_10, 3), device_id)


def build_frame(pm_25, pm_10, device_id=0xA160):
    """Baut ein gueltiges Paket -- fuer Tests und die Simulation."""
    raw_25 = int(round(pm_25 * 10))
    raw_10 = int(round(pm_10 * 10))
    payload = bytearray([
        raw_25 & 0xFF, (raw_25 >> 8) & 0xFF,
        raw_10 & 0xFF, (raw_10 >> 8) & 0xFF,
        (device_id >> 8) & 0xFF, device_id & 0xFF,
    ])
    return bytes(bytearray([HEAD, COMMANDER_NO])
                 + payload
                 + bytearray([checksum(payload), TAIL]))


class FrameDecoder(object):
    """Sammelt Bytes und gibt vollstaendige, gueltige Pakete heraus.

    Ersetzt das fruehere byteweise Lesen mit time.sleep(1), das sich
    gegen den ~1-Hz-Takt des Sensors dauerhaft desynchronisiert hat.
    Bei Muell im Strom wird um genau ein Byte weitergeschoben und neu
    nach einem Kopf gesucht.
    """

    # Reicht fuer gut 100 Pakete; verhindert unbegrenztes Wachsen,
    # falls der Sensor nur Muell liefert.
    MAX_BUFFER = 1024

    def __init__(self):
        self._buffer = bytearray()
        self.discarded_bytes = 0

    def feed(self, chunk):
        """Nimmt neue Bytes an und liefert die Liste der darin
        enthaltenen gueltigen Readings."""
        if chunk:
            self._buffer.extend(bytearray(chunk))
        if len(self._buffer) > self.MAX_BUFFER:
            dropped = len(self._buffer) - self.MAX_BUFFER
            del self._buffer[:dropped]
            self.discarded_bytes += dropped

        readings = []
        while True:
            start = self._buffer.find(_HEAD_BYTES)
            if start < 0:
                # Kein Kopf im Puffer -- nichts davon ist brauchbar.
                self.discarded_bytes += len(self._buffer)
                del self._buffer[:]
                break
            if start > 0:
                del self._buffer[:start]
                self.discarded_bytes += start
            if len(self._buffer) < FRAME_LEN:
                # Paket noch nicht vollstaendig, beim naechsten Mal weiter.
                break
            reading = parse_frame(self._buffer[:FRAME_LEN])
            if reading is None:
                del self._buffer[:1]
                self.discarded_bytes += 1
                continue
            del self._buffer[:FRAME_LEN]
            readings.append(reading)
        return readings

    def pending(self):
        """Anzahl noch nicht verarbeiteter Bytes -- nur fuer Debugging."""
        return len(self._buffer)
