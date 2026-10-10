# -*- coding: utf-8 -*-
"""Statische Pruefungen am Template.

Ein Browser laeuft hier nicht, aber die Fehler der alten Fassung waren
alle statisch sichtbar: eine undefinierte Variable im setInterval, ein
Stylesheet als <script>, eine fest verdrahtete localhost-URL.
"""

from __future__ import absolute_import

import io
import os
import re
import unittest

try:                                   # Python 3
    from html.parser import HTMLParser
except ImportError:                    # Python 2
    from HTMLParser import HTMLParser

import config

TEMPLATE = os.path.join(config.TEMPLATEDIR, 'index.html')


def read_template():
    with io.open(TEMPLATE, encoding='utf-8') as handle:
        return handle.read()


class TagCollector(HTMLParser):

    def __init__(self):
        try:
            HTMLParser.__init__(self, convert_charrefs=True)
        except TypeError:              # Python 2 kennt convert_charrefs nicht
            HTMLParser.__init__(self)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class TemplateTest(unittest.TestCase):

    def setUp(self):
        self.html = read_template()
        parser = TagCollector()
        parser.feed(self.html)
        self.tags = parser.tags

    # -- Skripte und Stylesheets --------------------------------------
    def test_no_external_resources(self):
        """Alles lokal: auf dem Fahrrad gibt es kein zuverlaessiges Netz,
        und http:// von googleapis ist ausserdem Mixed Content."""
        scripts = [a.get('src') for t, a in self.tags
                   if t == 'script' and a.get('src')]
        for src in scripts:
            self.assertFalse(src.startswith('http'),
                             'externes Skript: %s' % src)

    def test_jquery_loaded_once(self):
        scripts = [a.get('src', '') for t, a in self.tags if t == 'script']
        jquery = [s for s in scripts if 'jquery' in s.lower()]
        self.assertEqual(len(jquery), 1, jquery)

    def test_no_stylesheet_loaded_as_script(self):
        for tag, attrs in self.tags:
            if tag == 'script' and attrs.get('src'):
                self.assertFalse(attrs['src'].endswith('.css'),
                                 'CSS als <script>: %s' % attrs['src'])

    def test_referenced_static_files_exist(self):
        refs = set()
        for _tag, attrs in self.tags:
            for key in ('src', 'href'):
                value = attrs.get(key, '')
                if value.startswith('/static/'):
                    refs.add(value[len('/static/'):])
        self.assertTrue(refs, 'keine statischen Dateien referenziert')
        for name in refs:
            self.assertTrue(os.path.exists(os.path.join(config.STATICDIR, name)),
                            'fehlt in static/: %s' % name)

    def test_no_orphaned_static_files(self):
        """Umgekehrte Richtung: nichts in static/ soll unbenutzt
        herumliegen. jquery.mobile-1.4.5.css lag 244 KB gross da, ohne
        dass das zugehoerige JS ueberhaupt im Repo war."""
        for name in os.listdir(config.STATICDIR):
            self.assertIn(name, self.html,
                          'unbenutzte Datei in static/: %s' % name)

    # -- JavaScript-Fehler der alten Fassung --------------------------
    def test_no_undefined_data_in_setinterval(self):
        """Frueher: setInterval(... data.pm_10 ...) -- 'data' gibt es in
        dem Scope nicht, das warf alle 3 Sekunden einen ReferenceError."""
        for match in re.finditer(r'setInterval\(([^;]*?)\}\s*,', self.html,
                                 re.S):
            body = match.group(1)
            self.assertNotIn('data.pm_', body,
                             'setInterval greift auf undefiniertes data zu')

    def test_script_root_is_relative(self):
        match = re.search(r"\$SCRIPT_ROOT\s*=\s*'([^']*)'", self.html)
        self.assertIsNotNone(match, '$SCRIPT_ROOT nicht gefunden')
        self.assertEqual(match.group(1), '',
                         'fest verdrahtete URL: von anderen Geraeten nicht erreichbar')

    def test_chart_window_is_bounded(self):
        """Ohne Begrenzung waechst der Chart unbegrenzt -- bei 1 Sekunde
        Aktualisierungsrate 3600 Punkte pro Stunde."""
        self.assertIn('MAX_POINTS', self.html)
        self.assertIn('.shift()', self.html)

    # -- Vertrag zum Backend ------------------------------------------
    def test_uses_all_status_fields(self):
        """Jeder Schluessel aus /status/ soll auch benutzt werden."""
        for field in ('value', 'lat', 'lon', 'pm_10', 'pm_10_color',
                      'pm_25', 'pm_25_color', 'error_msg',
                      'recording', 'stationary'):
            self.assertIn('data.' + field, self.html,
                          '/status/-Feld unbenutzt: %s' % field)

    def test_all_called_routes_exist(self):
        """Jede im Template aufgerufene Route muss es im Backend geben."""
        import webapp
        from state import AppState

        app = webapp.create_app(AppState())
        known = {route.rule for route in app.routes}
        # Query-String abschneiden: /connect/?device= ist die Route /connect/
        called = {path.split('?')[0] for path in
                     re.findall(r'\$SCRIPT_ROOT \+ "([^"]+)"', self.html)}
        self.assertTrue(called, 'keine Routen im Template gefunden')
        for path in called:
            self.assertIn(path, known, 'Route fehlt im Backend: %s' % path)

    def test_button_ids_are_wired(self):
        # Ueber den geparsten Baum, nicht per Regex -- im Template
        # kommen einfache und doppelte Anfuehrungszeichen vor.
        ids = {a['id'] for t, a in self.tags if a.get('id')}
        for name in ('startBtn', 'stoppBtn', 'startStatBtn', 'stoppStatBtn',
                     'refreshBtn', 'echopm_10', 'echopm_25', 'echolat',
                     'echolon', 'echoerror'):
            self.assertIn(name, ids, 'Element fehlt: %s' % name)
            self.assertIn('#' + name, self.html, 'Element nie angesprochen: %s' % name)


if __name__ == '__main__':
    unittest.main()
