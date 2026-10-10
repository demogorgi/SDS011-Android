# -*- coding: utf-8 -*-
"""Recorder: Takt, Moduswechsel, veraltete Messwerte, Schreibfehler.

Laufen mit echten Threads, aber kurzen Intervallen.
"""

from __future__ import absolute_import

import glob
import io
import os
import shutil
import tempfile
import time
import tokenize
import unittest

import config
import kml
import recorder as recorder_module
from recorder import Recorder
from state import AppState, monotonic


def _csv_rows(directory):
    rows = []
    for name in sorted(os.listdir(directory)):
        if name.endswith('.csv'):
            with io.open(os.path.join(directory, name), encoding='utf-8') as fh:
                rows.extend(r for r in fh.read().splitlines() if r)
    return rows


def _wait_for(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class RecorderTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = AppState()
        self.state.set_measurement(12.3, 45.6)
        self.state.set_position(51.4385, 6.7882)
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

    def start(self, **kwargs):
        options = {'outdir': self.tmp, 'kml_interval': 0.3, 'tick': 0.02}
        options.update(kwargs)
        self.recorder = Recorder(self.state, **options)
        self.recorder.start()
        return self.recorder


class IntervalTest(RecorderTestCase):

    def test_local_mode_keeps_the_interval(self):
        """Die lokale Messung schrieb jeden Tick (0,5 s) eine Zeile statt
        alle KML_INT (5 s) -- zehnmal zu viele, fast nur Duplikate."""
        self.start()
        self.state.local = True
        time.sleep(1.05)
        self.state.local = False
        rows = _csv_rows(self.tmp)
        # 1,05 s bei 0,3 s Intervall: drei Zeilen. Vorher waren es ~50.
        self.assertGreaterEqual(len(rows), 2, rows)
        self.assertLessEqual(len(rows), 4, rows)


class StaleMeasurementTest(RecorderTestCase):

    def test_stale_value_is_not_recorded(self):
        """Nach einem Verbindungsabbruch bleibt der letzte Wert stehen --
        er darf nicht als frische Messung in die Datei."""
        self.state.set_measurement(12.3, 45.6, at=monotonic() - 100)
        self.start(max_age=10)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        self.assertEqual(_csv_rows(self.tmp), [])

        # Kommen wieder Werte, wird wieder geschrieben und der Hinweis
        # verschwindet.
        self.state.set_measurement(20.0, 30.0)
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp)))
        self.assertEqual(self.state.error(), u'')

    def test_missing_value_is_not_recorded(self):
        """Direkt nach dem Verbinden ist noch kein Paket da -- dann darf
        keine Zeile mit 0,0 entstehen."""
        self.state = AppState()
        self.state.set_position(51.4385, 6.7882)
        self.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        time.sleep(0.4)
        self.assertEqual(_csv_rows(self.tmp), [])

    def test_track_restarts_after_a_gap(self):
        """Nach einem Ausfall keine gerade Linie ueber die ganze Luecke."""
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._open_files(local=False)
        rec._record_step()
        self.assertIsNotNone(rec._lat_old)
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        rec._record_step()
        self.assertIsNone(rec._lat_old)

    def test_clock_set_back_counts_as_stale(self):
        """Unter Python 2 ist monotonic nur time.time -- eine
        zurueckgestellte Uhr darf einen alten Wert nicht frisch machen."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() + 100)
        self.assertIsNone(self.state.measurement_age())

    def test_hint_disappears_after_stop(self):
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.start(max_age=10)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: self.state.error()))
        self.state.local = False
        self.assertTrue(_wait_for(lambda: self.state.error() == u''))

    def test_stale_value_is_not_uploaded(self):
        # Der alte Code lud hier den veralteten Wert hoch.
        self.state.set_measurement(12.3, 45.6, at=monotonic() - 100)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertFalse(rec._push_step())
        self.assertEqual(self.posts, [])
        self.assertIn(u'nichts hochgeladen', self.state.error())

    def test_fresh_value_is_uploaded(self):
        # Positivkontrolle: frische Werte gehen weiterhin raus.
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertTrue(rec._push_step())
        self.assertEqual(len(self.posts), 1)
        self.assertIn('"P1","value":"45.6"', self.posts[0])
        self.assertIn('"P2","value":"12.3"', self.posts[0])

    def test_upload_errors_are_not_cleared_by_fresh_values(self):
        """Der Recorder raeumt nur seine eigenen Hinweise weg."""
        self.state.report_error(u'Verbindung zum Sensor verloren')
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._fresh_measurement(u'nichts aufgezeichnet')
        self.assertEqual(self.state.error(), u'Verbindung zum Sensor verloren')


class ModeSwitchTest(RecorderTestCase):

    def test_trip_starts_promptly_after_stationary(self):
        """Der stationaere Modus wartete STAT_INT (240 s) am Stueck --
        eine danach gestartete Messfahrt begann erst Minuten spaeter."""
        self.start(stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: self.posts))
        self.state.stationary = False
        self.state.recording = True
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp), timeout=2.0),
                        'Messfahrt hat nach 2 s noch nichts geschrieben')

    def test_stationary_retries_soon_without_value(self):
        """Ohne aktuellen Wert nicht STAT_INT warten, sondern bald neu
        versuchen -- sonst kommt der erste Upload erst nach 4 Minuten."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.start(stat_interval=60, max_age=10)
        self.state.stationary = True
        time.sleep(0.2)
        self.assertEqual(self.posts, [])
        self.state.set_measurement(3.0, 4.0)
        self.assertTrue(_wait_for(lambda: self.posts, timeout=2.0))

    def test_switch_without_stop_gets_new_files(self):
        """Lokal -> Messfahrt ohne Stop schrieb die Fahrt in die
        lokale CSV, ohne KML."""
        self.state.set_place(u'Halle')
        self.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp)))
        # Reihenfolge wie in /start/: recording zuerst, local danach --
        # der Recorder sieht also direkt LOCAL -> TRIP.
        self.state.recording = True
        self.state.local = False

        def done():
            files = os.listdir(self.tmp)
            return (len([f for f in files if f.endswith('.csv')]) == 2
                    and len([f for f in files if f.endswith('.kml')]) == 2)
        self.assertTrue(_wait_for(done), os.listdir(self.tmp))

    def test_toggling_stationary_does_not_upload_more_often(self):
        """Aus- und wieder einschalten darf den Upload-Abstand nicht
        unterlaufen -- sonst geht bei jedem Klick ein Wert raus."""
        self.start(stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: self.posts))
        for _ in range(3):
            self.state.stationary = False
            time.sleep(0.1)
            self.state.stationary = True
            time.sleep(0.1)
        self.assertEqual(len(self.posts), 1)


class WriteErrorTest(RecorderTestCase):

    def test_write_error_does_not_kill_the_recorder(self):
        """Speicher voll o. ae.: der Thread starb still, die Oberflaeche
        zeigte weiter "aktiv"."""
        calls = []
        original = kml.write_csv

        def flaky(*args):
            calls.append(1)
            if len(calls) <= 3:
                raise IOError('No space left on device')
            return original(*args)

        kml.write_csv = flaky
        self.addCleanup(setattr, kml, 'write_csv', original)
        self.start(kml_interval=0.1)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Aufzeichnung gestört' in self.state.error()))
        self.assertTrue(self.recorder.is_alive())

        # Solange es scheitert, bleibt der Hinweis stehen -- er
        # verschwindet erst nach dem ersten gelungenen Schreiben.
        seen_empty_before_success = False
        deadline = time.time() + 3.0
        while time.time() < deadline and not _csv_rows(self.tmp):
            if self.state.error() == u'' and not _csv_rows(self.tmp):
                seen_empty_before_success = True
            time.sleep(0.005)
        self.assertTrue(_csv_rows(self.tmp))
        self.assertFalse(seen_empty_before_success)
        self.assertTrue(_wait_for(lambda: self.state.error() == u''))


class UnicodeFormatTest(unittest.TestCase):
    """Unter Python 2 wirft '...{0}'.format(u'Mülheim') einen
    UnicodeEncodeError -- /localon/ antwortete mit 500, sobald der Ort
    einen Umlaut hatte. Vorlagen fuer .format() deshalb immer u''.

    Ueber tokenize statt ast: das sieht das u-Praefix auf jeder
    Python-Version (ast erst ab 3.8)."""

    @staticmethod
    def _offenders(path):
        skip = (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                tokenize.INDENT, tokenize.DEDENT)
        with io.open(path, encoding='utf-8') as fh:
            tokens = [t for t in tokenize.generate_tokens(fh.readline)
                      if t[0] not in skip]
        found = []
        run = []
        run_start = 0
        for i, tok in enumerate(tokens):
            if tok[0] == tokenize.STRING:
                if not run:
                    run_start = i
                run.append(tok)
                continue
            # ('a' 'b').format(...): die Klammer gehoert zum Literal.
            if run and tok[1] == ')' and run_start > 0 and tokens[run_start - 1][1] == '(':
                continue
            if (run and tok[1] == '.' and i + 1 < len(tokens)
                    and tokens[i + 1][1] == 'format'):
                # Bei aneinandergehaengten Literalen genuegt ein u-Teil.
                prefixes = [t[1][:t[1].index(t[1][-1])].lower() for t in run]
                if not any('u' in prefix for prefix in prefixes):
                    found.append('%s:%d' % (os.path.basename(path), run[0][2][0]))
            run = []
        return found

    def test_detector_sees_byte_templates(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, 'probe.py')
        with io.open(path, 'w', encoding='utf-8') as fh:
            fh.write(u"a = '{0}'.format(1)\n"
                     u"b = u'{0}'.format(1)\n"
                     u"c = ('x'\n     u'{0}').format(1)\n"
                     u"d = ('x'\n     '{0}').format(1)\n")
        self.assertEqual(self._offenders(path), ['probe.py:1', 'probe.py:5'])

    def test_format_templates_are_unicode(self):
        offenders = []
        for name in sorted(glob.glob(os.path.join(config.BASEDIR, '*.py'))):
            offenders.extend(self._offenders(name))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
