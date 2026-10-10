# -*- coding: utf-8 -*-
"""Tests fuer die lokale Messung.

Der Punkt dieses Modus: an einem Ort messen und mitschreiben, ohne
GPS-Spur und vor allem ohne irgendetwas hochzuladen. Der Upload zu
luftdaten.info passiert ausschliesslich im stationaeren Modus.
"""

from __future__ import absolute_import

import io
import os
import shutil
import tempfile
import time
import unittest

from recorder import Recorder, slugify
from state import AppState


class SlugifyTest(unittest.TestCase):

    def test_plain_text(self):
        self.assertEqual(slugify('Kletterhalle'), 'kletterhalle')

    def test_spaces_become_underscores(self):
        self.assertEqual(slugify('Kletterhalle Duisburg'), 'kletterhalle_duisburg')

    def test_umlauts(self):
        self.assertEqual(slugify(u'B\xfcro'), 'buero')
        self.assertEqual(slugify(u'K\xfcche'), 'kueche')
        self.assertEqual(slugify(u'Gr\xf6\xdfe'), 'groesse')

    def test_unsafe_characters_are_dropped(self):
        """Der Wert landet in einem Dateinamen -- nichts darf dort
        Unfug anrichten."""
        for text in (u'../../etc/passwd', u'a\\b', u'a/b', u'a:b', u'a*b',
                     u'a?b', u'a"b', u'a<b', u'a|b'):
            slug = slugify(text)
            for bad in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
                self.assertNotIn(bad, slug, '%r ergab %r' % (text, slug))
        self.assertNotIn('..', slugify(u'../../etc/passwd'))

    def test_empty_and_useless_input(self):
        self.assertEqual(slugify(''), '')
        self.assertEqual(slugify('   '), '')
        self.assertEqual(slugify('!!!'), '')
        self.assertEqual(slugify(None), '')

    def test_length_is_capped(self):
        self.assertLessEqual(len(slugify('x' * 200)), 40)

    def test_no_double_underscores(self):
        self.assertNotIn('__', slugify(u'a   -   b'))


class LocalRecordingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = AppState()
        self.state.set_measurement(12.3, 45.6)
        self.state.set_position(51.4385, 6.7882)
        self.state.mark_gps_fix()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_mode(self, local, place=u'', seconds=0.4):
        self.state.set_place(place)
        recorder = Recorder(self.state, outdir=self.tmp,
                            kml_interval=0.05, tick=0.01)
        recorder.start()
        if local:
            self.state.local = True
        else:
            self.state.recording = True
        time.sleep(seconds)
        self.state.shutdown()
        recorder.join(5)
        return sorted(os.listdir(self.tmp))

    def test_local_writes_csv_only(self):
        """Eine KML-Spur aus lauter gleichen Punkten waere nutzlos."""
        files = self._run_mode(local=True, place=u'Kletterhalle')
        self.assertEqual(len(files), 1, files)
        self.assertTrue(files[0].endswith('.csv'))

    def test_place_lands_in_filename(self):
        files = self._run_mode(local=True, place=u'Kletterhalle Duisburg')
        self.assertIn('kletterhalle_duisburg', files[0])

    def test_without_place_a_neutral_name_is_used(self):
        files = self._run_mode(local=True, place=u'')
        self.assertIn('lokal', files[0])

    def test_csv_has_measurements(self):
        files = self._run_mode(local=True, place=u'Buero')
        with io.open(os.path.join(self.tmp, files[0]), encoding='utf-8') as fh:
            rows = [r for r in fh.read().splitlines() if r]
        self.assertTrue(rows)
        self.assertIn('12,3', rows[0])
        self.assertIn('45,6', rows[0])

    def test_trip_still_writes_kml(self):
        """Die Messfahrt bleibt unveraendert: zwei KML plus CSV."""
        files = self._run_mode(local=False)
        self.assertEqual(len(files), 3, files)
        self.assertEqual(len([f for f in files if f.endswith('.kml')]), 2)

    def test_local_does_not_need_gps(self):
        """Am Laptop gibt es keine Position -- das darf die Messung
        nicht verhindern."""
        self.state.set_position(0, 0)
        files = self._run_mode(local=True, place=u'Halle')
        self.assertEqual(len(files), 1, files)
        with io.open(os.path.join(self.tmp, files[0]), encoding='utf-8') as fh:
            self.assertTrue(fh.read().strip())

    def test_nothing_before_start(self):
        recorder = Recorder(self.state, outdir=self.tmp,
                            kml_interval=0.05, tick=0.01)
        recorder.start()
        time.sleep(0.2)
        self.state.shutdown()
        recorder.join(5)
        self.assertEqual(os.listdir(self.tmp), [])


class NoUploadTest(unittest.TestCase):
    """Die Zusage, auf die es ankommt."""

    def test_push_step_is_not_reached_while_local(self):
        calls = []
        state = AppState()
        recorder = Recorder(state, outdir=tempfile.mkdtemp(),
                            kml_interval=0.05, tick=0.01)
        recorder._push_step = lambda: calls.append(1)
        recorder.start()
        state.local = True
        time.sleep(0.4)
        state.shutdown()
        recorder.join(5)
        self.assertEqual(calls, [], 'lokale Messung hat hochgeladen')

    def test_push_step_is_not_reached_while_recording(self):
        calls = []
        state = AppState()
        recorder = Recorder(state, outdir=tempfile.mkdtemp(),
                            kml_interval=0.05, tick=0.01)
        recorder._push_step = lambda: calls.append(1)
        recorder.start()
        state.recording = True
        time.sleep(0.4)
        state.shutdown()
        recorder.join(5)
        self.assertEqual(calls, [], 'Messfahrt hat hochgeladen')

    def test_push_step_runs_in_stationary(self):
        """Gegenprobe: im stationaeren Modus muss es passieren."""
        calls = []
        state = AppState()
        recorder = Recorder(state, outdir=tempfile.mkdtemp(),
                            kml_interval=0.05, tick=0.01, stat_interval=0.05)
        recorder._push_step = lambda: calls.append(1)
        recorder.start()
        state.stationary = True
        time.sleep(0.4)
        state.shutdown()
        recorder.join(5)
        self.assertTrue(calls, 'stationaerer Modus hat nicht hochgeladen')


if __name__ == '__main__':
    unittest.main()
