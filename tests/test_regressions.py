# -*- coding: utf-8 -*-
"""Regressionstests fuer die Fehler aus Phase 1.

Jeder Test hier ist an einen konkreten Bug der alten Fassung gebunden
und soll verhindern, dass er zurueckkommt.
"""

from __future__ import absolute_import

import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_python(code):
    """Fuehrt Code in einem frischen Interpreter im Repo-Verzeichnis aus."""
    env = dict(os.environ)
    env['SDS011_FAKE'] = '1'
    proc = subprocess.Popen([sys.executable, '-c', code], cwd=REPO,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env)
    out, err = proc.communicate()
    return proc.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


class NoCircularImportTest(unittest.TestCase):
    """Frueher: kml.py machte 'from main import write_log', main.py
    machte 'import kml'. Beim Start als __main__ wurde main.py ein
    zweites Mal als Modul 'main' geladen -- mit eigenem Satz Globals,
    so dass Fehlermeldungen aus kml.py das Frontend nie erreichten."""

    def test_kml_does_not_pull_in_main(self):
        code = 'import kml, sys; print("main" in sys.modules)'
        rc, out, err = run_python(code)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), 'False')

    def test_main_module_body_runs_once(self):
        code = ('import main, sys\n'
                'mods = [m for m in sys.modules if m in ("main", "__main__")]\n'
                'print(len(mods))')
        rc, out, err = run_python(code)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), '2')  # nur 'main' und '__main__' selbst


class NoRunNameCollisionTest(unittest.TestCase):
    """Frueher: 'from bottle import run' ueberschrieb die globale
    Aufzeichnungs-Flagge 'run = False' mit bottles run-Funktion. Die
    war truthy, also lief 'while run:' sofort los -- ohne Klick auf
    Start."""

    def test_main_has_no_module_level_run_flag(self):
        import main
        run_attr = getattr(main, 'run', None)
        # Wenn es 'run' ueberhaupt gibt, darf es keine Flagge sein.
        self.assertFalse(isinstance(run_attr, bool))

    def test_fresh_state_does_not_record(self):
        from state import AppState
        self.assertIs(AppState().recording, False)
        self.assertIs(AppState().stationary, False)

    def test_recorder_writes_nothing_before_start(self):
        """Der Kern des Bugs: ohne Klick darf keine Datei entstehen."""
        import time
        from state import AppState
        from recorder import Recorder

        tmp = tempfile.mkdtemp()
        state = AppState()
        recorder = Recorder(state, outdir=tmp, kml_interval=0.01, tick=0.01)
        recorder.start()
        time.sleep(0.4)
        state.shutdown()
        recorder.join(5)

        self.assertEqual(os.listdir(tmp), [],
                         'Aufzeichnung lief ohne Start-Klick an')

    def test_recorder_writes_after_start(self):
        import time
        from state import AppState
        from recorder import Recorder

        tmp = tempfile.mkdtemp()
        state = AppState()
        state.set_position(51.4385, 6.7882)
        state.mark_gps_fix()
        state.set_measurement(12.3, 45.6)
        recorder = Recorder(state, outdir=tmp, kml_interval=0.01, tick=0.01)
        recorder.start()
        state.recording = True
        time.sleep(0.4)
        state.shutdown()
        recorder.join(5)

        files = sorted(os.listdir(tmp))
        self.assertEqual(len(files), 3, files)
        self.assertTrue(any(f.endswith('.csv') for f in files))
        self.assertEqual(len([f for f in files if f.endswith('.kml')]), 2)


class _LoggingIsolated(unittest.TestCase):
    """Stellt die globale Logging-Konfiguration wieder her, damit die
    Tests unabhaengig von ihrer Reihenfolge laufen."""

    def setUp(self):
        import logging_util
        self._saved = (logging_util._logfile, logging_util.get_level())
        handle, self.logpath = tempfile.mkstemp()
        os.close(handle)
        logging_util.configure(logfile=self.logpath, level=3)

    def tearDown(self):
        import logging_util
        logging_util.configure(logfile=self._saved[0], level=self._saved[1])
        try:
            os.remove(self.logpath)
        except OSError:
            pass


class LoggingDoesNotSetErrorTest(_LoggingIsolated):
    """Frueher: write_log() setzte bei JEDER Meldung error_msg, also
    stand im roten Fehlerkasten des Frontends zuletzt 'Connected' oder
    'HALLO GPS!' statt eines echten Fehlers."""

    def test_write_log_leaves_state_error_empty(self):
        import logging_util
        from state import AppState

        state = AppState()
        logging_util.write_log(1, 'Verbinde mit Feinstaubsensor...')
        logging_util.write_log(0, 'irgendein Betriebshinweis')
        self.assertEqual(state.error(), u'')

        state.report_error(u'echter Fehler')
        self.assertEqual(state.error(), u'echter Fehler')
        state.clear_error()
        self.assertEqual(state.error(), u'')

    def test_write_log_never_raises(self):
        import logging_util
        logging_util.configure(logfile=os.path.join('gibts', 'nicht.txt'))
        logging_util.write_log(0, 'darf nicht knallen')
        logging_util.configure(logfile=self.logpath)


class ExceptionHandlingTest(_LoggingIsolated):
    """Frueher: write_log(0, "..." + e) -- str + Exception gibt einen
    TypeError, der Fehlerpfad crashte an sich selbst."""

    def test_log_accepts_exception_object(self):
        import logging_util
        logging_util.write_log(0, ValueError(u'kaputt'))
        logging_util.write_log(0, Exception())
        with open(self.logpath) as fh:
            self.assertIn('kaputt', fh.read())

    def test_to_text_handles_bytes_and_objects(self):
        from logging_util import to_text
        self.assertEqual(to_text(b'abc'), u'abc')
        self.assertEqual(to_text(u'abc'), u'abc')
        self.assertEqual(to_text(123), u'123')
        self.assertEqual(to_text(b'\xc3\xa4'), u'\xe4')


if __name__ == '__main__':
    unittest.main()


class KmlClosedPromptlyTest(unittest.TestCase):
    """Die README verspricht: Stop druecken -> gueltige KML-Datei.
    Also muss der Stop-Klick die Dateien zeitnah abschliessen und nicht
    erst nach dem naechsten Messintervall."""

    def test_files_closed_shortly_after_stop(self):
        import time
        from xml.etree import ElementTree
        from state import AppState
        from recorder import Recorder

        tmp = tempfile.mkdtemp()
        state = AppState()
        state.set_position(51.4385, 6.7882)
        state.mark_gps_fix()
        state.set_measurement(10.0, 20.0)
        # Messintervall 1 s, Stop-Reaktion soll deutlich schneller sein.
        recorder = Recorder(state, outdir=tmp, kml_interval=1.0, tick=0.02)
        recorder.start()
        state.recording = True
        time.sleep(1.2)                 # ein Messwert wird geschrieben
        kmls = [f for f in os.listdir(tmp) if f.endswith('.kml')]
        self.assertEqual(len(kmls), 2, os.listdir(tmp))

        state.recording = False
        time.sleep(0.2)                 # << 1 s Messintervall
        for name in kmls:
            with open(os.path.join(tmp, name), 'rb') as handle:
                # Wirft, solange </kml> fehlt.
                ElementTree.parse(handle)

        state.shutdown()
        recorder.join(5)

    def test_no_measurement_means_no_kml_file(self):
        """Start und sofort Stopp darf keine Datei mit nur schliessenden
        Tags hinterlassen."""
        import time
        from state import AppState
        from recorder import Recorder

        tmp = tempfile.mkdtemp()
        state = AppState()
        recorder = Recorder(state, outdir=tmp, kml_interval=10.0, tick=0.02)
        recorder.start()
        state.recording = True
        time.sleep(0.1)
        state.recording = False
        time.sleep(0.2)
        state.shutdown()
        recorder.join(5)

        self.assertEqual(os.listdir(tmp), [], os.listdir(tmp))


class WaitRecordingTest(unittest.TestCase):
    """_wait_in_mode() gegen eine Fake-Uhr -- deterministisch, ohne
    echte Wartezeit."""

    class FakeClock(object):
        def __init__(self, overhead=0.0):
            self.t = 1000.0
            self.overhead = overhead
            self.waits = 0

        def now(self):
            return self.t

        def wait(self, seconds):
            # Jeder echte Event.wait() kostet etwas mehr als angefordert.
            self.t += seconds + self.overhead
            self.waits += 1
            return False

    class FakeState(object):
        def __init__(self, clock, recording=True):
            self.recording = recording
            self.local = False
            self.stationary = False
            self.sensing = True
            self.clock = clock

        def wait(self, seconds):
            return self.clock.wait(seconds)

    def _recorder(self, state, tick):
        from recorder import Recorder
        rec = Recorder.__new__(Recorder)     # ohne Thread-Setup
        rec._state = state
        rec._tick = tick
        return rec

    def test_interval_does_not_drift_with_timer_overhead(self):
        """Frueher wurden nominale Schritte heruntergezaehlt, so dass
        sich der Timer-Overhead aufaddierte: aus 5 s wurden 7 s."""
        import recorder
        clock = self.FakeClock(overhead=0.015)   # Windows-Granularitaet
        state = self.FakeState(clock)
        rec = self._recorder(state, tick=0.02)

        saved = recorder._now
        recorder._now = clock.now
        try:
            start = clock.now()
            aborted = rec._wait_in_mode(5.0, recorder.MODE_TRIP)
        finally:
            recorder._now = saved

        elapsed = clock.now() - start
        self.assertFalse(aborted)
        # Hoechstens ein Tick plus Overhead ueber dem Sollwert.
        self.assertLess(elapsed, 5.0 + 0.02 + 0.015 + 1e-9,
                        'Messintervall driftet: %.3f statt 5.0' % elapsed)
        self.assertGreaterEqual(elapsed, 5.0)

    def test_returns_early_on_stop(self):
        import recorder
        clock = self.FakeClock()
        state = self.FakeState(clock)
        rec = self._recorder(state, tick=0.1)

        original_wait = state.wait

        def stop_after_three(seconds):
            result = original_wait(seconds)
            if clock.waits >= 3:
                state.recording = False
            return result

        state.wait = stop_after_three

        saved = recorder._now
        recorder._now = clock.now
        try:
            self.assertTrue(rec._wait_in_mode(60.0, recorder.MODE_TRIP))
        finally:
            recorder._now = saved
        # Nicht die vollen 60 s abgewartet.
        self.assertLess(clock.now() - 1000.0, 1.0)
