# -*- coding: utf-8 -*-
"""Zeichnet den Messverlauf als SVG fuer die Oberflaeche (/chart.svg).

Reine Funktionen, importiert nichts aus dem Projekt: render_svg() bekommt
die Punkte aus dem Verlauf des AppState und liefert fertigen SVG-Text.
Der Server zeichnet, damit Diagramm und CSV dieselben Mittelwerte zeigen
und das alte WebView auf dem Handy keine Diagrammbibliothek braucht.

Die Seite holt das SVG per XHR und setzt es als innerHTML ein. So greifen
die CSS-Variablen --pmc-* der Seite (hell/dunkel); ohne sie gelten die
Rueckfallwerte, die zu dunklem Grund passen.
"""

from __future__ import absolute_import, division

import calendar
import math
import re
import time


# Farben. Die Seite setzt die Variablen passend zum Theme, das Diagramm
# selbst bleibt durchsichtig (die Karte der Seite ist der Grund). Ohne
# Variablen gelten die Rueckfallwerte der Spalte "dunkel" (Grund #111a20).
# Empfohlene Werte fuer die Seite:
#
#   Variable      dunkel    hell      Rolle
#   --pmc-bg      #111a20   #ffffff   Grund der Karte: Ring um die Endpunkte,
#                                     Hof um Beschriftungen ueber Linien
#   --pmc-text    #e6edf2   #14212b   Werte am Linienende
#   --pmc-muted   #93a3ae   #5b6b77   Achsen, Einheit, Legende, Meldung
#   --pmc-grid    #24323c   #e3e8ec   Gitterlinien (Haarlinie)
#   --pmc-pm25    #19a3c4   #0b84a5   Linie PM2.5 (Cyan)
#   --pmc-pm10    #9b6cf0   #7c4ddb   Linie PM10 (Violett)
#   --pmc-rec     #6f8fa6   #6b8aa1   Band "gespeichert", deckend angeben:
#                                     das Diagramm legt es selbst blass hin
#   --pmc-warn    #f5a524   #b86e00   Ampel "erhoeht" (nur fuer die Seite)
#   --pmc-bad     #f0475a   #d42f3c   Linie bei 50, Ampel "hoch"
#
# PM2.5 und PM10 sind Cyan und Violett: weit weg von der Ampel (gruen,
# orange, rot) und auch bei Rot-Gruen-Schwaeche auseinanderzuhalten.
# Geprueft (OKLab-Abstand x100, Simulation nach Machado 2009): dunkel
# 9.5 bei Deuteranopie und 20.2 normalsichtig, hell 11.4 und 19.7; beide
# Linien mindestens 3:1 gegen den Grund. Text (text/muted) erreicht in
# beiden Themes mindestens 4.5:1.
_STYLE = (
    u'.pm-chart{font-family:system-ui,-apple-system,"Segoe UI",Roboto,'
    u'"Helvetica Neue",Arial,sans-serif;font-size:11px}'
    u'.pmc-axis{fill:var(--pmc-muted,#93a3ae);font-variant-numeric:tabular-nums}'
    u'.pmc-unit,.pmc-legend text{fill:var(--pmc-muted,#93a3ae)}'
    u'.pmc-grid{stroke:var(--pmc-grid,#24323c);stroke-width:1;fill:none}'
    u'.pmc-base{stroke:var(--pmc-muted,#93a3ae);stroke-opacity:.45;stroke-width:1;fill:none}'
    u'.pmc-tick{stroke:var(--pmc-muted,#93a3ae);stroke-opacity:.45;stroke-width:1}'
    u'.pmc-line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}'
    u'.pmc-s25{stroke:var(--pmc-pm25,#19a3c4)}'
    u'.pmc-s10{stroke:var(--pmc-pm10,#9b6cf0)}'
    u'.pmc-f25{fill:var(--pmc-pm25,#19a3c4)}'
    u'.pmc-f10{fill:var(--pmc-pm10,#9b6cf0)}'
    u'.pmc-end{stroke:var(--pmc-bg,#111a20);stroke-width:2}'
    u'.pmc-rec{fill:var(--pmc-rec,#6f8fa6);fill-opacity:.16}'
    u'.pmc-rec-top{fill:var(--pmc-rec,#6f8fa6);fill-opacity:.75}'
    u'.pmc-ref{fill:none;stroke-width:1;stroke-dasharray:5 4;stroke-opacity:.7}'
    u'.pmc-ref25{stroke:var(--pmc-pm25,#19a3c4)}'
    u'.pmc-ref40{stroke:var(--pmc-pm10,#9b6cf0)}'
    u'.pmc-ref50{stroke:var(--pmc-bad,#f0475a)}'
    u'.pmc-halo{paint-order:stroke;stroke:var(--pmc-bg,#111a20);stroke-width:3px;'
    u'stroke-linejoin:round}'
    u'.pmc-reflabel{fill:var(--pmc-muted,#93a3ae);font-size:10px}'
    u'.pmc-value{fill:var(--pmc-text,#e6edf2);font-size:12px;font-weight:600;'
    u'font-variant-numeric:tabular-nums}'
    u'.pmc-msg{fill:var(--pmc-muted,#93a3ae);font-size:13px}'
    u'.pmc-msgbg{fill:var(--pmc-bg,#111a20)}'
    u'.pmc-dim{opacity:.55}'
)

# Lueckenregel: liegen zwei Punkte weiter als so viele Intervalle (das
# laengere der beiden) auseinander, wird die Linie unterbrochen.
GAP_FACTOR = 2.5
# Kuerzeste Zeitspanne bei range=0, damit wenige Punkte nicht auf eine
# Handvoll Pixel zusammengezogen werden.
MIN_SPAN = 60
# Hoechstens so viele Punkte pro Pixel Breite zeichnen (Downsampling).
POINTS_PER_PX = 0.5

# Masse in Pixeln: Schriftgroessen, Grundlinie der ersten Kopfzeile,
# Zeilenabstand der Kopfzeilen, Abstand Kopf -> Diagramm, Platz unten fuer
# die Zeitachse, Abstand zwischen Legendeneintraegen.
_FONT = 11
_VALUE_FONT = 12
_HEAD_BASE = 12
_HEAD_ROW = 16
_HEAD_GAP = 20
_BOTTOM = 24
_ITEM_GAP = 14

# Moegliche Abstaende der Zeitachse in Sekunden. Bis 3600 teilen alle eine
# Stunde (siehe time_ticks).
_TIME_STEPS = (15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800,
               21600, 43200, 86400, 172800, 604800, 1209600, 2419200)
_DAY = 86400
_WEEK = 7 * _DAY
_WEEKDAYS = (u'Mo', u'Di', u'Mi', u'Do', u'Fr', u'Sa', u'So')

# Grenzwertlinien: Wert, CSS-Klasse, Beschriftung. Dieselben Schwellen
# wie die Ampel (kml.color_selection_rgb): ab der Linie gilt der Text.
# Reihenfolge = Vorrang der Beschriftung, wenn es eng wird.
_REFS = (
    (50, u'pmc-ref50', u'hoch'),
    (25, u'pmc-ref25', u'PM2.5 erhöht'),
    (40, u'pmc-ref40', u'PM10 erhöht'),
)

# In XML 1.0 verbotene Steuerzeichen (alles unter 0x20 ausser Tab, LF, CR).
_XML_BAD = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _text(value):
    """Beliebigen Wert als unicode (Python 2: bytes als UTF-8 lesen)."""
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return u'{0}'.format(value)


def escape(value):
    """Text fuer XML-Inhalt und Attribute maskieren, Steuerzeichen weg."""
    text = _XML_BAD.sub(u'', _text(value))
    return (text.replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;').replace(u'"', u'&quot;')
            .replace(u"'", u'&#39;'))


def _n(value):
    """Koordinate kompakt: eine Nachkommastelle, ohne '.0'."""
    text = u'{0:.1f}'.format(value)
    if text.endswith(u'.0'):
        text = text[:-2]
    return u'0' if text == u'-0' else text


def format_value(value):
    """Messwert fuer die Beschriftung, deutsch mit Dezimalkomma: 12,3."""
    return u'{0:.1f}'.format(value).replace(u'.', u',')


def text_width(text, size=_FONT):
    """Breite eines Textes grob schaetzen (Systemschrift, ohne Messen).

    Reicht, um Beschriftungen nicht ueberlappen zu lassen; lieber etwas
    zu breit als zu schmal.
    """
    width = 0.0
    for char in text:
        if char.isdigit():
            width += 0.57
        elif char in u'.,:;!|il\'':
            width += 0.3
        elif char == u' ':
            width += 0.28
        elif char in u'mwMW':
            width += 0.85
        elif char.isupper():
            width += 0.68
        else:
            width += 0.55
    return width * size


def nice_step(raw):
    """Kleinster Schritt aus der 1-2-5-Reihe, der mindestens raw ist."""
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    for factor in (1.0, 2.0, 5.0, 10.0):
        if factor * base >= raw * (1 - 1e-9):
            return factor * base
    return 10.0 * base


def y_scale(max_value, plot_height):
    """Obere Grenze und Schritt der y-Achse.

    Schritt aus der 1-2-5-Reihe, etwa alle 36 px eine Linie (2 bis 6
    Abschnitte). Grenze aus Maximalwert x1.15, mindestens 10, auf einen
    halben Schritt aufgerundet: nutzt die Hoehe, ohne dass die Skala bei
    jedem neuen Punkt springt.
    """
    top_raw = max(10.0, float(max_value) * 1.15)
    count = max(2, min(6, int(plot_height // 36)))
    step = nice_step(top_raw / count)
    half = step / 2.0
    top = math.ceil(top_raw / half - 1e-9) * half
    return top, step


# Ortszeit. Die Tests setzen hier eine feste Zeitzone ein (time.tzset
# gibt es unter Windows nicht).
_localtime = time.localtime


def _utc_offset(epoch):
    """Abstand der Ortszeit zu UTC in Sekunden (mit Sommerzeit)."""
    return calendar.timegm(_localtime(epoch)) - int(epoch)


def _clock(local):
    return u'{0:02d}:{1:02d}'.format(local.tm_hour, local.tm_min)


def _tick_room(step, long_span):
    """Platz in px, den ein Tick bei diesem Abstand braucht (Text + Luft)."""
    if step < 60:
        sample = u'00:00:00'
    elif step >= _DAY:
        sample = u'Mo 00.00.'
    elif long_span:
        sample = u'Mo 00:00'
    else:
        sample = u'00:00'
    return text_width(sample) + 28


def _tick_epochs(start, end, step):
    """Zeitpunkte der Ticks zwischen start und end, aufsteigend."""
    offset = _utc_offset(start)
    epochs = []
    if step <= 3600:
        # Teiler einer Stunde: in echten Sekunden weiterzaehlen. Die
        # Sommerzeit verschiebt um eine ganze Stunde, die Ticks bleiben also
        # auf runden Ortszeiten, und die doppelte Stunde im Herbst bekommt
        # ihre Ticks auch.
        epoch = math.ceil((start + offset) / step) * step - offset
        while epoch <= end + 1e-6:
            epochs.append(epoch)
            epoch += step
        return epochs
    # Ab zwei Stunden auf der Wanduhr weiterzaehlen (00:00, 02:00, ...).
    wall = math.ceil((start + offset) / step) * step
    while True:
        # Sommerzeit-Wechsel: Versatz am Tick selbst nachschlagen.
        epoch = wall - _utc_offset(wall - offset)
        if epoch > end + 1e-6:
            break
        # Uhrzeit, die es wegen der Umstellung nicht gibt, und Doppelte
        # weglassen.
        if (epoch >= start - 1e-6
                and calendar.timegm(_localtime(epoch)) == wall
                and (not epochs or epoch > epochs[-1])):
            epochs.append(epoch)
        wall += step
    return epochs


def time_ticks(start, end, plot_width):
    """Ticks der Zeitachse als Liste (epoch, Beschriftung).

    Die Ticks liegen auf runden Ortszeiten (14:00, 14:15, ...), der
    Abstand richtet sich nach der Breite. Bei mehr als einem Tag Spanne
    traegt der erste Tick und jeder Tageswechsel den Wochentag ("Di 14:00").
    """
    span = float(end - start)
    if span <= 0 or plot_width <= 0:
        return []
    long_span = span > _DAY
    step = None
    for candidate in _TIME_STEPS:
        if plot_width * candidate / span >= _tick_room(candidate, long_span):
            step = candidate
            break
    if step is None:
        # Laenger als die groesste Stufe (z. B. Uhr verstellt, ein Punkt von
        # vor Jahren): ein Vielfaches einer Woche, das gerade passt. So gibt
        # es hoechstens etwa Breite/78 Ticks statt Tausender uebereinander.
        need = span * _tick_room(_WEEK, long_span) / plot_width
        step = int(math.ceil(need / _WEEK)) * _WEEK

    ticks = []
    last_day = None
    for epoch in _tick_epochs(start, end, step):
        local = _localtime(epoch)
        day = (local.tm_year, local.tm_yday)
        weekday = _WEEKDAYS[local.tm_wday]
        if step < 60:
            label = u'{0}:{1:02d}'.format(_clock(local), local.tm_sec)
        elif step >= _DAY:
            label = u'{0} {1:02d}.{2:02d}.'.format(weekday, local.tm_mday,
                                                  local.tm_mon)
        elif long_span and day != last_day:
            label = u'{0} {1}'.format(weekday, _clock(local))
        else:
            label = _clock(local)
        last_day = day
        ticks.append((epoch, label))
    return ticks


def _clean(points, interval):
    """Gueltige Punkte als (epoch, pm25, pm10, interval, recorded), sortiert."""
    result = []
    for point in points or ():
        try:
            epoch = float(point[0])
            pm25 = float(point[1])
            pm10 = float(point[2])
        except (TypeError, ValueError, IndexError):
            continue
        if pm25 != pm25 or pm10 != pm10 or epoch != epoch:
            continue  # NaN
        try:
            own = float(point[3])
        except (TypeError, ValueError, IndexError):
            own = 0.0
        if own <= 0:
            own = float(interval)
        recorded = bool(point[4]) if len(point) > 4 else False
        result.append((epoch, max(0.0, pm25), max(0.0, pm10), own, recorded))
    result.sort(key=lambda item: item[0])
    return result


def split_segments(points):
    """Punkte an Luecken auftrennen: Liste von Listen.

    Luecke: Abstand zum Vorgaenger groesser als GAP_FACTOR x das laengere
    Intervall der beiden Punkte. Wird das Intervall verkuerzt (15 min ->
    5 s), kommt der erste kurze Punkt bis zu ein altes Intervall nach dem
    letzten langen; das ist keine Luecke.
    """
    segments = []
    current = []
    previous = None
    for point in points:
        if (previous is not None and point[0] - previous[0]
                > GAP_FACTOR * max(previous[3], point[3])):
            segments.append(current)
            current = []
        current.append(point)
        previous = point
    if current:
        segments.append(current)
    return segments


def _bucket_mean(group, bucket):
    count = len(group)
    return (
        sum(p[0] for p in group) / count,
        sum(p[1] for p in group) / count,
        sum(p[2] for p in group) / count,
        max(max(p[3] for p in group), bucket),
        any(p[4] for p in group),
    )


def downsample(segments, start, span, max_points):
    """Mehr Punkte als max_points: in Zeit-Buckets mitteln.

    Jedes Teilstueck fuer sich, damit Luecken Luecken bleiben. Ein Bucket
    gilt als gespeichert, wenn irgendein Punkt darin gespeichert wurde.
    """
    total = sum(len(segment) for segment in segments)
    if total <= max_points or max_points < 1:
        return segments
    bucket = float(span) / max_points
    result = []
    for segment in segments:
        groups = []
        key = None
        for point in segment:
            index = int((point[0] - start) // bucket)
            if index != key:
                groups.append([])
                key = index
            groups[-1].append(point)
        result.append([_bucket_mean(group, bucket) for group in groups])
    return result


def recorded_spans(segments):
    """Zeitspannen (von, bis) zusammenhaengend gespeicherter Punkte.

    Ein Punkt steht fuer den Mittelwert ueber sein Intervall davor, das
    Band beginnt deshalb ein Intervall vor dem ersten Punkt.
    """
    spans = []
    for segment in segments:
        begin = None
        last = None
        for point in segment:
            if point[4]:
                if begin is None:
                    begin = point[0] - point[3]
                last = point[0]
            elif begin is not None:
                spans.append((begin, last))
                begin = None
        if begin is not None:
            spans.append((begin, last))
    return spans


def _range_text(range_s):
    if not range_s:
        return u'gesamter Verlauf'
    if range_s < 3600:
        return u'letzte {0} min'.format(int(range_s // 60))
    hours = range_s / 3600.0
    if hours == 1:
        return u'letzte Stunde'
    return u'letzte {0} h'.format(_n(hours))


def _legend_items():
    # (Art, CSS-Klasse, Text)
    return ((u'line', u'pmc-s25', u'PM2.5'), (u'line', u'pmc-s10', u'PM10'),
            (u'rec', u'', u'gespeichert'))


def _legend_width(items):
    width = 0.0
    for kind, _, label in items:
        key = 16 if kind == u'line' else 12
        width += key + 5 + text_width(label)
    return width + _ITEM_GAP * (len(items) - 1)


def _draw_legend(out, items, right, baseline):
    """Legende rechtsbuendig bis right zeichnen."""
    x = right - _legend_width(items)
    out.append(u'<g class="pmc-legend">')
    for kind, cls, label in items:
        mid = baseline - 3.5
        if kind == u'line':
            out.append(u'<path class="pmc-line {0}" d="M{1} {2}h12"/>'.format(
                cls, _n(x + 2), _n(mid)))
            x += 16
        else:
            out.append(u'<rect class="pmc-rec" x="{0}" y="{1}" width="12" height="10"/>'
                       u'<rect class="pmc-rec-top" x="{0}" y="{1}" width="12" height="2"/>'
                       .format(_n(x), _n(mid - 5)))
            x += 12
        x += 5
        out.append(u'<text x="{0}" y="{1}">{2}</text>'.format(
            _n(x), _n(baseline), escape(label)))
        x += text_width(label) + _ITEM_GAP
    out.append(u'</g>')


def _crosses(segments, x_of, y_of, x0, x1, y0, y1):
    """Laeuft eine der beiden Linien durch das Rechteck x0..x1, y0..y1?

    Prueft jede Teilstrecke grob ueber ihr umschliessendes Rechteck; das
    reicht, um eine Beschriftung nicht auf eine Linie zu legen.
    """
    for segment in segments:
        previous = None
        for point in segment:
            x = x_of(point[0])
            current = (x, y_of(point[1]), y_of(point[2]))
            first = previous or current
            if min(first[0], x) <= x1 and max(first[0], x) >= x0:
                for index in (1, 2):
                    if (min(first[index], current[index]) <= y1
                            and max(first[index], current[index]) >= y0):
                        return True
            previous = current
    return False


def _spread_labels(labels, low, high, gap):
    """Zwei Endwert-Beschriftungen auseinanderschieben, wenn sie sich decken.

    labels: Liste [y, Wert, Klasse] (y = Mitte der Zeile), wird angepasst.
    Die Reihenfolge oben/unten bleibt die der Linien, bei gleichem Wert
    steht PM10 oben. Bleibt innerhalb [low, high].
    """
    if len(labels) != 2:
        return
    upper, lower = sorted(labels, key=lambda item: (item[0], item[2] != u'pmc-f10'))
    if lower[0] - upper[0] < gap:
        middle = (upper[0] + lower[0]) / 2.0
        upper[0] = middle - gap / 2.0
        lower[0] = middle + gap / 2.0
    if upper[0] < low:
        shift = low - upper[0]
        upper[0] += shift
        lower[0] += shift
    if lower[0] > high:
        shift = lower[0] - high
        upper[0] -= shift
        lower[0] -= shift


def render_svg(points, now, range_s=3600, width=640, height=320, interval=5,
               message=None):
    """points: Liste (epoch, pm25, pm10, interval, recorded) aufsteigend.
    now: epoch (rechter Rand). range_s: Sichtfenster in s, 0 = alles (vom ersten Punkt).
    Liefert unicode-SVG."""
    width = int(width)
    height = int(height)
    now = float(now)
    try:
        interval = float(interval) if interval else 5.0
    except (TypeError, ValueError):
        interval = 5.0
    range_s = int(range_s or 0)

    all_points = _clean(points, interval)

    # Sichtfenster
    if range_s > 0:
        start = now - range_s
    elif all_points:
        start = all_points[0][0] - all_points[0][3]
    else:
        start = now - 3600
    if now - start < MIN_SPAN:
        start = now - MIN_SPAN
    span = now - start
    window = [p for p in all_points if start <= p[0] <= now + interval]
    # Leicht in der Zukunft (Uhren nicht ganz gleich): an den Rand legen.
    window = [p if p[0] <= now else (now,) + p[1:] for p in window]
    has_data = bool(window)

    # Kopfzeile: Einheit links, Legende rechts; zu schmal -> zwei Zeilen.
    legend = _legend_items()
    unit = u'µg/m³'
    unit_w = text_width(unit)
    rows = 1
    if has_data and unit_w + 16 + _legend_width(legend) > width - 2:
        rows = 2
    unit_y = _HEAD_BASE + (rows - 1) * _HEAD_ROW
    plot_top = unit_y + _HEAD_GAP
    plot_bottom = height - _BOTTOM
    plot_h = max(20, plot_bottom - plot_top)
    plot_bottom = plot_top + plot_h

    max_value = max([max(p[1], p[2]) for p in window] or [0.0])
    top, step = y_scale(max_value, plot_h)
    y_ticks = []
    count = 0
    while count * step <= top + 1e-9:
        y_ticks.append(count * step)
        count += 1
    decimals = 0 if step >= 1 else 1
    y_labels = [u'{0:.{1}f}'.format(tick, decimals).replace(u'.', u',')
                for tick in y_ticks]
    left = max(22.0, max(text_width(label) for label in y_labels) + 10)

    last = window[-1] if has_data else None
    if has_data:
        # Platz rechts fuer die Endwerte, mindestens fuer "88,8", damit die
        # Flaeche nicht bei jedem Wert springt.
        widest = max(text_width(format_value(last[1]), _VALUE_FONT),
                     text_width(format_value(last[2]), _VALUE_FONT),
                     text_width(u'88,8', _VALUE_FONT))
        right_margin = widest + 14
    else:
        right_margin = 12
    plot_left = left
    plot_right = max(plot_left + 20, width - right_margin)
    plot_w = plot_right - plot_left

    def x_of(epoch):
        return plot_left + (epoch - start) / span * plot_w

    def y_of(val):
        return plot_bottom - min(val, top) / top * plot_h

    out = []
    if has_data:
        label = (u'Feinstaub-Verlauf, {0}: PM2.5 zuletzt {1} µg/m³, '
                 u'PM10 zuletzt {2} µg/m³').format(
                     _range_text(range_s), format_value(last[1]), format_value(last[2]))
    else:
        label = u'Feinstaub-Verlauf, {0}: {1}'.format(
            _range_text(range_s), _empty_message(message, all_points))
    out.append(
        u'<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" '
        u'viewBox="0 0 {0} {1}" class="pm-chart" role="img" aria-label="{2}">'
        .format(width, height, escape(label)))
    out.append(u'<title>{0}</title>'.format(escape(label)))
    out.append(u'<style>{0}</style>'.format(_STYLE))

    segments = []
    if has_data:
        segments = split_segments(window)
        max_points = max(10, int(plot_w * POINTS_PER_PX))
        segments = downsample(segments, start, span, max_points)

        # Gespeicherte Abschnitte als Band ueber die volle Hoehe, oben mit
        # einer kraeftigeren Kante. Baender unter 1 px Abstand verschmelzen.
        bands = []
        for begin, end in recorded_spans(segments):
            x0 = max(plot_left, x_of(begin))
            x1 = min(plot_right, x_of(end))
            if x1 - x0 < 1.5:
                x1 = min(plot_right, x0 + 1.5)
            if bands and x0 - bands[-1][1] < 1:
                bands[-1][1] = x1
            else:
                bands.append([x0, x1])
        if bands:
            out.append(u'<g class="pmc-bands">')
            for x0, x1 in bands:
                out.append(
                    u'<rect class="pmc-rec" x="{0}" y="{1}" width="{2}" height="{3}"/>'
                    u'<rect class="pmc-rec-top" x="{0}" y="{1}" width="{2}" height="2"/>'
                    .format(_n(x0), _n(plot_top), _n(x1 - x0), _n(plot_h)))
            out.append(u'</g>')

    # Gitter und y-Achse. Ohne Daten nur blass.
    out.append(u'<g class="pmc-dim">' if not has_data else u'<g>')
    for tick, text in zip(y_ticks, y_labels):
        y = y_of(tick)
        if tick > 0:
            # Auf halbe Pixel gelegt, damit die Haarlinie scharf bleibt.
            out.append(u'<path class="pmc-grid" d="M{0} {1}H{2}"/>'.format(
                _n(plot_left), _n(round(y) + 0.5), _n(plot_right)))
        out.append(u'<text class="pmc-axis" x="{0}" y="{1}" text-anchor="end" '
                   u'dy=".35em">{2}</text>'.format(_n(plot_left - 7), _n(y), text))
    base_y = plot_bottom + 0.5
    out.append(u'<path class="pmc-base" d="M{0} {1}H{2}"/>'.format(
        _n(plot_left), _n(base_y), _n(plot_right)))

    # Zeitachse: kurze Striche unter der Grundlinie, Beschriftung darunter,
    # am Rand nach innen geschoben statt abgeschnitten.
    for epoch, text in time_ticks(start, now, plot_w):
        x = x_of(epoch)
        half = text_width(text) / 2.0
        tx = min(max(x, half + 1), width - half - 1)
        out.append(u'<path class="pmc-tick" d="M{0} {1}v4"/>'.format(
            _n(round(x) + 0.5), _n(base_y)))
        out.append(u'<text class="pmc-axis" x="{0}" y="{1}" text-anchor="middle">'
                   u'{2}</text>'.format(_n(tx), _n(plot_bottom + 17), escape(text)))
    out.append(u'</g>')

    if not has_data:
        out.append(u'<text class="pmc-unit pmc-dim" x="1" y="{0}">{1}</text>'.format(
            _n(unit_y), escape(unit)))
        # Die Meldung auf einem Schild im Grundton, damit keine Gitterlinie
        # durch die Schrift laeuft.
        text = _empty_message(message, all_points)
        mid_x = plot_left + plot_w / 2.0
        mid_y = plot_top + plot_h / 2.0
        box_w = min(plot_w, text_width(text, 13) + 24)
        out.append(u'<rect class="pmc-msgbg" x="{0}" y="{1}" width="{2}" height="24" '
                   u'rx="12"/>'.format(_n(mid_x - box_w / 2.0), _n(mid_y - 12), _n(box_w)))
        out.append(u'<text class="pmc-msg" x="{0}" y="{1}" text-anchor="middle" '
                   u'dy=".35em">{2}</text>'.format(_n(mid_x), _n(mid_y), escape(text)))
        out.append(u'</svg>')
        return u''.join(out)

    # Grenzwertlinien, nur innerhalb der Skala. Beschriftung immer ueber der
    # Linie ("ab hier"), an der Oberkante darf sie in den Kopfabstand
    # ragen. Kreuzt sie eine andere Grenzlinie oder Beschriftung, entfaellt
    # sie; bei gestauchter Skala bleibt so nur "hoch". Sonst links, in der
    # Mitte oder rechts, je nachdem, wo keine Messlinie durchlaeuft.
    refs = [(limit, cls, text, y_of(limit)) for limit, cls, text in _REFS
            if limit <= top]
    for _, cls, _, y in sorted(refs, key=lambda item: item[0]):
        out.append(u'<path class="pmc-ref {0}" d="M{1} {2}H{3}"/>'.format(
            cls, _n(plot_left), _n(y), _n(plot_right)))
    # Die Beschriftungen kommen erst nach den Messlinien ins SVG (siehe
    # unten): laeuft doch eine Linie durch, liegt die Schrift mit ihrem Hof
    # obenauf und bleibt lesbar.
    ref_labels = []
    boxes = []
    for _, _, text, y in refs:
        base = y - 4
        box = (base - 9, base + 2)
        if (box[0] < unit_y + 5
                or any(box[0] - 1 <= other[3] <= box[1] + 1 for other in refs)
                or any(box[0] < b[1] and b[0] < box[1] for b in boxes)):
            continue
        boxes.append(box)
        label_w = text_width(text, 10)
        candidates = [plot_left + 5, plot_left + (plot_w - label_w) / 2.0,
                      plot_right - label_w - 10]
        x = candidates[0]
        for candidate in candidates:
            if candidate >= plot_left and not _crosses(
                    segments, x_of, y_of, candidate - 2, candidate + label_w + 2,
                    box[0] - 1, box[1] + 1):
                x = candidate
                break
        ref_labels.append(u'<text class="pmc-reflabel pmc-halo" x="{0}" y="{1}">{2}</text>'
                          .format(_n(x), _n(base), escape(text)))

    # Linien: PM10 zuerst, PM2.5 obendrauf. Ein Pfad je Teilstueck,
    # Einzelpunkte als kleiner Kreis.
    for index, cls, fill in ((2, u'pmc-s10', u'pmc-f10'), (1, u'pmc-s25', u'pmc-f25')):
        out.append(u'<g>')
        for segment in segments:
            if len(segment) == 1:
                point = segment[0]
                out.append(u'<circle class="{0}" cx="{1}" cy="{2}" r="2.5"/>'.format(
                    fill, _n(x_of(point[0])), _n(y_of(point[index]))))
                continue
            coords = [u'{0} {1}'.format(_n(x_of(p[0])), _n(y_of(p[index])))
                      for p in segment]
            out.append(u'<path class="pmc-line {0}" d="M{1}"/>'.format(
                cls, u'L'.join(coords)))
        out.append(u'</g>')

    out.extend(ref_labels)

    # Letzter Wert: Punkt mit Ring im Grundton und Zahl daneben.
    end_x = x_of(last[0])
    labels = [[y_of(last[1]), last[1], u'pmc-f25'], [y_of(last[2]), last[2], u'pmc-f10']]
    for y, _, fill in (labels[1], labels[0]):
        out.append(u'<circle class="{0} pmc-end" cx="{1}" cy="{2}" r="4"/>'.format(
            fill, _n(end_x), _n(y)))
    _spread_labels(labels, plot_top + 6, plot_bottom - 6, _VALUE_FONT + 3)
    for y, val, _ in labels:
        text = format_value(val)
        if end_x + 9 + text_width(text, _VALUE_FONT) <= width - 1:
            x, anchor = end_x + 9, u'start'
        else:
            x, anchor = end_x - 9, u'end'
        out.append(u'<text class="pmc-value pmc-halo" x="{0}" y="{1}" text-anchor="{2}" '
                   u'dy=".35em">{3}</text>'.format(_n(x), _n(y), anchor, text))

    # Kopfzeile: Legende rechts oben, Einheit links ueber der y-Achse (bei
    # zwei Zeilen darunter).
    _draw_legend(out, legend, width - 1, _HEAD_BASE)
    out.append(u'<text class="pmc-unit" x="1" y="{0}">{1}</text>'.format(
        _n(unit_y), escape(unit)))

    out.append(u'</svg>')
    return u''.join(out)


def _empty_message(message, all_points):
    """Text fuer ein leeres Diagramm."""
    if message:
        return _text(message)
    if all_points:
        return u'Keine Messwerte in diesem Zeitraum'
    return u'Noch keine Messwerte'
