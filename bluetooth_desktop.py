# -*- coding: utf-8 -*-
"""Bluetooth-Anbindung fuer PC und Laptop.

Spricht das HC05/HC06-Modul ueber RFCOMM an -- dieselbe Denkweise wie
unter Android: verbunden wird ueber die MAC-Adresse, nicht ueber eine
COM-Port-Nummer. socket.AF_BLUETOOTH steckt in der Standardbibliothek,
es braucht also weder pyserial noch PyBluez.

Voraussetzung: das Modul muss einmal in den Bluetooth-Einstellungen des
Betriebssystems gekoppelt sein -- Windows verlangt fuer RFCOMM eine
bestehende Kopplung.

Dieses Modul laeuft nur auf dem Desktop. Auf dem Geraet uebernimmt
transport.AndroidBluetoothTransport; transport.create_transport()
importiert hier deshalb erst bei Bedarf.
"""

from __future__ import absolute_import

import re
import socket
import subprocess
import sys
import threading

import config
from logging_util import write_log
from transport import Transport, TransportError

# BTHENUM = Bluetooth Classic (kann RFCOMM), BTHLE = Low Energy (kann es
# nicht). Der HC-06 ist Classic.
_WINDOWS_DEVICE = re.compile(r'^BTHENUM\\DEV_([0-9A-Fa-f]{12})', re.IGNORECASE)
_LINUX_DEVICE = re.compile(r'^Device\s+([0-9A-Fa-f:]{17})\s+(.*)$')

_POWERSHELL_QUERY = (
    "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
    "ForEach-Object { $_.FriendlyName + '|' + $_.InstanceId }"
)


def format_mac(raw):
    """001403055917 -> 00:14:03:05:59:17"""
    raw = raw.upper()
    return ':'.join(raw[i:i + 2] for i in range(0, 12, 2))


def _run(command, timeout=15):
    """Externes Kommando ausfuehren, Ausgabe als Text.

    Liefert '' bei jedem Problem -- eine fehlende Geraeteliste darf
    nichts abbrechen, es gibt ja noch die Adresse aus config.py.
    """
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except (OSError, IOError) as exc:
        write_log(2, 'Geraeteliste: {0} nicht ausfuehrbar ({1})'.format(
            command[0], exc))
        return ''
    try:
        out, _ = proc.communicate(timeout=timeout)
    except TypeError:
        # Python 2 kennt den timeout-Parameter nicht.
        out, _ = proc.communicate()
    except Exception as exc:
        proc.kill()
        write_log(2, 'Geraeteliste abgebrochen: {0}'.format(exc))
        return ''
    return out.decode('utf-8', 'replace')


def parse_windows_devices(text):
    """Zeilen der Form 'Name|BTHENUM\\DEV_001403055917\\...' auswerten."""
    devices = []
    for line in text.splitlines():
        if '|' not in line:
            continue
        name, instance = line.rsplit('|', 1)
        match = _WINDOWS_DEVICE.match(instance.strip())
        if match:
            devices.append({'id': format_mac(match.group(1)),
                            'name': name.strip()})
    return devices


def parse_linux_devices(text):
    """Zeilen der Form 'Device 00:14:03:05:59:17 HC-06' auswerten."""
    devices = []
    for line in text.splitlines():
        match = _LINUX_DEVICE.match(line.strip())
        if match:
            devices.append({'id': match.group(1).upper(),
                            'name': match.group(2).strip()})
    return devices


def paired_devices():
    """Gekoppelte Bluetooth-Classic-Geraete als [{'id', 'name'}, ...]."""
    if sys.platform.startswith('win'):
        devices = parse_windows_devices(
            _run(['powershell', '-NoProfile', '-Command', _POWERSHELL_QUERY]))
    else:
        devices = parse_linux_devices(_run(['bluetoothctl', 'paired-devices']))

    # Windows meldet ein Geraet gern mehrfach, einmal pro angebotenem
    # Dienst -- Doppelte zusammenfassen, Reihenfolge erhalten.
    seen = {}
    unique = []
    for entry in devices:
        if entry['id'] in seen:
            continue
        seen[entry['id']] = True
        unique.append(entry)
    return unique


class BluetoothSocketTransport(Transport):
    """RFCOMM-Verbindung zum SDS011 ueber das HC05/HC06-Modul."""

    # Wie lange auf den Verbindungsaufbau gewartet wird.
    CONNECT_TIMEOUT = 10.0
    # Lesezeitfenster. Kurz, damit der SensorReader zwischendurch
    # mitbekommt, dass er aufhoeren soll.
    READ_TIMEOUT = 1.0

    def __init__(self, device_id=None, channel=None, lister=None,
                 connect_timeout=None, read_timeout=None):
        self._default_device = device_id or config.SDS011_BLUETOOTH_DEVICE_ID
        self._channel = channel or config.RFCOMM_CHANNEL
        # Einspeisbar, damit sich die Geraeteliste ohne echtes Bluetooth
        # testen laesst.
        self._lister = lister or paired_devices
        self._connect_timeout = connect_timeout or self.CONNECT_TIMEOUT
        self._read_timeout = read_timeout or self.READ_TIMEOUT
        self._socket = None
        self._lock = threading.Lock()

    # -- Geraeteliste -------------------------------------------------
    def available_devices(self):
        try:
            devices = self._lister()
        except Exception as exc:
            write_log(0, 'Geraeteliste nicht lesbar: {0}'.format(exc))
            devices = []
        if not devices:
            write_log(1, 'Keine gekoppelten Geraete gefunden, '
                         'benutze konfigurierte Adresse')
            devices = [{'id': self._default_device,
                        'name': self._default_device + ' (aus config.py)'}]
        return devices

    # -- Verbindung ---------------------------------------------------
    def is_connected(self):
        with self._lock:
            return self._socket is not None

    def connect(self, device_id=None):
        address = device_id or self._default_device
        self.disconnect()

        if not hasattr(socket, 'AF_BLUETOOTH'):
            raise TransportError(
                u'Dieses Python kennt keine Bluetooth-Sockets.')

        write_log(1, 'Verbinde mit {0} (RFCOMM Kanal {1})...'.format(
            address, self._channel))
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                             socket.BTPROTO_RFCOMM)
        sock.settimeout(self._connect_timeout)
        try:
            sock.connect((address, self._channel))
        except socket.timeout:
            sock.close()
            raise TransportError(
                u'Sensor %s antwortet nicht. Eingeschaltet und gekoppelt?'
                % address)
        except Exception as exc:
            sock.close()
            raise TransportError(
                u'Verbindung zu %s fehlgeschlagen: %s' % (address, exc))

        sock.settimeout(self._read_timeout)
        with self._lock:
            self._socket = sock
        write_log(1, 'Verbunden mit {0}'.format(address))

    def disconnect(self):
        with self._lock:
            sock = self._socket
            self._socket = None
        if sock is None:
            return
        try:
            sock.close()
        except Exception as exc:
            write_log(2, 'Socket schliessen fehlgeschlagen: {0}'.format(exc))
        write_log(1, 'Bluetooth-Verbindung getrennt')

    # -- Daten --------------------------------------------------------
    def read(self, max_bytes):
        with self._lock:
            sock = self._socket
        if sock is None:
            raise TransportError(u'Nicht verbunden.')
        try:
            data = sock.recv(max_bytes)
        except socket.timeout:
            # Kein Paket im Zeitfenster -- normal, der Sensor sendet nur
            # etwa einmal pro Sekunde. socket.timeout muss vor OSError
            # stehen, seit Python 3.10 ist es ein Alias von TimeoutError.
            return b''
        except Exception as exc:
            raise TransportError(u'Verbindung zum Sensor verloren: %s' % exc)

        if not data:
            # recv liefert b'' nur, wenn die Gegenstelle zugemacht hat.
            raise TransportError(u'Sensor hat die Verbindung geschlossen.')
        write_log(3, 'bluetooth read {0} byte'.format(len(data)))
        return data

    def close(self):
        self.disconnect()
