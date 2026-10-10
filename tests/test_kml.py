# -*- coding: utf-8 -*-
"""Tests fuer Farbwahl und Dateiausgabe."""

from __future__ import absolute_import

import io
import os
import shutil
import tempfile
import unittest
from xml.etree import ElementTree

import kml


class ColorSelectionTest(unittest.TestCase):

    def test_returns_string_over_full_range(self):
        value = -50.0
        while value <= 200.0:
            self.assertTrue(kml.color_selection(value).startswith('#'))
            value += 0.5

    def test_negative_does_not_raise(self):
        # Lief frueher in einen UnboundLocalError, weil die if/elif-Kette
        # keinen else-Zweig hatte.
        self.assertTrue(kml.color_selection(-1.0).startswith('#'))
        self.assertTrue(kml.color_selection_rgb(-1.0, 'pm_10').startswith('#'))
        self.assertTrue(kml.color_selection_rgb(-1.0, 'pm_25').startswith('#'))

    def test_unknown_pm_kind(self):
        self.assertTrue(kml.color_selection_rgb(10.0, 'pm_99').startswith('#'))

    def test_pm10_thresholds(self):
        self.assertEqual(kml.color_selection_rgb(39.9, 'pm_10'), '#2bef0d')
        self.assertEqual(kml.color_selection_rgb(40.0, 'pm_10'), '#FF7814')
        self.assertEqual(kml.color_selection_rgb(50.0, 'pm_10'), '#F00014')

    def test_pm25_thresholds(self):
        self.assertEqual(kml.color_selection_rgb(24.9, 'pm_25'), '#2bef0d')
        self.assertEqual(kml.color_selection_rgb(25.0, 'pm_25'), '#FF7814')
        self.assertEqual(kml.color_selection_rgb(50.0, 'pm_25'), '#F00014')
        # Der Sensor liefert Zehntel: 49,5 liegt noch im orangen Bereich.
        self.assertEqual(kml.color_selection_rgb(49.5, 'pm_25'), '#FF7814')


class FileOutputTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_track(self, name='track.kml', points=3):
        path = os.path.join(self.tmp, name)
        for i in range(points):
            kml.write_kml_line('12.3', '11.0', '6.78', '51.43',
                               '51.4%d' % i, '6.7%d' % i, '2026-01-01 10:00:00',
                               path, '25', '#C800FF00')
        kml.close_kml(path)
        return path

    def test_kml_is_well_formed_xml(self):
        path = self._write_track()
        # Faellt hier eine ParseError, ist die Datei in Google Earth wertlos.
        with io.open(path, 'rb') as handle:
            root = ElementTree.parse(handle).getroot()
        self.assertTrue(root.tag.endswith('kml'))

    def test_kml_has_placemarks(self):
        path = self._write_track(points=4)
        with io.open(path, encoding='utf-8') as handle:
            text = handle.read()
        # Jeder Messwert ergibt ein Placemark. Frueher legte der erste
        # Aufruf nur den Kopf an und verwarf den Messwert.
        self.assertEqual(text.count('<Placemark>'), 4)
        self.assertEqual(text.count('<Document>'), 1)
        self.assertTrue(text.rstrip().endswith('</kml>'))

    def test_kml_uses_unix_line_endings(self):
        path = self._write_track()
        with io.open(path, 'rb') as handle:
            self.assertNotIn(b'\r\n', handle.read())

    def test_csv_format(self):
        path = os.path.join(self.tmp, 'out.csv')
        kml.write_csv('12.3', '45.6', '51.4385', '6.7882',
                      '2026-01-01 10:00:00', path)
        with io.open(path, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        # Dezimaltrenner wird auf Komma umgestellt (deutsches Excel).
        self.assertEqual(lines, ['Zeit;PM2.5;PM10;Breite;Laenge',
                                 '2026-01-01 10:00:00;12,3;45,6;51,4385;6,7882'])

    def test_csv_header_only_once(self):
        path = os.path.join(self.tmp, 'out.csv')
        for _ in range(3):
            kml.write_csv('1.0', '2.0', '', '', 't', path)
        with io.open(path, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines[0], kml.CSV_HEADER)
        self.assertEqual(len(lines), 4)
        self.assertNotIn(kml.CSV_HEADER, lines[1:])

    def test_close_kml_on_missing_dir_does_not_raise(self):
        # Fehler beim Schreiben duerfen die Messung nicht abbrechen.
        kml.close_kml(os.path.join(self.tmp, 'gibtsnicht', 'x.kml'))


if __name__ == '__main__':
    unittest.main()


class CloseKmlEdgeCaseTest(unittest.TestCase):
    """Start und Stopp vor dem ersten Messwert."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_close_without_any_measurement_creates_no_file(self):
        path = os.path.join(self.tmp, 'leer.kml')
        self.assertFalse(kml.close_kml(path))
        self.assertFalse(os.path.exists(path),
                         'close_kml hat eine Datei mit nur schliessenden Tags angelegt')

    def test_first_measurement_is_not_lost(self):
        """Ein einziger Messwert muss als Placemark in der Datei landen."""
        path = os.path.join(self.tmp, 'einer.kml')
        kml.write_kml_line('12.3', '12.3', '6.7882', '51.4385',
                           '51.4385', '6.7882', '2026-01-01 10:00:00',
                           path, '25', '#C800FF00')
        self.assertTrue(kml.close_kml(path))
        with io.open(path, encoding='utf-8') as handle:
            text = handle.read()
        self.assertEqual(text.count('<Placemark>'), 1)
        self.assertIn('12.3', text)
        with io.open(path, 'rb') as handle:
            ElementTree.parse(handle)

    def test_close_after_single_line_is_valid_xml(self):
        path = os.path.join(self.tmp, 'kopf.kml')
        kml.write_kml_line('1.0', '1.0', '6.7', '51.4', '51.4', '6.7',
                           '2026-01-01 10:00:00', path, '25', '#C800FF00')
        self.assertTrue(kml.close_kml(path))
        with io.open(path, 'rb') as handle:
            ElementTree.parse(handle)


class RepairUnclosedTest(unittest.TestCase):
    """Nach einem harten Abbruch fehlt der KML-Abschluss -- beim naechsten
    Start wird er nachgetragen."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _trip(self, name, points):
        path = os.path.join(self.tmp, name)
        for i in range(points):
            kml.write_kml_line('1%d.0' % i, '10.0', '6.78', '51.43', '51.4%d' % i,
                               '6.7%d' % i, 'x', path, '25', '#FF00FF00')
        return path

    def _placemarks(self, path):
        root = ElementTree.parse(path).getroot()
        return root.findall('.//{http://earth.google.com/kml/2.1}Placemark')

    def test_unclosed_file_becomes_valid(self):
        path = self._trip('a.kml', 2)
        self.assertEqual(kml.repair_unclosed_kml(self.tmp), ['a.kml'])
        self.assertEqual(len(self._placemarks(path)), 2)

    def test_half_written_placemark_is_cut_off(self):
        path = self._trip('a.kml', 2)
        with io.open(path, 'ab') as fh:
            fh.write(b'   <Placemark>\n   <name>99.0</name>\n    <Poi')
        kml.repair_unclosed_kml(self.tmp)
        self.assertEqual(len(self._placemarks(path)), 2)

    def test_header_only_becomes_an_empty_document(self):
        path = os.path.join(self.tmp, 'a.kml')
        kml._write_kml_header(path, '25')
        kml.repair_unclosed_kml(self.tmp)
        self.assertEqual(self._placemarks(path), [])

    def test_closed_files_are_left_alone(self):
        path = self._trip('a.kml', 1)
        kml.close_kml(path)
        with io.open(path, 'rb') as fh:
            before = fh.read()
        self.assertEqual(kml.repair_unclosed_kml(self.tmp), [])
        with io.open(path, 'rb') as fh:
            self.assertEqual(fh.read(), before)

    def test_other_files_are_ignored(self):
        csv = os.path.join(self.tmp, 'a.csv')
        with io.open(csv, 'w', encoding='utf-8') as fh:
            fh.write(u'x;1,0;2,0;;\n')
        self.assertEqual(kml.repair_unclosed_kml(self.tmp), [])

    def test_missing_directory_is_no_error(self):
        self.assertEqual(kml.repair_unclosed_kml(os.path.join(self.tmp, 'fehlt')), [])
