# -*- coding: utf-8 -*-
"""Simulierter Sensor in der Geraeteliste.

Er steht neben den echten Modulen zur Wahl. Seine Werte sind erfunden:
sie duerfen nie oeffentlich hochgeladen werden, die Dateien tragen
'sim_' im Namen, und waehrend einer Messung wird nicht zwischen echt und
simuliert gewechselt.
"""

from __future__ import absolute_import

import os
import shutil
import tempfile
import time
import unittest

import config
import gps
import recorder as recorder_module
import transport
import webapp
from protocol import FrameDecoder
from recorder import Recorder
from state import AppState, CONN_CONNECTED
from tests.test_webapp import call

SIM = config.SIM_DEVICE_ID


class _NoFakeEnv(unittest.TestCase):
    """SDS011_FAKE macht alles zur Simulation -- fuer diese Tests aus."""

    def setUp(self):
        self._saved_fake = os.environ.pop('SDS011_FAKE', None)

    def tearDown(self):
        if self._saved_fake is not None:
            os.environ['SDS011_FAKE'] = self._saved_fake


class _RealStub(transport.Transport):
    """Echter Transport ohne Hardware: merkt sich, was passiert."""

    def __init__(self, devices=None, fail_listing=False):
        self.devices = devices if devices is not None else [
            {'id': '00:14:03:05:59:17', 'name': 'HC-06'}]
        self.fail_listing = fail_listing
        self.connected = None
        self.closed = False

    def available_devices(self):
        if self.fail_listing:
            raise transport.TransportError(u'Bluetooth aus')
        return list(self.devices)

    def connect(self, device_id=None):
        self.connected = device_id

    def disconnect(self):
        self.connected = None

    def is_connected(self):
        return self.connected is not None

    def read(self, max_bytes):
        return b''

    def close(self):
        self.closed = True


class IsSimulationTest(_NoFakeEnv):

    def test_only_the_sim_device(self):
        self.assertTrue(config.is_simulation(SIM))
        self.assertFalse(config.is_simulation('00:14:03:05:59:17'))
        self.assertFalse(config.is_simulation(None))

    def test_fake_env_makes_everything_simulated(self):
        os.environ['SDS011_FAKE'] = '1'
        try:
            self.assertTrue(config.is_simulation('00:14:03:05:59:17'))
        finally:
            del os.environ['SDS011_FAKE']


class SelectableTransportTest(unittest.TestCase):

    def setUp(self):
        self.real = _RealStub()
        self.sel = transport.SelectableTransport(
            self.real, fake_factory=lambda: transport.FakeTransport(clock=lambda: 0.0))

    def test_sim_entry_comes_after_the_real_devices(self):
        ids = [d['id'] for d in self.sel.available_devices()]
        self.assertEqual(ids, ['00:14:03:05:59:17', SIM])

    def test_sim_delivers_valid_frames(self):
        self.sel.connect(SIM)
        self.assertTrue(self.sel.is_connected())
        self.assertIsNone(self.real.connected)
        frames = FrameDecoder().feed(self.sel.read(64))
        self.assertTrue(frames)

    def test_switching_disconnects_the_other_side(self):
        self.sel.connect('00:14:03:05:59:17')
        self.assertEqual(self.real.connected, '00:14:03:05:59:17')
        self.sel.connect(SIM)
        self.assertIsNone(self.real.connected)
        self.sel.connect('00:14:03:05:59:17')
        self.assertTrue(self.sel.is_connected())
        self.assertEqual(self.real.connected, '00:14:03:05:59:17')

    def test_listing_error_goes_to_the_caller(self):
        sel = transport.SelectableTransport(_RealStub(fail_listing=True))
        with self.assertRaises(transport.TransportError):
            sel.available_devices()
        self.assertEqual([d['id'] for d in sel.simulated_devices()], [SIM])

    def test_close_closes_both(self):
        self.sel.connect(SIM)
        self.sel.close()
        self.assertTrue(self.real.closed)
        self.assertFalse(self.sel.is_connected())


class SimulatedOnDemandGpsTest(unittest.TestCase):

    def test_follows_the_selected_sensor(self):
        state = AppState()
        source = gps.SimulatedOnDemandGps(lambda: state.device()[0] == SIM)
        reader = gps.GpsReader(state, source, interval=0.01)
        self.assertFalse(state.snapshot()['gps_available'])
        self.assertIsNone(state.gps_age())

        state.set_device(SIM, config.SIM_DEVICE_NAME)
        reader.step()
        self.assertTrue(state.snapshot()['gps_available'])
        self.assertIsNotNone(state.gps_age())

        state.set_device('00:14:03:05:59:17', u'HC-06')
        reader.step()
        self.assertFalse(state.snapshot()['gps_available'])


class WebappTest(_NoFakeEnv):

    def setUp(self):
        _NoFakeEnv.setUp(self)
        self.state = AppState()
        self.real = _RealStub()
        self.app = webapp.create_app(
            self.state, transport=transport.SelectableTransport(self.real))

    def connect(self, device_id):
        status, body = call(self.app, '/connect/?device=' + device_id)
        self.state.set_connection(CONN_CONNECTED)
        return body

    def test_device_list_offers_the_sim(self):
        _status, body = call(self.app, '/devices/')
        self.assertIn(SIM, [d['id'] for d in body['devices']])
        # Vorgewaehlt bleibt das echte Modul aus config.py.
        self.assertEqual(body['selected'], '00:14:03:05:59:17')

    def test_sim_offered_even_when_bluetooth_listing_fails(self):
        app = webapp.create_app(self.state, transport=transport.SelectableTransport(
            _RealStub(fail_listing=True)))
        _status, body = call(app, '/devices/')
        self.assertEqual([d['id'] for d in body['devices']], [SIM])
        self.assertIn(u'Bluetooth aus', self.state.error())

    def test_status_flags_simulation(self):
        self.connect(SIM)
        _status, body = call(self.app, '/status/')
        self.assertTrue(body['simulated'])
        self.assertEqual(body['device_name'], config.SIM_DEVICE_NAME)
        self.connect('00:14:03:05:59:17')
        _status, body = call(self.app, '/status/')
        self.assertFalse(body['simulated'])

    def test_stationary_refused_with_sim(self):
        self.connect(SIM)
        _status, body = call(self.app, '/staton/')
        self.assertTrue(body['refused'])
        self.assertIn(u'simuliert', body['value'])
        self.assertFalse(self.state.stationary)

    def test_stationary_allowed_with_real_sensor(self):
        self.connect('00:14:03:05:59:17')
        _status, body = call(self.app, '/staton/')
        self.assertNotIn('refused', body)
        self.assertTrue(self.state.stationary)

    def test_local_and_trip_allowed_with_sim(self):
        self.connect(SIM)
        _status, body = call(self.app, '/localon/?place=Test')
        self.assertNotIn('refused', body)
        self.assertTrue(self.state.local)

    def test_no_switch_between_real_and_sim_during_a_measurement(self):
        self.connect('00:14:03:05:59:17')
        call(self.app, '/start/')
        self.assertTrue(self.state.recording)
        _status, body = call(self.app, '/connect/?device=' + SIM)
        self.assertTrue(body['refused'])
        self.assertEqual(self.state.device()[0], '00:14:03:05:59:17')
        # Dasselbe Modul neu verbinden geht weiter.
        _status, body = call(self.app, '/connect/?device=00:14:03:05:59:17')
        self.assertNotIn('refused', body)
        # Nach dem Stop ist der Wechsel frei.
        call(self.app, '/stopp/')
        _status, body = call(self.app, '/connect/?device=' + SIM)
        self.assertNotIn('refused', body)


class RecorderTest(_NoFakeEnv):

    def setUp(self):
        _NoFakeEnv.setUp(self)
        self.tmp = tempfile.mkdtemp()
        self.state = AppState()
        self.state.set_measurement(12.3, 45.6)
        self.state.set_position(51.4385, 6.7882)
        self.state.mark_gps_fix()
        self.recorder = None
        self._saved_post = recorder_module.post_json
        self.posts = []

        def fake_post(url, body, headers, timeout=30):
            self.posts.append(body)
            return 201
        recorder_module.post_json = fake_post

    def tearDown(self):
        self.state.shutdown()
        if self.recorder is not None:
            self.recorder.join(5)
        recorder_module.post_json = self._saved_post
        shutil.rmtree(self.tmp, ignore_errors=True)
        _NoFakeEnv.tearDown(self)

    def run_mode(self, flag, device):
        self.state.set_device(device, u'')
        self.recorder = Recorder(self.state, outdir=self.tmp, record_interval=0.1,
                                 tick=0.02, stat_interval=60)
        self.recorder.start()
        setattr(self.state, flag, True)
        deadline = time.time() + 3
        while time.time() < deadline and not os.listdir(self.tmp):
            self.state.set_measurement(12.3, 45.6)
            time.sleep(0.05)
        time.sleep(0.2)
        setattr(self.state, flag, False)
        time.sleep(0.2)
        return sorted(os.listdir(self.tmp))

    def test_sim_files_are_marked(self):
        names = self.run_mode('recording', SIM)
        self.assertTrue(names)
        for name in names:
            self.assertTrue(name.startswith('feinstaub_sim_'), names)
        self.assertTrue(any(name.endswith('.kml') for name in names), names)

    def test_real_files_are_not_marked(self):
        names = self.run_mode('local', '00:14:03:05:59:17')
        self.assertTrue(names)
        for name in names:
            self.assertFalse('sim_' in name, names)

    def test_sim_never_uploads(self):
        """Letzte Sicherung im Recorder, falls der stationaere Modus doch
        mit simuliertem Sensor laeuft (etwa von einer veralteten Seite)."""
        names = self.run_mode('stationary', SIM)
        self.assertEqual(self.posts, [])
        info = self.state.upload_info()
        self.assertFalse(info['last_ok'])
        self.assertIn(u'Simulierter Sensor', info['last_message'])
        self.assertTrue(all(name.startswith('feinstaub_sim_') for name in names), names)

    def test_real_sensor_uploads(self):
        self.run_mode('stationary', '00:14:03:05:59:17')
        self.assertGreaterEqual(len(self.posts), 1)


if __name__ == '__main__':
    unittest.main()
