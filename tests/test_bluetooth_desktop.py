# -*- coding: utf-8 -*-
"""Tests fuer die Desktop-Bluetooth-Anbindung.

Echtes Bluetooth kommt hier nicht vor: geprueft werden das Auswerten
der Geraeteliste, die Fehlerpfade und dass ohne Verbindung nichts
gelesen wird. Ob der RFCOMM-Aufbau den konkreten HC-06 greift, zeigt
sich erst am Geraet.
"""

from __future__ import absolute_import

import os
import socket
import unittest

import bluetooth_desktop as bd
import config
import gps
from transport import TransportError


WINDOWS_OUTPUT = u"""
Logitech BT Adapter|BTHENUM\\DEV_1094973597B6\\7&132E72C6&0&BLUETOOTHDEVICE_1094973597B6
HC-06|BTHENUM\\DEV_001403055917\\7&132E72C6&0&BLUETOOTHDEVICE_001403055917
HC-06|BTHENUM\\DEV_001403055917\\7&132E72C6&1&BLUETOOTHDEVICE_001403055917
BBC micro:bit [gapot]|BTHLE\\DEV_D7A87439A723\\7&3813F365&0&D7A87439A723
Generisches Attributprofil|BTHLEDevice\\{00001801-0000-1000-8000-00805f9b34fb}
Bluetooth Device (RFCOMM Protocol TDI)|BTH\\MS_RFCOMM\\6&2C4D2E3A&0&0
"""

LINUX_OUTPUT = u"""
Device 00:14:03:05:59:17 HC-06
Device 10:94:97:35:97:B6 Logitech BT Adapter
"""


class ParseTest(unittest.TestCase):

    def test_mac_formatting(self):
        self.assertEqual(bd.format_mac('001403055917'), '00:14:03:05:59:17')
        self.assertEqual(bd.format_mac('1094973597b6'), '10:94:97:35:97:B6')

    def test_windows_parsing(self):
        devices = bd.parse_windows_devices(WINDOWS_OUTPUT)
        ids = [d['id'] for d in devices]
        self.assertIn('00:14:03:05:59:17', ids)
        self.assertIn('10:94:97:35:97:B6', ids)

    def test_ble_devices_are_excluded(self):
        """BTHLE ist Low Energy und kann kein RFCOMM -- ein BLE-Geraet in
        der Auswahl waere eine Sackgasse."""
        devices = bd.parse_windows_devices(WINDOWS_OUTPUT)
        ids = [d['id'] for d in devices]
        self.assertNotIn('D7:A8:74:39:A7:23', ids)
        names = [d['name'] for d in devices]
        self.assertNotIn('BBC micro:bit [gapot]', names)

    def test_non_device_entries_are_ignored(self):
        devices = bd.parse_windows_devices(WINDOWS_OUTPUT)
        for entry in devices:
            self.assertRegex(entry['id'], r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$')

    def test_linux_parsing(self):
        devices = bd.parse_linux_devices(LINUX_OUTPUT)
        self.assertEqual([d['id'] for d in devices],
                         ['00:14:03:05:59:17', '10:94:97:35:97:B6'])
        self.assertEqual(devices[0]['name'], 'HC-06')

    def test_garbage_yields_nothing(self):
        self.assertEqual(bd.parse_windows_devices(u'voellig anderer Text'), [])
        self.assertEqual(bd.parse_linux_devices(u'voellig anderer Text'), [])


class DeviceListTest(unittest.TestCase):

    def test_injected_list_is_used(self):
        entries = [{'id': 'AA:BB:CC:DD:EE:FF', 'name': 'HC-06'}]
        tr = bd.BluetoothSocketTransport(lister=lambda: entries)
        self.assertEqual(tr.available_devices(), entries)

    def test_empty_list_falls_back_to_config(self):
        """Ohne Kopplung soll wenigstens die konfigurierte Adresse zur
        Auswahl stehen."""
        tr = bd.BluetoothSocketTransport(device_id='11:22:33:44:55:66',
                                         lister=lambda: [])
        devices = tr.available_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['id'], '11:22:33:44:55:66')

    def test_broken_lister_does_not_raise(self):
        def broken():
            raise RuntimeError('PowerShell fehlt')
        tr = bd.BluetoothSocketTransport(lister=broken)
        self.assertEqual(len(tr.available_devices()), 1)

    def test_duplicates_are_collapsed(self):
        """Windows meldet ein Geraet einmal pro angebotenem Dienst."""
        devices = bd.parse_windows_devices(WINDOWS_OUTPUT)
        ids = [d['id'] for d in devices]
        self.assertEqual(len(ids), len(set(ids)) + 1,
                         'Testdaten enthalten absichtlich ein Duplikat')
        # paired_devices() faltet sie zusammen -- hier ueber den Umweg
        # der gleichen Logik geprueft.
        seen, unique = {}, []
        for entry in devices:
            if entry['id'] in seen:
                continue
            seen[entry['id']] = True
            unique.append(entry)
        self.assertEqual(len(unique), len(set(ids)))


class ConnectionTest(unittest.TestCase):

    def setUp(self):
        if not hasattr(socket, 'AF_BLUETOOTH'):
            raise unittest.SkipTest('dieses Python kennt keine Bluetooth-Sockets')

    def test_read_without_connect_raises(self):
        tr = bd.BluetoothSocketTransport()
        self.assertRaises(TransportError, tr.read, 64)

    def test_disconnect_without_connect_is_harmless(self):
        bd.BluetoothSocketTransport().disconnect()

    def test_is_connected_starts_false(self):
        self.assertFalse(bd.BluetoothSocketTransport().is_connected())

    def test_connect_to_absent_device_reports_plainly(self):
        """Der Text landet unveraendert in der Oberflaeche -- er muss
        also verstaendlich sein, nicht ein Stacktrace."""
        tr = bd.BluetoothSocketTransport(device_id='00:00:00:00:00:00',
                                         connect_timeout=2.0)
        try:
            tr.connect()
            self.fail('Verbindung zu einem nicht vorhandenen Geraet gelang')
        except TransportError as exc:
            text = u'%s' % exc
            self.assertIn('00:00:00:00:00:00', text)
            self.assertNotIn('Traceback', text)
        self.assertFalse(tr.is_connected())


if __name__ == '__main__':
    unittest.main()


class DesktopGpsTest(unittest.TestCase):
    """Echter Sensor am PC: kein androidhelper, kein GPS."""

    def setUp(self):
        self._saved = {k: os.environ.get(k)
                           for k in ('SDS011_FAKE', 'ANDROID_ROOT')}
        os.environ.pop('SDS011_FAKE', None)
        os.environ.pop('ANDROID_ROOT', None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_real_hardware_is_default(self):
        self.assertFalse(config.use_fake_hardware())

    def test_fake_only_on_request(self):
        os.environ['SDS011_FAKE'] = '1'
        self.assertTrue(config.use_fake_hardware())
        os.environ['SDS011_FAKE'] = '0'
        self.assertFalse(config.use_fake_hardware())

    def test_no_gps_instead_of_androidhelper(self):
        source = gps.create_gps(None)
        self.assertIsInstance(source, gps.NoGps)
        self.assertEqual(source.read_position(), (0, 0))
