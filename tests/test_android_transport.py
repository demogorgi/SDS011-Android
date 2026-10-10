# -*- coding: utf-8 -*-
"""Tests fuer die Geraeteliste unter Android.

androidhelper gibt es nur auf dem Geraet. Hier steht ein Nachbau, der
nur die RPC-Antworten liefert, die der jeweilige Test braucht -- alle
anderen Methoden antworten wie SL4A mit einem Fehler.
"""

from __future__ import absolute_import

import base64
import sys
import types
import unittest

import config


class Result(object):
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error


class FakeDroid(object):
    answers = {}

    def __getattr__(self, name):
        answer = self.answers.get(name)

        def call(*args):
            if answer is None:
                return Result(error='Unknown RPC: ' + name)
            return Result(answer(*args) if callable(answer) else answer)
        return call


class AndroidReadTest(unittest.TestCase):
    """Ein stummer Sensor darf den RPC-Lock nicht blockieren: sonst kommt
    disconnect() -- und damit das Beenden der App -- nie dran."""

    def setUp(self):
        module = types.ModuleType('androidhelper')
        module.Android = FakeDroid
        self._saved = sys.modules.get('androidhelper')
        sys.modules['androidhelper'] = module
        self.reads = []

        def read_binary(size, conn_id):
            self.reads.append(size)
            return base64.b64encode(b'\xaa\xc0').decode('ascii')

        FakeDroid.answers = {'toggleBluetoothState': True,
                             'bluetoothConnect': 'conn-1',
                             'bluetoothStop': True,
                             'bluetoothReadBinary': read_binary}
        from transport import AndroidBluetoothTransport
        self.transport = AndroidBluetoothTransport()
        self.transport.connect('00:14:03:05:59:17')

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('androidhelper', None)
        else:
            sys.modules['androidhelper'] = self._saved

    def test_nothing_ready_means_no_blocking_read(self):
        FakeDroid.answers['bluetoothReadReady'] = False
        self.assertEqual(self.transport.read(64), b'')
        self.assertEqual(self.reads, [])

    def test_ready_data_is_read(self):
        FakeDroid.answers['bluetoothReadReady'] = True
        self.assertEqual(self.transport.read(64), b'\xaa\xc0')
        self.assertEqual(self.reads, [64])

    def test_without_read_ready_it_reads_directly(self):
        """Aeltere QPython-Versionen kennen bluetoothReadReady nicht."""
        self.assertEqual(self.transport.read(64), b'\xaa\xc0')
        self.assertEqual(self.transport.read(64), b'\xaa\xc0')
        self.assertEqual(self.reads, [64, 64])


class AndroidDeviceListTest(unittest.TestCase):

    def setUp(self):
        module = types.ModuleType('androidhelper')
        module.Android = FakeDroid
        self._saved = sys.modules.get('androidhelper')
        sys.modules['androidhelper'] = module
        FakeDroid.answers = {}

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('androidhelper', None)
        else:
            sys.modules['androidhelper'] = self._saved

    def devices(self):
        from transport import AndroidBluetoothTransport
        return AndroidBluetoothTransport().available_devices()

    def test_configured_device_gets_its_name(self):
        """Ohne Geraeteliste: Name statt nackter MAC-Adresse."""
        FakeDroid.answers = {'bluetoothGetRemoteDeviceName': 'DSDTECH HC-06'}
        self.assertEqual(self.devices(),
                         [{'id': config.SDS011_BLUETOOTH_DEVICE_ID,
                           'name': u'DSDTECH HC-06'}])

    def test_without_name_lookup_falls_back_to_config(self):
        found = self.devices()
        self.assertEqual(found[0]['id'], config.SDS011_BLUETOOTH_DEVICE_ID)
        self.assertIn(u'aus config.py', found[0]['name'])

    def test_bonded_devices_as_dict(self):
        FakeDroid.answers = {'bluetoothGetBondedDevices':
                             {'00:14:03:05:59:17': 'DSDTECH HC-06'}}
        self.assertEqual(self.devices(),
                         [{'id': '00:14:03:05:59:17', 'name': 'DSDTECH HC-06'}])

    def test_bare_addresses_are_named(self):
        FakeDroid.answers = {
            'bluetoothGetBondedDevices': ['00:14:03:05:59:17'],
            'bluetoothGetRemoteDeviceName': lambda address: 'HC-06 ' + address[-2:],
        }
        self.assertEqual(self.devices()[0]['name'], u'HC-06 17')


    def test_nested_objects_never_become_names(self):
        """{Adresse: Objekt} ergab im Browser '[object Object]'."""
        FakeDroid.answers = {'bluetoothGetBondedDevices': {
            '00:14:03:05:59:17': {'name': 'DSDTECH HC-06', 'type': 1},
            '20:18:5B:EA:80:26': {'bondState': 12}}}
        found = {d['id']: d['name'] for d in self.devices()}
        self.assertEqual(found['00:14:03:05:59:17'], 'DSDTECH HC-06')
        self.assertEqual(found['20:18:5B:EA:80:26'], '20:18:5B:EA:80:26')


class ParseDeviceEntriesTest(unittest.TestCase):

    def parse(self, raw):
        from transport import parse_device_entries
        return sorted(parse_device_entries(raw))

    def test_name_to_address(self):
        self.assertEqual(self.parse({'DSDTECH HC-06': '00:14:03:05:59:17'}),
                         [('00:14:03:05:59:17', 'DSDTECH HC-06')])

    def test_list_of_objects(self):
        self.assertEqual(
            self.parse([{'address': '00:14:03:05:59:17', 'name': 'HC-06'},
                        {'Address': '20:18:5B:EA:80:26'}]),
            [('00:14:03:05:59:17', 'HC-06'), ('20:18:5B:EA:80:26', None)])

    def test_pairs(self):
        self.assertEqual(self.parse([['HC-06', '00:14:03:05:59:17']]),
                         [('00:14:03:05:59:17', 'HC-06')])

    def test_junk_is_ignored(self):
        self.assertEqual(self.parse({'count': 2, 'devices': None}), [])
        self.assertEqual(self.parse(42), [])


if __name__ == '__main__':
    unittest.main()
