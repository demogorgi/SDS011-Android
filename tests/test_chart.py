# -*- coding: utf-8 -*-
"""Tests fuer das Verlaufsdiagramm (chart.render_svg und Helfer)."""

from __future__ import absolute_import, division

import calendar
import io
import os
import re
import time
import unittest
from xml.etree import ElementTree

import chart

NS = u'{http://www.w3.org/2000/svg}'
# Fester Zeitpunkt, damit die Tests nicht von der Uhr abhaengen.
NOW = 1760000000.0


def make_points(start, end, step, pm25=10.0, pm10=20.0, recorded=False):
    """Punkte (epoch, pm25, pm10, interval, recorded) von start bis end."""
    points = []
    t = start
    while t <= end:
        points.append((t, pm25, pm10, step, recorded))
        t += step
    return points


def parse(svg):
    return ElementTree.fromstring(svg.encode('utf-8'))


def by_class(root, tag, cls):
    """Alle Elemente tag, deren class-Attribut cls enthaelt."""
    return [el for el in root.iter(NS + tag)
            if cls in (el.get('class') or u'').split()]


def path_points(path):
    """Anzahl der Stuetzpunkte eines Pfads 'M.. L.. L..'."""
    return path.get('d').count(u'L') + 1


def texts(root):
    return [u''.join(el.itertext()) for el in root.iter(NS + 'text')]


def _last_sunday(year, month):
    """Tag des letzten Sonntags im Monat."""
    last = calendar.monthrange(year, month)[1]
    return last - (calendar.weekday(year, month, last) + 1) % 7


def _berlin_switch(year, month):
    """Zeitumstellung (EU-Regel): letzter Sonntag, 01:00 UTC."""
    return calendar.timegm((year, month, _last_sunday(year, month), 1, 0, 0))


def berlin_localtime(epoch):
    """time.localtime fuer Europe/Berlin (MEZ/MESZ), ohne time.tzset.

    tzset gibt es unter Windows nicht; so pruefen die Tests die
    Sommerzeit ueberall mit derselben Zeitzone.
    """
    year = time.gmtime(epoch).tm_year
    summer = _berlin_switch(year, 3) <= epoch < _berlin_switch(year, 10)
    return time.gmtime(epoch + (7200 if summer else 3600))


def axis_labels(root):
    """Beschriftungen der Zeitachse als Liste (x, Text)."""
    return [(float(el.get('x')), u''.join(el.itertext()))
            for el in by_class(root, 'text', 'pmc-axis')
            if el.get('text-anchor') == 'middle']


class RootTest(unittest.TestCase):

    def test_valid_xml_with_root_attributes(self):
        svg = chart.render_svg(make_points(NOW - 600, NOW, 5), NOW, width=360, height=220)
        self.assertIsInstance(svg, type(u''))
        root = parse(svg)
        self.assertEqual(root.tag, NS + 'svg')
        self.assertEqual(root.get('width'), u'360')
        self.assertEqual(root.get('height'), u'220')
        self.assertEqual(root.get('viewBox'), u'0 0 360 220')
        self.assertEqual(root.get('class'), u'pm-chart')
        self.assertEqual(root.get('role'), u'img')
        self.assertTrue(root.get('aria-label'))
        self.assertIsNotNone(root.find(NS + 'title'))

    def test_style_uses_theme_variables_with_fallback(self):
        root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5), NOW))
        style = root.find(NS + 'style').text
        for name in ('bg', 'text', 'muted', 'grid', 'pm25', 'pm10', 'rec', 'bad'):
            self.assertTrue(re.search(r'var\(--pmc-' + name + r',#[0-9a-f]{6}\)', style),
                            name)
        # Nur eigene Klassen, damit das eingesetzte <style> die Seite nicht trifft.
        selectors = re.findall(r'(?:^|\})([^{}]+)\{', style)
        for selector in selectors:
            for part in selector.split(','):
                self.assertTrue(part.strip().startswith(('.pmc-', '.pm-chart')), part)

    def test_no_project_imports(self):
        # chart.py muss allein laufen (webapp importiert es erst bei Bedarf).
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'chart.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        modules = re.findall(r'^(?:from|import) (\w+)', source, re.MULTILINE)
        self.assertEqual(set(modules), {'__future__', 'calendar', 'math', 're', 'time'})


class LinesTest(unittest.TestCase):

    def test_two_series_and_end_values(self):
        points = make_points(NOW - 600, NOW - 2, 5, pm25=12.34, pm10=25.0)
        root = parse(chart.render_svg(points, NOW))
        self.assertEqual(by_class(root, 'path', 'pmc-s25'), [])
        self.assertEqual(by_class(root, 'path', 'pmc-s10'), [])
        self.assertGreater(len(by_class(root, 'circle', 'pmc-f25')), 2)
        self.assertGreater(len(by_class(root, 'circle', 'pmc-f10')), 2)
        values = [u''.join(el.itertext()) for el in by_class(root, 'text', 'pmc-value')]
        self.assertEqual(sorted(values), [u'12,3', u'25,0'])
        self.assertEqual(len(by_class(root, 'circle', 'pmc-end')), 2)

    def test_gap_splits_segments(self):
        points = make_points(NOW - 900, NOW - 600, 5) + make_points(NOW - 300, NOW, 5)
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 2)

    def test_small_gap_does_not_split(self):
        # 12 s Abstand bei 5 s Intervall liegt unter 2.5 x 5 = 12.5 s.
        points = [(NOW - 100, 10.0, 20.0, 5, False), (NOW - 95, 10.0, 20.0, 5, False),
                  (NOW - 83, 10.0, 20.0, 5, False), (NOW - 78, 10.0, 20.0, 5, False)]
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 1)

    def test_gap_uses_interval_of_later_point(self):
        # Intervall auf 60 s umgestellt: 100 s Abstand ist dann keine Luecke.
        points = [(NOW - 200, 10.0, 20.0, 5, False), (NOW - 195, 10.0, 20.0, 5, False),
                  (NOW - 95, 10.0, 20.0, 60, False)]
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 1)
        points[2] = (NOW - 95, 10.0, 20.0, 5, False)
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 2)

    def test_gap_uses_interval_of_earlier_point(self):
        # Intervall von 15 min auf 5 s verkuerzt: der erste 5-s-Punkt kommt
        # erst 595 s nach dem letzten 900-s-Punkt. Das ist keine Luecke,
        # weder in der Linie noch im Band "gespeichert".
        points = (make_points(0, 1800, 900, recorded=True)
                  + make_points(2395, 2495, 5, recorded=True))
        segments = chart.split_segments(chart._clean(points, 5))
        self.assertEqual(len(segments), 1)
        self.assertEqual(chart.recorded_spans(segments), [(-900, 2495)])
        # Echte Luecke (laenger als 2.5 x 900 s) trennt weiterhin.
        points = (make_points(0, 1800, 900, recorded=True)
                  + make_points(4100, 4200, 5, recorded=True))
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 2)

    def test_single_point_is_circle(self):
        points = (make_points(NOW - 1800, NOW - 1500, 5)
                  + [(NOW - 1000, 10.0, 20.0, 5, False)]
                  + make_points(NOW - 300, NOW, 5))
        root = parse(chart.render_svg(points, NOW))
        dots = [el for el in by_class(root, 'circle', 'pmc-f25')
                if 'pmc-end' not in el.get('class')]
        # Alle Messpunkte sind Kreise; plus ein Kreis in der Legende.
        self.assertEqual(len(dots), len(points) + 1)

    def test_end_labels_do_not_overlap(self):
        points = make_points(NOW - 600, NOW, 5, pm25=20.0, pm10=20.2)
        root = parse(chart.render_svg(points, NOW, width=360, height=220))
        ys = sorted(float(el.get('y')) for el in by_class(root, 'text', 'pmc-value'))
        self.assertGreaterEqual(ys[1] - ys[0], 12)
        # PM10 (hoeherer Wert) oben.
        top = min(by_class(root, 'text', 'pmc-value'), key=lambda el: float(el.get('y')))
        self.assertEqual(u''.join(top.itertext()), u'20,2')

    def test_end_labels_stay_inside(self):
        points = make_points(NOW - 600, NOW, 5, pm25=0.0, pm10=0.0)
        root = parse(chart.render_svg(points, NOW, width=360, height=220))
        for el in by_class(root, 'text', 'pmc-value'):
            self.assertLess(float(el.get('y')), 220 - 24)
            self.assertGreater(float(el.get('y')), 0)

    def test_invalid_points_are_skipped(self):
        points = make_points(NOW - 300, NOW, 5)
        points.insert(3, (NOW - 280, None, 20.0, 5, False))
        points.insert(5, (NOW - 270, float('nan'), 20.0, 5, False))
        parse(chart.render_svg(points, NOW))

    def test_future_points_are_clamped(self):
        points = make_points(NOW - 300, NOW + 3, 5)
        root = parse(chart.render_svg(points, NOW, width=400))
        for el in by_class(root, 'circle', 'pmc-end'):
            self.assertLessEqual(float(el.get('cx')), 400)


class DownsamplingTest(unittest.TestCase):

    def test_render_uses_measured_points(self):
        points = make_points(NOW - 4320 * 5, NOW, 5)
        root = parse(chart.render_svg(points, NOW, range_s=0, width=400))
        dots = [el for el in by_class(root, 'circle', 'pmc-f25')
                if 'pmc-end' not in el.get('class')]
        # Alle Messpunkte plus ein Legendenpunkt; kein Bucket-Mittelwert.
        self.assertEqual(len(dots), len(points) + 1)

    def test_gaps_stay_gaps(self):
        points = (make_points(NOW - 21600, NOW - 12000, 5)
                  + make_points(NOW - 9000, NOW, 5))
        self.assertEqual(len(chart.split_segments(chart._clean(points, 5))), 2)

    def test_bucket_is_recorded_if_any_point_is(self):
        points = [(0.0, 10.0, 20.0, 5, False), (5.0, 12.0, 22.0, 5, True),
                  (10.0, 14.0, 24.0, 5, False), (15.0, 16.0, 26.0, 5, False)]
        result = chart.downsample([points], 0.0, 40.0, 2)
        self.assertEqual(len(result[0]), 1)
        epoch, pm25, pm10, interval, recorded = result[0][0]
        self.assertAlmostEqual(pm25, 13.0)
        self.assertAlmostEqual(pm10, 23.0)
        self.assertTrue(recorded)
        self.assertGreaterEqual(interval, 20.0)

    def test_few_points_untouched(self):
        points = make_points(0, 50, 5)
        self.assertEqual(chart.downsample([points], 0, 60, 100), [points])


class RecordedTest(unittest.TestCase):

    def test_band_for_recorded_section(self):
        points = (make_points(NOW - 1800, NOW - 1200, 5)
                  + make_points(NOW - 1195, NOW - 600, 5, recorded=True)
                  + make_points(NOW - 595, NOW, 5))
        root = parse(chart.render_svg(points, NOW, width=640))
        bands = [el for el in root.iter(NS + 'g') if el.get('class') == 'pmc-bands']
        self.assertEqual(len(bands), 1)
        rects = by_class(bands[0], 'rect', 'pmc-rec')
        self.assertEqual(len(rects), 1)
        self.assertIn(u'gespeichert', texts(root))

    def test_no_band_without_recorded_points(self):
        root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5), NOW))
        self.assertEqual([el for el in root.iter(NS + 'g')
                          if el.get('class') == 'pmc-bands'], [])
        # Die Legende nennt "gespeichert" trotzdem, damit sie nicht springt.
        self.assertIn(u'gespeichert', texts(root))

    def test_spans_split_at_unrecorded_points(self):
        points = (make_points(0, 20, 5, recorded=True) + make_points(25, 40, 5)
                  + make_points(45, 60, 5, recorded=True))
        self.assertEqual(chart.recorded_spans([points]), [(-5, 20), (40, 60)])


class ScaleTest(unittest.TestCase):

    def test_nice_step_is_1_2_5(self):
        self.assertEqual(chart.nice_step(0.7), 1.0)
        self.assertEqual(chart.nice_step(1.5), 2.0)
        self.assertEqual(chart.nice_step(3), 5.0)
        self.assertEqual(chart.nice_step(7), 10.0)
        self.assertEqual(chart.nice_step(20), 20.0)
        self.assertEqual(chart.nice_step(260), 500.0)

    def test_y_scale_minimum_and_headroom(self):
        top, step = chart.y_scale(0, 200)
        self.assertGreaterEqual(top, 10)
        top, step = chart.y_scale(89, 166)
        self.assertGreaterEqual(top, 89 * 1.15)
        self.assertIn(step / 10 ** int(len(str(int(step))) - 1), (1, 2, 5))
        self.assertAlmostEqual(top / (step / 2.0), round(top / (step / 2.0)))
        self.assertLessEqual(top, 89 * 1.15 + step / 2.0)

    def test_y_ticks_start_at_zero(self):
        root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5, 30.0, 60.0), NOW))
        labels = [u''.join(el.itertext()) for el in by_class(root, 'text', 'pmc-axis')
                  if el.get('text-anchor') == 'end']
        self.assertEqual(labels[0], u'0')
        numbers = [int(label) for label in labels]
        self.assertEqual(numbers, sorted(numbers))

    def test_reference_lines_only_inside_scale(self):
        def refs(pm10):
            root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5, 5.0, pm10), NOW))
            return sorted(cls for el in by_class(root, 'path', 'pmc-ref')
                          for cls in el.get('class').split() if cls != 'pmc-ref')
        self.assertEqual(refs(15.0), [])
        self.assertEqual(refs(23.0), ['pmc-ref25'])
        self.assertEqual(refs(60.0), ['pmc-ref25', 'pmc-ref40', 'pmc-ref50'])

    def test_reference_labels_do_not_collide(self):
        # Stark gestauchte Skala: 25/40/50 liegen dicht, Beschriftungen
        # duerfen sich nicht ueberlappen.
        root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5, 100.0, 400.0), NOW,
                                      width=360, height=220))
        ys = sorted(float(el.get('y')) for el in by_class(root, 'text', 'pmc-reflabel'))
        self.assertTrue(ys)
        for first, second in zip(ys, ys[1:]):
            self.assertGreaterEqual(second - first, 11)

    def test_reference_labels_above_their_line(self):
        # "hoch" gilt ab 50: die Beschriftung steht ueber der Linie, auch
        # wenn die Linie an der Oberkante liegt.
        for pm10 in (38.0, 60.0):
            root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5, 20.0, pm10), NOW,
                                          width=360, height=220))
            # d = "M<x> <y>H<x2>"
            lines = {el.get('class').split()[1]: float(el.get('d').split()[1].split('H')[0])
                     for el in by_class(root, 'path', 'pmc-ref')}
            labels = {u''.join(el.itertext()): float(el.get('y'))
                      for el in by_class(root, 'text', 'pmc-reflabel')}
            self.assertIn(u'hoch', labels)
            self.assertLess(labels[u'hoch'], lines['pmc-ref50'])
            if u'PM2.5 erhöht' in labels:
                self.assertLess(labels[u'PM2.5 erhöht'], lines['pmc-ref25'])

    def test_reference_label_avoids_data(self):
        # Messlinie laeuft links genau durch die Beschriftung von 25: sie
        # weicht nach rechts aus.
        points = (make_points(NOW - 600, NOW - 300, 5, 26.0, 26.2)
                  + make_points(NOW - 295, NOW, 5, 5.0, 8.0))
        root = parse(chart.render_svg(points, NOW, range_s=600, width=640, height=320))
        label = [el for el in by_class(root, 'text', 'pmc-reflabel')
                 if u''.join(el.itertext()) == u'PM2.5 erhöht'][0]
        self.assertGreater(float(label.get('x')), 320)


class TimeAxisTest(unittest.TestCase):

    def test_ticks_on_round_local_times(self):
        ticks = chart.time_ticks(NOW - 3600, NOW, 560)
        self.assertGreaterEqual(len(ticks), 3)
        epochs = [epoch for epoch, _ in ticks]
        self.assertEqual(epochs, sorted(epochs))
        steps = {int(round(b - a)) for a, b in zip(epochs, epochs[1:])}
        self.assertEqual(len(steps), 1)
        step = steps.pop()
        for epoch, label in ticks:
            self.assertTrue(NOW - 3600 <= epoch <= NOW)
            self.assertTrue(re.match(r'^\d\d:\d\d$', label), label)
            local = time.localtime(epoch)
            self.assertEqual(label, u'{0:02d}:{1:02d}'.format(local.tm_hour, local.tm_min))
            self.assertEqual((local.tm_min * 60 + local.tm_sec) % min(step, 3600), 0)

    def test_narrow_chart_has_fewer_ticks(self):
        wide = chart.time_ticks(NOW - 3600, NOW, 560)
        narrow = chart.time_ticks(NOW - 3600, NOW, 280)
        self.assertLess(len(narrow), len(wide))
        self.assertGreaterEqual(len(narrow), 2)

    def test_weekday_when_longer_than_a_day(self):
        ticks = chart.time_ticks(NOW - 2 * 86400, NOW, 560)
        labels = [label for _, label in ticks]
        self.assertTrue(re.match(r'^(Mo|Di|Mi|Do|Fr|Sa|So) \d\d:\d\d$', labels[0]), labels)
        # Weitere Wochentage nur an Tageswechseln.
        days = [label for label in labels if label[:2] in chart._WEEKDAYS]
        self.assertTrue(2 <= len(days) <= 4, labels)

    def test_labels_inside_svg(self):
        for width in (240, 360, 640):
            root = parse(chart.render_svg(make_points(NOW - 3600, NOW, 5), NOW, width=width))
            for el in by_class(root, 'text', 'pmc-axis'):
                if el.get('text-anchor') == 'middle':
                    half = chart.text_width(u''.join(el.itertext())) / 2
                    self.assertGreaterEqual(float(el.get('x')) - half, 0)
                    self.assertLessEqual(float(el.get('x')) + half, width)

    def assert_no_overlap(self, ticks, start, end, plot_width):
        for (a, text_a), (b, text_b) in zip(ticks, ticks[1:]):
            distance = (b - a) / (end - start) * plot_width
            needed = (chart.text_width(text_a) + chart.text_width(text_b)) / 2 + 4
            self.assertGreaterEqual(distance, needed, (text_a, text_b))

    def test_long_history_uses_two_week_steps(self):
        # 45 Tage (4320 Punkte zu 900 s) auf schmalem Handy: eine Woche
        # Abstand passt nicht mehr, zwei Wochen schon.
        start = NOW - 45 * 86400
        ticks = chart.time_ticks(start, NOW, 300)
        self.assertGreaterEqual(len(ticks), 2)
        self.assert_no_overlap(ticks, start, NOW, 300)
        for (a, _), (b, _) in zip(ticks, ticks[1:]):
            self.assertAlmostEqual(b - a, 14 * 86400, delta=3600)

    def test_very_long_span_limits_tick_count(self):
        # Uhr verstellt, ein Punkt von vor zehn Jahren: wenige Ticks auf
        # einem Vielfachen einer Woche statt Hunderter uebereinander.
        start = NOW - 10 * 365 * 86400
        for width in (240, 300, 1000):
            ticks = chart.time_ticks(start, NOW, width)
            self.assertGreaterEqual(len(ticks), 1)
            self.assertLessEqual(len(ticks), width // 78 + 1)
            self.assert_no_overlap(ticks, start, NOW, width)
            for (a, _), (b, _) in zip(ticks, ticks[1:]):
                self.assertAlmostEqual((b - a) / 604800.0, round((b - a) / 604800.0),
                                       delta=3600 / 604800.0)

    def test_range_zero_long_history_labels_do_not_overlap(self):
        points = make_points(NOW - 45 * 86400, NOW, 900)
        for width in (296, 320, 360):
            root = parse(chart.render_svg(points, NOW, range_s=0, width=width,
                                          interval=900))
            labels = sorted(axis_labels(root))
            self.assertGreaterEqual(len(labels), 2)
            for (xa, text_a), (xb, text_b) in zip(labels, labels[1:]):
                half = (chart.text_width(text_a) + chart.text_width(text_b)) / 2
                self.assertGreater(xb - xa, half, (width, text_a, text_b))


class DaylightSavingTest(unittest.TestCase):
    """Zeitachse bei der Zeitumstellung, Zeitzone Europe/Berlin."""

    def setUp(self):
        self._localtime = chart._localtime
        chart._localtime = berlin_localtime

    def tearDown(self):
        chart._localtime = self._localtime

    def check_labels(self, ticks):
        epochs = [epoch for epoch, _ in ticks]
        self.assertEqual(epochs, sorted(set(epochs)), ticks)  # steigend, keine Doppel
        for epoch, label in ticks:
            local = berlin_localtime(epoch)
            self.assertEqual(label[-5:], u'{0:02d}:{1:02d}'.format(local.tm_hour,
                                                                  local.tm_min))
        return epochs

    def test_repeated_hour_has_ticks(self):
        # Ende der Sommerzeit: 02:00 bis 03:00 gibt es zweimal. Auch die
        # zweite Haelfte des Fensters bekommt ihre Ticks, alle im gleichen
        # Abstand.
        end = _berlin_switch(2026, 10) + 1800  # 02:30 MEZ
        for range_s in (3600, 3 * 3600):
            for width in (300, 560):
                start = end - range_s
                ticks = chart.time_ticks(start, end, width)
                epochs = self.check_labels(ticks)
                steps = {b - a for a, b in zip(epochs, epochs[1:])}
                self.assertEqual(len(steps), 1, ticks)
                step = steps.pop()
                self.assertLessEqual(step, 3600)
                self.assertLess(epochs[0] - start, step, ticks)
                self.assertLess(end - epochs[-1], step, ticks)
                for epoch in epochs:
                    local = berlin_localtime(epoch)
                    self.assertEqual((local.tm_min * 60 + local.tm_sec) % step, 0)

    def test_repeated_hour_labels(self):
        end = _berlin_switch(2026, 10) + 1800
        ticks = chart.time_ticks(end - 3600, end, 300)
        self.assertEqual([label for _, label in ticks],
                         [u'02:30', u'02:45', u'02:00', u'02:15', u'02:30'])

    def test_skipped_hour_no_duplicates(self):
        # Beginn der Sommerzeit: 02:00 bis 03:00 gibt es nicht.
        switch = _berlin_switch(2026, 3)
        for range_s in (3600, 3 * 3600):
            for width in (300, 560):
                end = switch + 1800
                ticks = chart.time_ticks(end - range_s, end, width)
                self.assertGreaterEqual(len(ticks), 2)
                self.check_labels(ticks)
                for _, label in ticks:
                    self.assertFalse(label.startswith(u'02:'), ticks)

    def test_wall_clock_steps_stay_round(self):
        # Ab zwei Stunden Abstand zaehlt die Wanduhr (00:00, 02:00, ...).
        # Eine Uhrzeit, die es nicht gibt, entfaellt statt auf 01:00 zu
        # rutschen; doppelte Uhrzeiten kommen nur einmal.
        for month in (3, 10):
            switch = _berlin_switch(2026, month)
            for range_s, width in ((6 * 3600, 300), (12 * 3600, 360), (86400, 560)):
                end = switch + 4 * 3600
                ticks = chart.time_ticks(end - range_s, end, width)
                epochs = self.check_labels(ticks)
                self.assertGreaterEqual(len(epochs), 2)
                self.assertGreaterEqual(min(b - a for a, b in zip(epochs, epochs[1:])),
                                        7200)
                hours = []
                for epoch in epochs:
                    local = berlin_localtime(epoch)
                    self.assertEqual((local.tm_min, local.tm_sec), (0, 0))
                    hours.append(local.tm_hour)
                # Alle Stunden auf einem gemeinsamen Raster von 2 h oder mehr.
                grid = max(h for h in range(1, 25) if all(x % h == 0 for x in hours))
                self.assertGreaterEqual(grid, 2, ticks)


class RangeTest(unittest.TestCase):

    def test_range_limits_window(self):
        points = make_points(NOW - 7200, NOW, 5)
        root = parse(chart.render_svg(points, NOW, range_s=600, width=640))
        dots = [el for el in by_class(root, 'circle', 'pmc-f25')
                if 'pmc-end' not in el.get('class')]
        self.assertLessEqual(len(dots) - 1, 600 // 5 + 1)  # minus Legende

    def test_range_zero_shows_everything(self):
        points = make_points(NOW - 2 * 86400, NOW - 60, 60)
        root = parse(chart.render_svg(points, NOW, range_s=0, width=640, interval=60))
        dots = [el for el in by_class(root, 'circle', 'pmc-f25')
                if 'pmc-end' not in el.get('class')]
        first_x = min(float(el.get('cx')) for el in dots)
        self.assertLess(first_x, 60)
        self.assertIn(u'gesamter Verlauf', root.get('aria-label'))
        labels = [u''.join(el.itertext()) for el in by_class(root, 'text', 'pmc-axis')
                  if el.get('text-anchor') == 'middle']
        self.assertTrue(any(label[:2] in chart._WEEKDAYS for label in labels), labels)

    def test_range_zero_single_point(self):
        root = parse(chart.render_svg([(NOW - 5, 10.0, 20.0, 5, True)], NOW, range_s=0))
        self.assertEqual(len(by_class(root, 'circle', 'pmc-end')), 2)


class EmptyTest(unittest.TestCase):

    def test_no_points_default_message(self):
        root = parse(chart.render_svg([], NOW))
        self.assertIn(u'Noch keine Messwerte', texts(root))
        self.assertEqual(by_class(root, 'path', 'pmc-line'), [])
        self.assertEqual(by_class(root, 'text', 'pmc-value'), [])

    def test_custom_message(self):
        root = parse(chart.render_svg([], NOW, message=u'Kein Sensor verbunden'))
        self.assertIn(u'Kein Sensor verbunden', texts(root))
        self.assertIn(u'Kein Sensor verbunden', root.get('aria-label'))

    def test_points_outside_window(self):
        points = make_points(NOW - 7200, NOW - 4000, 5)
        root = parse(chart.render_svg(points, NOW, range_s=3600))
        self.assertIn(u'Keine Messwerte in diesem Zeitraum', texts(root))

    def test_range_zero_without_points(self):
        parse(chart.render_svg([], NOW, range_s=0))
        parse(chart.render_svg(None, NOW, range_s=0, width=240, height=140))


class EscapeTest(unittest.TestCase):

    def test_message_is_escaped(self):
        message = u'<b>Ger\xe4t & "Sensor"</b>\x01'
        svg = chart.render_svg([], NOW, message=message)
        root = parse(svg)
        self.assertIn(u'<b>Ger\xe4t & "Sensor"</b>', texts(root))
        self.assertNotIn(u'<b>', svg)
        self.assertNotIn(u'\x01', svg)

    def test_byte_message(self):
        message = u'Ger\xe4t fehlt'.encode('utf-8')
        root = parse(chart.render_svg([], NOW, message=message))
        self.assertIn(u'Ger\xe4t fehlt', texts(root))

    def test_escape_helper(self):
        self.assertEqual(chart.escape(u'a<b>&"\''), u'a&lt;b&gt;&amp;&quot;&#39;')


class LayoutTest(unittest.TestCase):

    def test_narrow_chart_wraps_legend(self):
        root = parse(chart.render_svg(make_points(NOW - 600, NOW, 5), NOW,
                                      width=240, height=140))
        unit = by_class(root, 'text', 'pmc-unit')[0]
        legend = [el for el in root.iter(NS + 'g') if el.get('class') == 'pmc-legend'][0]
        legend_y = float(legend.find(NS + 'text').get('y'))
        self.assertGreater(float(unit.get('y')), legend_y)
        for el in legend.iter(NS + 'text'):
            self.assertGreaterEqual(float(el.get('x')), 0)

    def test_value_format(self):
        self.assertEqual(chart.format_value(12.34), u'12,3')
        self.assertEqual(chart.format_value(0), u'0,0')


if __name__ == '__main__':
    unittest.main()
