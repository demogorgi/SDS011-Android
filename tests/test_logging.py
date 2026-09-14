# -*- coding: utf-8 -*-
"""Tests fuer Logrotation und Koordinatenformat."""

from __future__ import absolute_import

import io
import os
import shutil
import tempfile
import unittest

import logging_util
from recorder import _coord


class RotateLogfileTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'logfile.txt')
        self.saved = (logging_util._logfile, logging_util.get_level())
        logging_util.configure(logfile=self.path, level=3)

    def tearDown(self):
        logging_util.configure(logfile=self.saved[0], level=self.saved[1])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self, path):
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def test_previous_path(self):
        self.assertEqual(logging_util.previous_logfile('/a/logfile.txt'),
                         '/a/logfile.1.txt')
        self.assertEqual(logging_util.previous_logfile('log'), 'log.1')

    def test_rotate_keeps_previous_run(self):
        """Frueher wurde beim Start geloescht -- das Log der Messfahrt
        war nach dem Neustart weg."""
        logging_util.write_log(0, 'lauf eins')
        logging_util.rotate_logfile()
        logging_util.write_log(0, 'lauf zwei')

        previous = logging_util.previous_logfile(self.path)
        self.assertTrue(os.path.exists(previous))
        self.assertIn('lauf eins', self._read(previous))
        self.assertIn('lauf zwei', self._read(self.path))
        self.assertNotIn('lauf eins', self._read(self.path))

    def test_rotate_keeps_only_one_generation(self):
        for run in range(4):
            logging_util.rotate_logfile()
            logging_util.write_log(0, 'lauf %d' % run)
        files = sorted(os.listdir(self.tmp))
        self.assertEqual(files, ['logfile.1.txt', 'logfile.txt'], files)
        self.assertIn('lauf 3', self._read(self.path))
        self.assertIn('lauf 2', self._read(logging_util.previous_logfile(self.path)))

    def test_rotate_without_existing_log_does_nothing(self):
        logging_util.rotate_logfile()
        self.assertEqual(os.listdir(self.tmp), [])

    def test_rotate_never_raises(self):
        logging_util.configure(logfile=os.path.join(self.tmp, 'x', 'y.txt'))
        logging_util.rotate_logfile()


class CoordinateFormatTest(unittest.TestCase):

    def test_no_float_noise(self):
        """str(51.4385 + 0.0002 * 3) liefert 51.439099999999996."""
        value = 51.4385 + 0.0002 * 3
        self.assertIn('99999', str(value))
        self.assertEqual(_coord(value), '51.439100')

    def test_precision_is_six_decimals(self):
        self.assertEqual(_coord(6.7882), '6.788200')
        self.assertEqual(_coord(0.0), '0.000000')
        self.assertEqual(_coord(-51.4385), '-51.438500')

    def test_survives_csv_decimal_replacement(self):
        # write_csv ersetzt Punkt durch Komma.
        self.assertEqual(_coord(51.4385).replace('.', ','), '51,438500')


if __name__ == '__main__':
    unittest.main()
