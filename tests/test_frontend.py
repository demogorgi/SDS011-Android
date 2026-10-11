# -*- coding: utf-8 -*-
"""Statische Pruefungen an Template, Stylesheet und Skript der Oberflaeche.

Ein Browser laeuft hier nicht (das macht test_frontend_browser.py), aber
viele Fehler sind statisch sichtbar: externe Ressourcen, die unterwegs
ohne Netz fehlen, Routen, die es im Backend nicht gibt, und JavaScript,
das das alte Android-WebView in QPython nicht versteht.
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
SCRIPT = os.path.join(config.STATICDIR, 'app.js')
STYLE = os.path.join(config.STATICDIR, 'app.css')

# Die Elemente, an denen Skript und Browsertests haengen.
REQUIRED_IDS = (
    'connectBtn', 'disconnectBtn', 'deviceSelect', 'connStatus',
    'errorBanner', 'pm25Value', 'pm10Value', 'pm25Level', 'pm10Level',
    'liveAge', 'gpsStatus', 'gpsCoords', 'chart', 'rangeSelect',
    'intervalSelect', 'modeTrip', 'modeLocal', 'modeStat', 'placeInput',
    'startBtn', 'stopBtn', 'sessionPanel', 'sessionElapsed',
    'sessionPoints', 'sessionAvg25', 'sessionAvg10', 'sessionFile',
    'uploadInfo', 'toast',
)


def read_text(path):
    with io.open(path, encoding='utf-8') as handle:
        return handle.read()


def strip_js_comments(source):
    """Kommentare entfernen, damit deutsche Erklaerungen wie "let" oder
    "=>" in einem Kommentar die Syntaxpruefung nicht ausloesen. Grob,
    aber app.js hat keine Strings mit // oder /*."""
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'(^|[^:\\])//[^\n]*', r'\1', source)


def strip_css_comments(source):
    return re.sub(r'/\*.*?\*/', '', source, flags=re.S)


def render_template(**extra):
    """Das Template so rendern, wie es die Route '/' tut."""
    from bottle import template

    import webapp

    values = {'xsensor': config.XSENSOR, 'outdir': config.OUTDIR,
              'links': config.LINKS, 'open_external': False}
    values.update(extra)
    return template('index.html', template_lookup=webapp.TEMPLATE_LOOKUP, **values)


class TagCollector(HTMLParser):

    def __init__(self):
        try:
            HTMLParser.__init__(self, convert_charrefs=True)
        except TypeError:              # Python 2 kennt convert_charrefs nicht
            HTMLParser.__init__(self)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class SearchMixin(object):
    """assertRegex gibt es erst ab Python 3.2 (in 2.7 heisst es
    assertRegexpMatches); deshalb ein eigenes, das in beiden laeuft."""

    def assert_search(self, text, pattern, msg=None):
        if re.search(pattern, text) is None:
            self.fail(msg or 'nicht gefunden: %s' % pattern)


def collect_tags(html):
    parser = TagCollector()
    parser.feed(html)
    return parser.tags


class TemplateTest(SearchMixin, unittest.TestCase):

    def setUp(self):
        self.html = read_text(TEMPLATE)
        self.tags = collect_tags(self.html)
        self.script = read_text(SCRIPT)

    def _ids(self):
        return {a['id'] for t, a in self.tags if a.get('id')}

    # -- Ressourcen ----------------------------------------------------
    def test_viewport_meta(self):
        """Ohne viewport rechnet das Handy mit 980 px Breite; die alte
        Seite hat das mit font-size 2em ausgeglichen."""
        metas = [a for t, a in self.tags if t == 'meta' and a.get('name') == 'viewport']
        self.assertEqual(len(metas), 1, 'viewport-meta fehlt')
        content = metas[0].get('content', '').replace(' ', '')
        self.assertIn('width=device-width', content)
        self.assertIn('initial-scale=1', content)

    def test_no_external_resources(self):
        """Alles lokal: auf dem Fahrrad gibt es kein zuverlaessiges Netz.
        Links (<a href>) sind erlaubt, geladene Ressourcen nicht."""
        for tag, attrs in self.tags:
            if tag in ('iframe', 'embed', 'object'):
                self.fail('eingebettete Fremdseite: <%s>' % tag)
            for key in ('src', 'href'):
                value = attrs.get(key) or ''
                if tag == 'a' and key == 'href':
                    continue
                self.assertFalse(re.match(r'(https?:)?//', value),
                                 'externe Ressource in <%s>: %s' % (tag, value))
        for name in (SCRIPT, STYLE):
            text = read_text(name)
            self.assertNotIn('@import', text)
            self.assertIsNone(re.search(r'url\(\s*["\']?(https?:)?//', text),
                              'externe url() in %s' % os.path.basename(name))

    def test_no_libraries_left(self):
        """Ziel ist Vanilla-ES5: jQuery und Chart.js sind raus."""
        lowered = self.html.lower()
        for name in ('jquery', 'chart.min.js', 'chart.js'):
            self.assertNotIn(name, lowered)

    def test_no_stylesheet_loaded_as_script(self):
        for tag, attrs in self.tags:
            if tag == 'script' and attrs.get('src'):
                self.assertFalse(attrs['src'].endswith('.css'),
                                 'CSS als <script>: %s' % attrs['src'])

    def test_referenced_static_files_exist(self):
        refs = set()
        for _tag, attrs in self.tags:
            for key in ('src', 'href'):
                value = attrs.get(key) or ''
                if value.startswith('/static/'):
                    refs.add(value[len('/static/'):])
        self.assertIn('app.js', refs)
        self.assertIn('app.css', refs)
        for name in refs:
            self.assertTrue(os.path.exists(os.path.join(config.STATICDIR, name)),
                            'fehlt in static/: %s' % name)

    def test_no_orphaned_static_files(self):
        """Umgekehrte Richtung: nichts in static/ soll unbenutzt
        herumliegen (frueher lag dort ein 244 KB grosses jquery.mobile-CSS
        ohne das zugehoerige Skript)."""
        for name in os.listdir(config.STATICDIR):
            self.assertIn('/static/' + name, self.html,
                          'unbenutzte Datei in static/: %s' % name)

    def test_template_renders_with_intervals(self):
        """So ruft die Route '/' das Template auf: ein Knopf je Intervall."""
        html = render_template(intervals=(5, 10, 30, 60, 300, 900))
        found = re.findall(r'data-seconds="(\d+)"[^>]*>([^<]*)<', html)
        self.assertEqual([int(s) for s, _ in found], [5, 10, 30, 60, 300, 900])
        self.assertEqual([label for _, label in found],
                         ['5 s', '10 s', '30 s', '1 min', '5 min', '15 min'])
        self.assertIn(config.XSENSOR, html)

    def test_template_renders_without_intervals(self):
        """Fehlt intervals, darf das Template nicht mit NameError
        abbrechen -- dann baut das Skript die Knoepfe aus /status/."""
        html = render_template()
        self.assertNotIn('data-seconds=', html)
        self.assertIn('id="intervalSelect"', html)

    # -- Element-IDs ---------------------------------------------------
    def test_required_ids_exist(self):
        ids = self._ids()
        for name in REQUIRED_IDS:
            self.assertIn(name, ids, 'Element fehlt: %s' % name)

    def test_required_ids_are_used_by_script(self):
        for name in REQUIRED_IDS:
            self.assertTrue("'%s'" % name in self.script,
                            'Element nie angesprochen: %s' % name)

    def test_ids_are_unique(self):
        ids = [a['id'] for t, a in self.tags if a.get('id')]
        doubles = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(doubles, [])

    def test_script_ids_exist_in_template(self):
        """Umgekehrt: jedes byId('...') im Skript muss es geben, sonst
        wirft es im Browser beim ersten Zugriff."""
        ids = self._ids()
        for name in set(re.findall(r"byId\('([A-Za-z0-9_]+)'\)", self.script)):
            self.assertIn(name, ids, 'app.js sucht ein Element, das fehlt: %s' % name)

    def test_buttons_are_real_buttons(self):
        """Knoepfe sind <button> mit disabled, keine <div>: an einem div
        hat disabled keine sichtbare Wirkung, und die Tastatur erreicht
        es nicht."""
        by_id = {a['id']: t for t, a in self.tags if a.get('id')}
        for name in ('connectBtn', 'disconnectBtn', 'startBtn', 'stopBtn'):
            self.assertEqual(by_id[name], 'button', '%s ist kein <button>' % name)
        for tag, attrs in self.tags:
            if tag == 'button':
                self.assertEqual(attrs.get('type'), 'button',
                                 '<button> ohne type="button": %s' % attrs)

    def test_range_buttons(self):
        ranges = [a.get('data-range') for t, a in self.tags
                  if t == 'button' and 'data-range' in a]
        self.assertEqual(ranges, ['600', '3600', '21600', '0'])

    def test_mode_cards_are_radios(self):
        """Die drei Moduskarten verhalten sich wie Radioknoepfe."""
        radios = [a.get('value') for t, a in self.tags
                  if t == 'input' and a.get('type') == 'radio' and a.get('name') == 'mode']
        self.assertEqual(radios, ['trip', 'local', 'stat'])

    def test_inputs_have_labels(self):
        labelled = {a.get('for') for t, a in self.tags if t == 'label' and a.get('for')}
        for name in ('placeInput', 'deviceSelect'):
            self.assertIn(name, labelled, 'Eingabe ohne <label for>: %s' % name)

    def test_live_regions(self):
        """Live-Werte und Meldungen werden Screenreadern angesagt."""
        self.assert_search(self.html, r'class="tiles"[^>]*aria-live="polite"')
        self.assert_search(self.html, r'id="toast"[^>]*aria-live="polite"')
        self.assert_search(self.html, r'id="errorBanner"[^>]*role="alert"')

    def test_upload_warning_names_sensor(self):
        """Der stationaere Modus laedt oeffentlich hoch -- der Hinweis
        nennt Ziel und Sensor-ID."""
        match = re.search(r'id="statWarn".*?</div>', self.html, re.S)
        self.assertIsNotNone(match)
        self.assertIn('sensor.community', match.group(0))
        self.assertIn('{{xsensor}}', match.group(0))

    def test_info_links(self):
        """Die Links kommen aus config.LINKS und tragen data-link, damit
        app.js sie unter Android ueber /open/ im Browser oeffnen kann --
        das WebView von QPython ignoriert target="_blank"."""
        html = render_template()
        self.assertIn(config.LINKS['karte'], html)
        self.assertIn(config.LINKS['uba'], html)
        self.assertIn('{{outdir}}', self.html)
        for tag, attrs in self.tags:
            if tag == 'a' and attrs.get('target') == '_blank':
                self.assertIn(attrs.get('data-link'), config.LINKS,
                              'externer Link ohne data-link: %s' % attrs.get('href'))

    def test_map_link_at_stationary_mode(self):
        """Die Karte gehoert zum stationaeren Modus: im Hinweis vor dem
        Start und in der Upload-Anzeige waehrend der Messung."""
        for block in ('statWarn', 'uploadInfo'):
            match = re.search(r'id="%s".*?data-link="karte"' % block, self.html, re.S)
            self.assertIsNotNone(match, 'Kartenlink fehlt in #%s' % block)

    def test_open_external_flag(self):
        self.assertIn('data-open-external="0"', render_template(open_external=False))
        self.assertIn('data-open-external="1"', render_template(open_external=True))

    def test_level_explanation_matches_kml_level(self):
        """Die Tabelle "Was bedeuten die Stufen?" nennt dieselben
        Schwellen, nach denen kml.level() einstuft."""
        import kml

        match = re.search(r'id="levelsInfo".*?</details>', self.html, re.S)
        self.assertIsNotNone(match)
        table = match.group(0)
        for text in ('unter 25', 'unter 40', '25 bis 50', '40 bis 50', 'ab 50'):
            self.assertIn(text, table)
        self.assertIn('data-link="uba"', table)
        self.assertEqual(kml.level(24.9, 'pm_25'), 'good')
        self.assertEqual(kml.level(25, 'pm_25'), 'elevated')
        self.assertEqual(kml.level(39.9, 'pm_10'), 'good')
        self.assertEqual(kml.level(40, 'pm_10'), 'elevated')
        self.assertEqual(kml.level(50, 'pm_25'), 'high')
        self.assertEqual(kml.level(50, 'pm_10'), 'high')

    def test_favicon_is_the_brand_mark(self):
        self.assertIn('href="/static/favicon.svg"', self.html)


class ScriptTest(SearchMixin, unittest.TestCase):
    """app.js muss im alten Android-WebView laufen: ES5, keine Bibliothek."""

    def setUp(self):
        self.raw = read_text(SCRIPT)
        self.code = strip_js_comments(self.raw)

    def test_es5_only(self):
        forbidden = [
            (r'=>', 'Pfeilfunktion'),
            (r'\blet\s+[A-Za-z_$]', 'let'),
            (r'\bconst\s+[A-Za-z_$]', 'const'),
            (r'`', 'Template-String'),
            (r'\bfetch\s*\(', 'fetch'),
            (r'\bPromise\b', 'Promise'),
            (r'\basync\s+function\b|\bawait\s', 'async/await'),
            (r'\bclass\s+[A-Za-z_$][\w$]*\s*(extends\b|\{)', 'class'),
            (r'\.includes\s*\(', 'includes'),
            (r'\.find(Index)?\s*\(', 'find'),
            (r'Object\.assign', 'Object.assign'),
            (r'\.closest\s*\(', 'Element.closest'),
            (r'\.\.\.[A-Za-z_$\[]', 'Spread'),
        ]
        for pattern, what in forbidden:
            match = re.search(pattern, self.code)
            self.assertIsNone(match, '%s in app.js: %r' % (
                what, match and self.code[max(0, match.start() - 30):match.end() + 30]))

    def test_uses_xmlhttprequest(self):
        self.assertIn('new XMLHttpRequest()', self.code)

    def test_no_library_globals(self):
        self.assertIsNone(re.search(r'\$\(|jQuery|\bChart\b', self.code))

    def test_script_root_is_relative(self):
        """Leerer Praefix: die Seite passt zu jeder Adresse und jedem Port
        des Servers. Eine feste localhost-URL waere von anderen Geraeten
        aus nicht erreichbar."""
        match = re.search(r"SCRIPT_ROOT\s*=\s*'([^']*)'", self.code)
        self.assertIsNotNone(match, 'SCRIPT_ROOT nicht gefunden')
        self.assertEqual(match.group(1), '')
        self.assertNotIn('localhost', self.code)
        self.assertNotIn('127.0.0.1', self.code)

    def test_status_poll_is_fixed_and_single(self):
        """Statusabfrage fest alle 2 s ueber eine einzige setTimeout-Kette.
        Frueher startete jede Aenderung der Rate eine weitere Kette."""
        self.assert_search(self.code, r'POLL_MS\s*=\s*2000')
        self.assertIn('clearTimeout(pollTimer)', self.code)
        self.assertNotIn('setInterval(poll', self.code)
        self.assertEqual(len(re.findall(r'\bsetInterval\(', self.code)), 1,
                         'mehr als ein setInterval -- stapeln sich Timer?')

    def test_uses_status_fields(self):
        """Die Felder aus /status/, auf denen die Anzeige beruht."""
        for field in ('value', 'lat', 'lon', 'gps_available', 'gps_age',
                      'gps_max_age', 'pm_10', 'pm_25', 'error_msg', 'recording',
                      'local', 'stationary', 'place', 'connection',
                      'connection_error', 'connection_wanted', 'device',
                      'device_name', 'interval', 'intervals', 'measurement_age',
                      'pm_25_level', 'history_rev', 'next_point_in', 'session',
                      'upload', 'outdir', 'stat_interval'):
            pattern = r"(data|last|status)\.%s\b|'%s'" % (field, field)
            self.assert_search(self.code, pattern, '/status/-Feld unbenutzt: %s' % field)

    def test_all_called_routes_exist(self):
        """Jede Route, die app.js aufruft, muss es im Backend geben.

        Gefunden werden alle String-Literale, die mit '/' beginnen
        ('/status/', '/connect/?device=', '/chart.svg?range=' ...); der
        Query-Teil wird abgeschnitten."""
        import webapp
        from state import AppState

        app = webapp.create_app(AppState())
        known = {route.rule for route in app.routes}
        called = set()
        for literal in re.findall(r"'(/[^'\s]*)'", self.code):
            called.add(literal.split('?')[0])
        self.assertTrue(called, 'keine Routen in app.js gefunden')
        for path in ('/status/', '/devices/', '/connect/', '/disconnect/',
                     '/interval/', '/chart.svg', '/start/', '/stopp/',
                     '/localon/', '/localoff/', '/staton/', '/statoff/'):
            self.assertIn(path, called, 'app.js ruft %s nicht auf' % path)
        missing = sorted(path for path in called if path not in known)
        self.assertEqual(missing, [], 'Routen fehlen im Backend: %s' % missing)

    def test_chart_is_inlined_not_img(self):
        """Das SVG wird als innerHTML eingesetzt, nicht per <img>: nur so
        greifen die --pmc-*-Farben der Seite (hell/dunkel)."""
        self.assertIn('innerHTML = markup', self.code)
        self.assertNotIn('<img', read_text(TEMPLATE))

    def test_chart_reloads_on_connection_change(self):
        """Die Meldung im leeren Diagramm haengt an der Verbindung
        ("Kein Sensor verbunden"). Ohne sie im Schluessel stuende sie nach
        dem Verbinden bis zu einer Minute lang weiter da. Nur ja/nein,
        sonst laedt jeder Zwischenzustand ("verbinde" ...) neu."""
        match = re.search(r'function updateChart\(.*?var key = \[(.*?)\]\.join',
                          self.code, re.S)
        self.assertIsNotNone(match, 'Schluessel in updateChart nicht gefunden')
        parts = match.group(1)
        for field in ('chart.range', 'history_rev', 'status.interval'):
            self.assertIn(field, parts)
        self.assert_search(parts, r"status\.connection\s*===\s*'verbunden'\s*\?\s*1\s*:\s*0")

    def test_place_not_overwritten_while_typing(self):
        self.assert_search(self.code, r'document\.activeElement\s*!==\s*place')

    def test_storage_is_guarded(self):
        """localStorage kann im WebView fehlen oder werfen."""
        for match in re.finditer(r'localStorage\.\w+\(', self.code):
            before = self.code[max(0, match.start() - 80):match.start()]
            self.assertIn('try', before, 'localStorage ohne try/catch')


class StyleTest(SearchMixin, unittest.TestCase):

    def setUp(self):
        self.css = strip_css_comments(read_text(STYLE))

    def test_no_grid_and_no_flex_gap(self):
        """Das alte WebView kennt weder CSS grid noch gap bei flexbox."""
        self.assertIsNone(re.search(r'display\s*:\s*(inline-)?grid', self.css))
        self.assertIsNone(re.search(r'(^|[\s;{])(row-|column-)?gap\s*:', self.css))

    def test_chart_variables_for_both_themes(self):
        """Das Server-SVG liest diese Variablen; beide Themes setzen sie."""
        names = ('--pmc-bg', '--pmc-text', '--pmc-muted', '--pmc-grid',
                 '--pmc-pm25', '--pmc-pm10', '--pmc-rec', '--pmc-warn', '--pmc-bad')
        light = re.search(r'@media\s*\(prefers-color-scheme:\s*light\)\s*\{(.*?)\n\}',
                          self.css, re.S)
        self.assertIsNotNone(light, 'kein helles Theme')
        dark = self.css[:light.start()]
        for name in names:
            self.assert_search(dark, re.escape(name) + r'\s*:', 'dunkel ohne %s' % name)
            self.assert_search(light.group(1), re.escape(name) + r'\s*:', 'hell ohne %s' % name)

    def test_series_colors_differ_from_traffic_light(self):
        """PM2.5/PM10 duerfen nicht wie gut/erhoeht/hoch aussehen."""
        def value(name, block):
            match = re.search(re.escape(name) + r'\s*:\s*(#[0-9a-fA-F]{6})', block)
            return match.group(1).lower() if match else None

        light = re.search(r'@media\s*\(prefers-color-scheme:\s*light\)', self.css)
        for block in (self.css[:light.start()], self.css[light.start():]):
            series = {value('--pmc-pm25', block), value('--pmc-pm10', block)}
            status = {value('--good', self.css), value('--pmc-warn', block),
                          value('--pmc-bad', block)}
            self.assertEqual(len(series), 2)
            self.assertFalse(series & status)

    def test_hidden_attribute_wins(self):
        """Das Skript blendet ueber das hidden-Attribut aus; display:flex
        an .btn darf das nicht aushebeln."""
        self.assert_search(self.css, r'\[hidden\]\s*\{\s*display\s*:\s*none\s*!important')

    def test_touch_targets(self):
        """Knoepfe und Segmente mindestens 44 px hoch."""
        for selector in (r'\.btn', r'\.seg button', r'\.icon-btn'):
            block = re.search(r'(^|\n)' + selector + r'\s*\{([^}]*)\}', self.css)
            self.assertIsNotNone(block, selector)
            height = re.search(r'(min-)?height\s*:\s*(\d+)px', block.group(2))
            self.assertIsNotNone(height, selector)
            self.assertGreaterEqual(int(height.group(2)), 44, selector)

    def test_disabled_and_focus_states(self):
        self.assert_search(self.css, r'\.btn:disabled\s*\{[^}]*opacity')
        self.assertIn(':focus-visible', self.css)
        self.assert_search(self.css, r'\.btn:focus[^{]*\{[^}]*outline:\s*2px')


if __name__ == '__main__':
    unittest.main()
