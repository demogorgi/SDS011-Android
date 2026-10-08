# -*- coding: utf-8 -*-
"""Tests fuer die Geraeteliste unter Android.

androidhelper gibt es nur auf dem Geraet. Hier steht ein Nachbau, der
nur die RPC-Antworten liefert, die der jeweilige Test braucht -- alle
anderen Methoden antworten wie SL4A mit einem Fehler.
"""

from __future__ import absolute_import

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


if __name__ == '__main__':
    unittest.main()
