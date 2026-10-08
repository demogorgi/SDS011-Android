# -*- coding: utf-8 -*-
"""Wohin die Aufzeichnungen geschrieben werden."""

from __future__ import absolute_import

import os
import shutil
import tempfile
import unittest

import config


class ChooseOutdirTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
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


if __name__ == '__main__':
    unittest.main()
