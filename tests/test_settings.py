# -*- coding: utf-8 -*-
"""Gespeicherte Einstellungen (settings.py) und ihre Uebernahme beim
Start (main.apply_settings)."""

from __future__ import absolute_import

import io
import json
import os
import shutil
import tempfile
import unittest

import config
import settings
from state import AppState


class SettingsFileTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'einstellungen.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        with io.open(self.path, 'w', encoding='utf-8') as handle:
            handle.write(text)

    def test_missing_file_gives_empty_settings(self):
        self.assertEqual(settings.load(self.path), {})

    def test_save_and_load(self):
        self.assertTrue(settings.save({'record_interval': 30}, self.path))
        self.assertEqual(settings.load(self.path), {'record_interval': 30})
        with io.open(self.path, encoding='utf-8') as handle:
            self.assertEqual(json.loads(handle.read()), {'record_interval': 30})

    def test_save_replaces_and_leaves_no_temp_file(self):
        settings.save({'record_interval': 30}, self.path)
        self.assertTrue(settings.save({'record_interval': 60}, self.path))
        self.assertEqual(settings.load(self.path), {'record_interval': 60})
        self.assertEqual(os.listdir(self.tmp), ['einstellungen.json'])

    def test_save_without_os_replace(self):
        """Python 2 kennt os.replace nicht, und os.rename scheitert unter
        Windows an einem vorhandenen Ziel."""
        settings.save({'record_interval': 30}, self.path)
        saved = getattr(os, 'replace', None)
        if saved is not None:
            del os.replace
        try:
            self.assertTrue(settings.save({'record_interval': 900}, self.path))
        finally:
            if saved is not None:
                os.replace = saved
        self.assertEqual(settings.load(self.path), {'record_interval': 900})
        self.assertEqual(os.listdir(self.tmp), ['einstellungen.json'])

    def test_broken_file_gives_empty_settings(self):
        """Etwa halb geschrieben, als der Akku leer war."""
        self._write(u'{"record_interval": 3')
        self.assertEqual(settings.load(self.path), {})

    def test_wrong_content_gives_empty_settings(self):
        self._write(u'[30]')
        self.assertEqual(settings.load(self.path), {})

    def test_unwritable_place_is_no_exception(self):
        target = os.path.join(self.tmp, 'fehlt', 'einstellungen.json')
        self.assertFalse(settings.save({'record_interval': 30}, target))
        self.assertFalse(os.path.exists(os.path.dirname(target)))

    def test_umlauts_survive(self):
        settings.save({'ort': u'Küche'}, self.path)
        self.assertEqual(settings.load(self.path), {'ort': u'Küche'})

    def test_default_path_is_read_at_call_time(self):
        saved = config.SETTINGS_FILE
        config.SETTINGS_FILE = self.path
        try:
            settings.save({'record_interval': 10})
            self.assertEqual(settings.load(), {'record_interval': 10})
        finally:
            config.SETTINGS_FILE = saved
        self.assertTrue(os.path.exists(self.path))


class ApplySettingsTest(unittest.TestCase):
    """Beim Start: nur ein Intervall, das zur Wahl steht, wird uebernommen."""

    def _applied(self, stored):
        import main
        state = AppState(record_interval=config.RECORD_INT)
        main.apply_settings(state, stored)
        return state.record_interval()

    def test_valid_interval_is_used(self):
        self.assertEqual(self._applied({'record_interval': 300}), 300)

    def test_invalid_values_are_ignored(self):
        for value in (7, 0, -5, u'30', None, True, [30], 30.5):
            self.assertEqual(self._applied({'record_interval': value}),
                             config.RECORD_INT, value)

    def test_empty_settings(self):
        self.assertEqual(self._applied({}), config.RECORD_INT)


if __name__ == '__main__':
    unittest.main()
