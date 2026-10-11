# -*- coding: utf-8 -*-
"""Wohin die Aufzeichnungen geschrieben werden."""

from __future__ import absolute_import

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ChooseOutdirTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Ein gesetztes SDS011_OUTDIR ginge allem vor; die Tests hier
        # pruefen die Wahl ohne. Von Hand statt mock.patch.dict: mock
        # gehoert unter Python 2 nicht zur Standardbibliothek.
        self._saved = os.environ.pop('SDS011_OUTDIR', None)

    def tearDown(self):
        os.environ.pop('SDS011_OUTDIR', None)
        if self._saved is not None:
            os.environ['SDS011_OUTDIR'] = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_android_uses_download_folder(self):
        target = os.path.join(self.tmp, 'Download', 'Feinstaub')
        self.assertEqual(config.choose_outdir(android=True, preferred=target),
                         target)
        self.assertTrue(os.path.isdir(target))
        # Die Probedatei wird wieder weggeraeumt.
        self.assertEqual(os.listdir(target), [])

    def test_unwritable_falls_back_to_output(self):
        # Eine Datei, wo ein Verzeichnis sein muesste -- scheitert auf
        # jeder Plattform, anders als Rechte unter Windows.
        blocker = os.path.join(self.tmp, 'blocker')
        open(blocker, 'w').close()
        target = os.path.join(blocker, 'Feinstaub')
        self.assertEqual(config.choose_outdir(android=True, preferred=target),
                         config.FALLBACK_OUTDIR)

    def test_desktop_keeps_output(self):
        self.assertEqual(config.choose_outdir(android=False, preferred=self.tmp),
                         config.FALLBACK_OUTDIR)

    def test_environment_overrides_everything(self):
        """SDS011_OUTDIR geht vor: am PC statt output/, unter Android
        statt Download/Feinstaub. So schreibt ein Testlauf nicht in die
        echten Aufzeichnungen und Einstellungen."""
        target = os.path.join(self.tmp, 'eigenes')
        os.environ['SDS011_OUTDIR'] = target
        android_dir = os.path.join(self.tmp, 'Download', 'Feinstaub')
        self.assertEqual(config.choose_outdir(android=False), target)
        self.assertEqual(config.choose_outdir(android=True, preferred=android_dir),
                         target)
        # Die Android-Pruefung laeuft gar nicht erst (sie legte das
        # Verzeichnis an).
        self.assertFalse(os.path.exists(android_dir))

    def test_relative_override_becomes_absolute(self):
        os.environ['SDS011_OUTDIR'] = 'relativ'
        self.assertEqual(config.choose_outdir(android=False),
                         os.path.abspath('relativ'))

    def test_empty_override_is_ignored(self):
        os.environ['SDS011_OUTDIR'] = ''
        self.assertEqual(config.choose_outdir(android=False), config.FALLBACK_OUTDIR)

    def test_override_moves_log_and_settings(self):
        """OUTDIR wird beim Import festgelegt; Log und Einstellungen
        haengen daran. Eigener Prozess, damit config hier unberuehrt
        bleibt."""
        target = os.path.join(self.tmp, 'eigenes')
        env = dict(os.environ, SDS011_OUTDIR=target)
        code = ('import config; print(config.OUTDIR); print(config.LOGFILE); '
                'print(config.SETTINGS_FILE)')
        proc = subprocess.Popen([sys.executable, '-c', code], cwd=REPO, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        self.assertEqual(proc.returncode, 0, err)
        outdir, logfile, settings_file = out.decode('utf-8').splitlines()
        self.assertEqual(outdir, target)
        self.assertEqual(logfile, os.path.join(target, 'logfile.txt'))
        self.assertEqual(settings_file, os.path.join(target, 'einstellungen.json'))

    def test_settings_live_next_to_the_recordings(self):
        """Auf dem Handy mit jedem Dateimanager erreichbar, wie das Log."""
        self.assertEqual(os.path.dirname(config.SETTINGS_FILE), config.OUTDIR)
        self.assertEqual(os.path.dirname(config.LOGFILE), config.OUTDIR)


if __name__ == '__main__':
    unittest.main()
