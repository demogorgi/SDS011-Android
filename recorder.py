# -*- coding: utf-8 -*-
"""Mittelwerte je Messintervall: Verlauf, Aufzeichnung (KML/CSV) und
Upload im stationaeren Modus.

main.py startet den Recorder als Thread. Er liest Messwerte und Position
aus dem AppState (state.py), den Sensor selbst liest er nicht. Je
Messintervall mittelt er alle Sensorwerte, haengt den Mittelwert an den
Verlauf im AppState (daraus zeichnet webapp.py das Diagramm) und
schreibt ihn bei laufender Messung in die Dateien. Der Upload im
stationaeren Modus mittelt ueber sein eigenes, laengeres Fenster. Alle
Wartezeiten laufen ueber state.wait(), damit sich das Programm sofort
beenden laesst und nicht bis zu STAT_INT Sekunden haengt.
"""

from __future__ import absolute_import

import datetime
import json
import os
import threading
import time

import config
import kml
from logging_util import to_text, write_log

try:                                   # Python 3
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
except ImportError:                    # Python 2
    from urllib2 import Request, urlopen, HTTPError


# time.monotonic gibt es erst ab Python 3.3.
_now = getattr(time, 'monotonic', time.time)


def _have_ssl():
    try:
        import ssl  # noqa: F401
        return True
    except ImportError:
        return False


# Fehlertexte, an denen HTTPS dauerhaft scheitert: veraltete Zertifikate
# oder ein Protokoll, das die alte ssl-Bibliothek nicht kann.
_TLS_MARKERS = ('CERTIFICATE', 'UNSUPPORTED PROTOCOL', 'PROTOCOL VERSION',
                'WRONG VERSION NUMBER', 'HANDSHAKE FAILURE', 'UNKNOWN PROTOCOL',
                'TLSV1_ALERT', 'SSLV3_ALERT')
# Voruebergehend -- schlechtes Mobilnetz, kein Grund fuer HTTP.
_TRANSIENT_MARKERS = ('TIMED OUT', 'TIMEOUT', 'EOF OCCURRED')


def is_tls_error(exc):
    """True, wenn ein Upload dauerhaft an TLS gescheitert ist.

    Altes Android hat oft ein ssl-Modul, aber veraltete Zertifikate --
    dann scheitert jeder HTTPS-Upload, obwohl HTTP ginge. Ein Timeout
    im Handshake ('_ssl.c:...: The handshake operation timed out')
    zaehlt nicht, das ist nur langsames Netz. Deshalb haben die
    _TRANSIENT_MARKERS Vorrang.
    """
    reason = getattr(exc, 'reason', None)
    text = (to_text(exc) + u' ' + to_text(reason or u'')).upper()
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return False
    return any(marker in text for marker in _TLS_MARKERS)


def upload_url(url, have_ssl=None):
    """HTTPS, wenn Python es kann, sonst HTTP.

    Altes QPython ist ohne ssl-Modul gebaut, urllib meldet dann
    'unknown url type: https'. Die API nimmt auch HTTP an -- so senden
    die Feinstaubsensoren von sensor.community ohnehin standardmaessig.
    """
    if have_ssl is None:
        have_ssl = _have_ssl()
    if not have_ssl and url.startswith('https://'):
        return 'http://' + url[len('https://'):]
    return url


def post_json(url, body, headers, timeout=30):
    """POST mit JSON-Body, liefert den HTTP-Statuscode.

    Nur Standardbibliothek: requests fehlt auf alten QPython-Versionen,
    und pip scheitert dort oft schon an veralteten TLS-Zertifikaten.
    Netzfehler werden geworfen, HTTP-Fehler als Statuscode geliefert.
    """
    if not isinstance(body, bytes):
        body = body.encode('utf-8')
    request = Request(url, data=body, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        return exc.code
    try:
        return response.getcode()
    finally:
        response.close()


def _coord(value):
    """GPS-Koordinate mit fester Genauigkeit.

    Nicht str(): das liefert je nach Rechenweg Float-Rauschen wie
    51.439099999999996. Sechs Nachkommastellen entsprechen etwa 11 cm
    und sind damit genauer als jedes Handy-GPS.
    """
    return '%.6f' % value


def _value(value):
    """Messwert mit einer Nachkommastelle, so genau wie der Sensor.

    Ein Mittelwert hat sonst Float-Rauschen (12.350000000000001). Datei,
    Upload und Verlauf bekommen alle diese gerundete Zahl, damit
    Diagramm und CSV dasselbe zeigen.
    """
    return '%.1f' % value


_UMLAUTS = [(u'ä', u'ae'), (u'ö', u'oe'), (u'ü', u'ue'),
            (u'Ä', u'ae'), (u'Ö', u'oe'), (u'Ü', u'ue'),
            (u'ß', u'ss')]


def slugify(text, maxlen=40):
    """Freitext in einen Dateinamen-Baustein verwandeln.

    "Kletterhalle Duisburg" -> "kletterhalle_duisburg". Umlaute werden
    umschrieben, uebrige Nicht-ASCII-Zeichen entfallen. Leerer oder
    unbrauchbarer Text ergibt '', der Aufrufer nimmt dann einen
    Standardnamen.
    """
    if not text:
        return ''
    try:
        value = text if isinstance(text, type(u'')) else text.decode('utf-8', 'replace')
    except Exception:
        return ''
    value = value.strip().lower()
    for umlaut, replacement in _UMLAUTS:
        value = value.replace(umlaut, replacement)

    out = []
    for char in value:
        if char.isalnum() and ord(char) < 128:
            out.append(char)
        elif char in (u' ', u'-', u'_', u'.'):
            out.append(u'_')
    slug = ''.join(out)
    while '__' in slug:
        slug = slug.replace('__', '_')
    return str(slug.strip('_')[:maxlen])


# Kennung dieser Software beim Upload zu sensor.community.
SOFTWARE_VERSION = 'SDS011-Android'

# Arten eigener Hinweise: kein aktueller Messwert / Schreibfehler.
HINT_STALE = 'stale'
HINT_FAILURE = 'failure'

# Die drei Modi, wie der Recorder sie unterscheidet.
MODE_TRIP = 'messfahrt'
MODE_LOCAL = 'lokal'
MODE_STATIONARY = 'stationaer'


def _timestamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H_%M_%S')


class Recorder(threading.Thread):
    """Thread, der je Messintervall einen Mittelwert bildet und ihn je
    nach Modus aufzeichnet, und im stationaeren Modus hochlaedt.

    Laeuft, solange state.sensing gesetzt ist, und schliesst zum Schluss
    offene KML-Dateien. Eigene Probleme zeigt er als Hinweis in der
    Oberflaeche an, statt still zu sterben.

    Zwei Zeitfenster: das Aufzeichnungsfenster (ein Messintervall, ein
    Punkt) und das Upload-Fenster (STAT_INT). Beide merken sich die
    Summen aus state.sample_totals() zu ihrem Beginn; der Mittelwert ist
    die Differenz bis jetzt.
    """

    # Wie oft geprueft wird, ob eine Taste gedrueckt wurde.
    TICK = 0.5
    # Nach einem Upload-Versuch ohne aktuellen Messwert spaetestens nach
    # so vielen Sekunden neu versuchen, nicht erst nach STAT_INT.
    PUSH_RETRY = 5.0
    # So lange (s) wartet ein Upload hoechstens auf jede Antwort des
    # Servers. Er laeuft im Recorder-Thread: haengt das Netz, entsteht so
    # lange kein Punkt (die Sensorwerte landen im naechsten).
    UPLOAD_TIMEOUT = 15

    def __init__(self, state, outdir=None, record_interval=None, stat_interval=None,
                 tick=None, max_age=None, gps_max_age=None, clock=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._outdir = outdir or config.OUTDIR
        # Die Parameter ausser state sind fuer Tests, damit sie nicht
        # Sekunden oder Minuten warten muessen. Ohne record_interval gilt
        # das Messintervall aus dem AppState, bei jedem Durchlauf neu
        # gelesen -- so wirkt eine Umstellung in der Oberflaeche sofort.
        self._record_interval = record_interval
        self._stat_interval = config.STAT_INT if stat_interval is None else stat_interval
        self._tick = self.TICK if tick is None else tick
        self._max_age = config.MAX_MEASUREMENT_AGE if max_age is None else max_age
        self._gps_max_age = config.GPS_MAX_AGE if gps_max_age is None else gps_max_age
        # Wanduhr fuer die Zeitstempel in Verlauf, Sitzung und Upload.
        # Geplant wird mit _now (monotonic), das beim Stellen der Uhr
        # nicht springt.
        self._clock = time.time if clock is None else clock
        # Nach einem TLS-Fehler bleibt der Upload bei HTTP.
        self._plain_http = False
        self._files_open = False
        self._files_mode = None
        # Eigene Hinweise in der Oberflaeche, je Art. Nur die raeumt der
        # Recorder wieder weg, nicht etwa einen Verbindungsfehler.
        self._hints = {HINT_STALE: None, HINT_FAILURE: None}

        # Aufzeichnungsfenster: zu welchem Modus es gehoert, wann es
        # begann (monotonic) und die Summen zu Beginn. None = noch keins;
        # dann zaehlt der aktuelle Messwert.
        self._window_mode = None
        self._window_start = None
        self._window_totals = None
        # Messintervall zu Beginn des Fensters und die Zeit, die der Thread
        # darin mit Uploads verbracht hat: die Obergrenze fuer die
        # Fensterlaenge, die ein Punkt angibt (siehe _point_interval).
        self._window_interval = None
        self._window_busy = 0.0
        # Upload-Fenster: Summen beim letzten Upload bzw. beim Einschalten
        # des stationaeren Modus.
        self._push_totals = None
        # Zeitpunkt (monotonic) des letzten Uploads. Bleibt beim Aus- und
        # Wiedereinschalten erhalten: nie oefter als alle STAT_INT senden.
        self._last_push = None
        # Neuer Versuch (monotonic), wenn mangels Messwert nichts
        # hochgeladen wurde; sonst None.
        self._push_retry_at = None
        # Zuletzt an den AppState gemeldete Termine, damit er nicht bei
        # jedem Tick neu beschrieben wird.
        self._published = None

        self.last_files = None
        self._fname_25 = None
        self._fname_10 = None
        self._fname_csv = None
        # Laufende Aufzeichnung (siehe _open_files) und ihre Summen fuer
        # die Mittelwerte seit Start.
        self._session = None
        self._session_sum_25 = 0.0
        self._session_sum_10 = 0.0
        # Vorgaengerwerte fuer die KML-Linien.
        self._lat_old = None
        self._lon_old = None
        self._pm_old_25 = '0.0'
        self._pm_old_10 = '0.0'

    def _interval(self):
        """Messintervall in Sekunden."""
        if self._record_interval is not None:
            return self._record_interval
        return self._state.record_interval()

    # -- Dateien ------------------------------------------------------
    def _open_files(self, mode):
        """Beginnt eine neue Aufzeichnung: Dateinamen, Sitzung, Spur.

        Messfahrt: zwei KML-Spuren und eine CSV. Lokal und stationaer nur
        CSV: beide finden an einem festen Ort statt, eine KML-Spur aus
        lauter gleichen Punkten waere nutzlos -- und ohne GPS-Fix
        entstuende sie ohnehin nicht. Angelegt werden die Dateien erst
        mit dem ersten Punkt.
        """
        stamp = _timestamp()
        join = os.path.join
        # Simulierte Messungen erkennt man am Namen -- sonst verwechselt
        # man sie spaeter mit echten.
        pre = 'feinstaub_sim_' if config.is_simulation(self._state.device()[0]) else 'feinstaub_'
        self._files_mode = mode
        self._fname_25 = None
        self._fname_10 = None
        place = u''
        if mode == MODE_TRIP:
            place = self._state.trip_name()
            slug = slugify(place)
            stem = '%s%s_' % (pre, slug) if slug else pre
            self._fname_25 = join(self._outdir, '%s25_line_%s.kml' % (stem, stamp))
            self._fname_10 = join(self._outdir, '%s10_line_%s.kml' % (stem, stamp))
            name = '%s%s.csv' % (stem, stamp)
        elif mode == MODE_LOCAL:
            place = self._state.place()
            slug = slugify(place)
            name = ('%s%s_%s.csv' % (pre, slug, stamp) if slug
                    else '%slokal_%s.csv' % (pre, stamp))
        else:
            name = '%sstationaer_%s.csv' % (pre, stamp)
        self._fname_csv = join(self._outdir, name)
        self._files_open = True
        self._lat_old = None
        self._lon_old = None
        self._session_sum_25 = 0.0
        self._session_sum_10 = 0.0
        self._session = {
            'mode': mode,
            'active': True,
            'started': self._clock(),
            'ended': None,
            'points': 0,
            'avg_pm25': None,
            'avg_pm10': None,
            'file': to_text(name),
            'place': place,
        }
        self._state.set_session(self._session)
        write_log(1, u'Aufzeichnung nach {0}'.format(to_text(self._fname_csv)))
        self.last_files = (self._fname_25, self._fname_10, self._fname_csv)

    def _close_files(self):
        """Beendet die Aufzeichnung (Stop, Moduswechsel, Programmende):
        zuerst das angefangene Fenster als letzter Punkt, dann die
        KML-Dateien abschliessen und die Sitzung beenden."""
        self._flush_window()
        if self._fname_25:
            kml.close_kml(self._fname_25)
        if self._fname_10:
            kml.close_kml(self._fname_10)
        self._files_open = False
        if self._session is not None:
            self._session['active'] = False
            self._session['ended'] = self._clock()
            if not self._session['points']:
                # Ohne Punkt ist keine Datei entstanden; die Anzeige soll
                # keine nennen, die es nicht gibt.
                self._session['file'] = u''
            self._state.set_session(self._session)
        write_log(1, u'Aufzeichnung beendet' if not self._fname_25
                  else u'Aufzeichnung beendet, KML-Dateien abgeschlossen')

    def _flush_window(self):
        """Schreibt das angefangene Fenster als letzten Punkt, wenn seit
        seinem Beginn Sensorwerte kamen. Sonst verwuerfe ein Stop bei
        15 min Intervall bis zu 15 min Messung, und eine kurze Messung
        hinterliesse gar keine Datei.

        Ein Schreibfehler erscheint als Hinweis, haelt das Schliessen aber
        nicht auf: die KML-Dateien muessen trotzdem abgeschlossen werden.
        """
        since = self._window_totals
        if not self._files_open or since is None:
            return
        if self._state.sample_totals()[0] <= since[0]:
            return
        try:
            self._record_step(final=True)
        except Exception as exc:
            self._report(HINT_FAILURE,
                         u'Aufzeichnung gestört: {0}'.format(to_text(exc)))

    # -- Meldungen ----------------------------------------------------
    def _report(self, kind, message):
        """Zeigt einen eigenen Hinweis an. Ins Log kommt er nur, wenn er
        nicht schon angezeigt wird, sonst stuende er bei jedem Versuch erneut
        dort."""
        if self._state.error() != message:
            write_log(0, message)
        self._state.report_error(message)
        self._hints[kind] = message

    def _clear(self, kind):
        """Nimmt den eigenen Hinweis dieser Art zurueck, aber nur, wenn er
        noch angezeigt wird. Eine fremde Meldung bleibt stehen."""
        hint = self._hints[kind]
        if hint is not None and self._state.error() == hint:
            self._state.clear_error()
        self._hints[kind] = None

    def _consequence(self, default):
        """Die Folge fuer den Hinweis "Kein aktueller Messwert".

        Der stationaere Modus zeichnet auf und laedt hoch; mit zwei
        verschiedenen Texten wechselte der Hinweis bei jedem Schritt und
        landete jedes Mal erneut im Log.
        """
        if self._files_open and self._files_mode == MODE_STATIONARY:
            return u'nichts aufgezeichnet, nichts hochgeladen'
        return default

    def _is_fresh(self):
        age = self._state.measurement_age()
        return age is not None and age <= self._max_age

    def _accepts_sleeping_window(self):
        """Im SDS011-Working-Period-Modus sind Werte aus dem Fenster
        brauchbar, auch wenn der letzte Einzelwert inzwischen schlaeft."""
        return self._interval() >= config.SDS011_POWER_SAVE_MIN_INTERVAL

    def _sleep_age_limit(self):
        """So alt darf der letzte Wert waehrend geplanter Schlafphasen sein."""
        return (config.SDS011_POWER_SAVE_PERIOD * 60
                + config.SDS011_POWER_SAVE_SILENCE_SLACK)

    def _is_expected_sleeping(self):
        """True, wenn die Stille zum SDS011-Working-Period-Zyklus passt."""
        age = self._state.measurement_age()
        return (age is not None and self._accepts_sleeping_window()
                and age > self._max_age and age <= self._sleep_age_limit())

    def _has_current_or_sleeping_value(self):
        return self._is_fresh() or self._is_expected_sleeping()

    def _check_fresh(self, fresh, consequence):
        """Zeigt den Hinweis "Kein aktueller Messwert" an, der die Folge
        nennt (consequence, etwa 'nichts aufgezeichnet'), oder raeumt ihn
        weg. Liefert fresh."""
        if fresh:
            self._clear(HINT_STALE)
        else:
            self._report(HINT_STALE,
                         u'Kein aktueller Messwert vom Sensor - {0}.'.format(consequence))
        return fresh

    def _fresh_measurement(self, consequence):
        """(pm_25, pm_10) oder None, wenn kein aktueller Messwert da ist.

        Nach einem Verbindungsabbruch bleibt der letzte Wert im AppState
        stehen. Ohne diese Pruefung wuerde er weiter aufgezeichnet und
        sogar oeffentlich hochgeladen, als waere er frisch. Bei None
        erscheint ein Hinweis (siehe _check_fresh).
        """
        if not self._check_fresh(self._is_fresh(), consequence):
            return None
        return self._state.measurement()

    def _window_mean(self, since, totals):
        """Mittelwert (pm_25, pm_10) der Sensorwerte zwischen zwei Staenden
        von sample_totals(). Ohne Werte dazwischen (Intervall kuerzer als
        der Sensortakt, oder kein Fenster) der aktuelle Messwert."""
        if since is not None:
            count = totals[0] - since[0]
            if count > 0:
                return ((totals[1] - since[1]) / float(count),
                        (totals[2] - since[2]) / float(count))
        return self._state.measurement()

    # -- Ein Messschritt ----------------------------------------------
    def _record_step(self, final=False):
        """Ein Messpunkt: Mittelwert des Fensters bilden und in den
        Verlauf haengen. Laeuft eine Messung, zuerst eine CSV-Zeile, bei
        Messfahrt mit GPS-Fix zusaetzlich je ein KML-Segment fuer PM2.5
        und PM10, und die Mittelwerte seit Start in Sitzung und Status.

        Ohne aktuellen Messwert entsteht kein Punkt; nur bei laufender
        Messung erscheint dann ein Hinweis. Das naechste Fenster zaehlt in
        jedem Fall ab hier. final: das angefangene Fenster beim Schliessen
        (siehe _flush_window).
        """
        totals = self._state.sample_totals()
        since = self._window_totals
        self._window_totals = totals
        recording = self._files_open
        count = totals[0] - since[0] if since is not None else 0

        # Kamen in diesem Fenster Werte, ist ihr Mittelwert aktuell, auch
        # wenn der letzte davon schon aelter als max_age ist. Sonst
        # verwuerfe bei 15 min Intervall ein kurzer Aussetzer am
        # Fensterende die ganze Viertelstunde. Ohne Werte im Fenster
        # entscheidet das Alter des letzten Messwerts.
        fresh = count > 0 or self._is_fresh()
        if recording:
            self._check_fresh(fresh, self._consequence(u'nichts aufgezeichnet'))
        if not fresh:
            # Die Spur nach der Luecke neu beginnen, statt eine gerade
            # Linie ueber den ganzen Ausfall zu ziehen.
            self._lat_old = None
            self._lon_old = None
            return

        mean_25, mean_10 = self._window_mean(since, totals)
        text_25 = _value(mean_25)
        text_10 = _value(mean_10)
        pm_25 = float(text_25)
        pm_10 = float(text_10)
        epoch = self._clock()
        interval = self._point_interval(final)
        if not recording:
            # Ohne Messung nur als Vorschau im Diagramm.
            self._state.add_history_point(epoch, pm_25, pm_10, interval, False)
            return

        try:
            self._write_point(text_25, text_10, pm_25, pm_10)
        except Exception:
            # Im Diagramm erscheint der Wert trotzdem, nur nicht als
            # gespeichert. Den Hinweis zeigt run().
            self._state.add_history_point(epoch, pm_25, pm_10, interval, False)
            raise
        self._state.add_history_point(epoch, pm_25, pm_10, interval, True)
        self._count_point(pm_25, pm_10, announce=not final)
        # Erst nach einem gelungenen Schreiben: ein bleibender
        # Schreibfehler soll nicht bei jedem Versuch kurz verschwinden.
        self._clear(HINT_FAILURE)

    def _point_interval(self, final=False):
        """Ueber wie viele Sekunden der faellige Punkt gemittelt hat. Das
        Diagramm unterbricht die Linie erst ab dem 2,5-Fachen davon und
        laesst das Band "gespeichert" bei Punkt minus Intervall beginnen.

        Meist ist das das eingestellte Messintervall. Laenger ist das
        Fenster, wenn das Intervall verkuerzt wurde (der Punkt ist dann
        sofort faellig und mittelt z. B. die bisherigen 10 von 15 min)
        oder ein Upload den Thread aufgehalten hat. Dann zaehlt die
        tatsaechliche Fensterlaenge, sonst zeigte das Diagramm eine
        Luecke, wo keine ist.

        Die Fensterlaenge ist gedeckelt auf das Intervall bei
        Fensterbeginn plus die Zeit im Upload. Waehrend des Uploads kamen
        die Sensorwerte weiter (eigener Thread), sie stecken also im
        Mittelwert. Schlief das Geraet dagegen, ist das Fenster lang, aber
        Werte kamen keine; mit der vollen Laenge wuerden Linie und Band
        die Pause ueberbruecken. Dasselbe gilt fuer eine vorgestellte Uhr
        (unter Python 2 ist _now nur time.time).

        final: das angefangene Fenster bei Stop, Wechsel oder Ende. Es
        ist kuerzer als das Intervall und traegt seine echte Laenge, sonst
        begaenne das Band "gespeichert" vor dem Start der Messung.
        """
        if self._window_start is None:
            return self._interval()
        span = min(max(0.0, _now() - self._window_start),
                   self._window_interval + self._window_busy)
        if final:
            return span
        interval = self._interval()
        return span if span > interval else interval

    def _write_point(self, text_25, text_10, pm_25, pm_10):
        """Schreibt einen Punkt in CSV und bei Messfahrt mit Fix in die
        KML-Spuren. Schreibfehler gehen an den Aufrufer."""
        lat, lon, utc = self._state.position()
        # Nur eine aktuelle Position zaehlt. Die letzte bekannte kann
        # von gestern sein, und ohne Signal bleibt sie einfach stehen.
        gps_age = self._state.gps_age()
        has_fix = (gps_age is not None and gps_age <= self._gps_max_age
                   and -90 <= lat <= 90 and lat != 0)
        if not has_fix:
            self._lat_old = None
            self._lon_old = None

        # Linie nur mit Fix -- und nur bei der Messfahrt; lokal und
        # stationaer gibt es keine Spur.
        if self._files_mode == MODE_TRIP and has_fix:
            if self._lat_old is None:
                self._lat_old = lat
                self._lon_old = lon
                # Auch die Messwerte, sonst zieht das erste Placemark
                # eine senkrechte Linie von 0 auf den aktuellen Wert.
                self._pm_old_25 = text_25
                self._pm_old_10 = text_10

            kml.write_kml_line(
                text_25, self._pm_old_25, _coord(self._lon_old),
                _coord(self._lat_old), _coord(lat), _coord(lon), str(utc),
                self._fname_25, '25', kml.color_selection(pm_25))
            kml.write_kml_line(
                text_10, self._pm_old_10, _coord(self._lon_old),
                _coord(self._lat_old), _coord(lat), _coord(lon), str(utc),
                self._fname_10, '10', kml.color_selection(pm_10))

            self._lat_old = lat
            self._lon_old = lon
            self._pm_old_25 = text_25
            self._pm_old_10 = text_10

        kml.write_csv(
            text_25, text_10,
            _coord(lat) if has_fix else '', _coord(lon) if has_fix else '',
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            self._fname_csv)

    def _count_point(self, pm_25, pm_10, announce=True):
        """Zaehlt einen geschriebenen Punkt in die Sitzung und zeigt die
        Mittelwerte seit Start an. announce=False beim letzten Punkt nach
        dem Stop: dann bleibt der Statustext der Oberflaeche stehen."""
        session = self._session
        session['points'] += 1
        self._session_sum_25 += pm_25
        self._session_sum_10 += pm_10
        session['avg_pm25'] = self._session_sum_25 / session['points']
        session['avg_pm10'] = self._session_sum_10 / session['points']
        self._state.set_session(session)
        # Im stationaeren Modus bleibt die Meldung zum letzten Upload stehen.
        if announce and self._files_mode != MODE_STATIONARY:
            self._state.set_status(u'Mittelwerte: {0:.1f}, {1:.1f}'.format(
                session['avg_pm10'], session['avg_pm25']))

    # -- Stationaerer Modus -------------------------------------------
    def _push_step(self):
        """Laedt den Mittelwert seit dem letzten Upload (bzw. seit dem
        Einschalten) zu luftdaten (sensor.community) hoch.

        Liefert False, wenn mangels aktuellem Messwert nichts gesendet
        wurde, sonst True -- auch wenn der Upload scheiterte.
        """
        totals = self._state.sample_totals()
        if config.is_simulation(self._state.device()[0]):
            # Die Oberflaeche und /staton/ sperren das schon; hier die
            # letzte Sicherung, falls doch (etwa eine veraltete Seite):
            # erfundene Werte nie in den oeffentlichen Datensatz.
            self._push_totals = totals
            message = u'Simulierter Sensor - nichts hochgeladen.'
            if self._state.error() != message:
                write_log(1, message)
            self._state.report_error(message)
            self._uploaded(False, message)
            return True
        count = totals[0] - self._push_totals[0] if self._push_totals is not None else 0
        if count <= 0 and self._is_expected_sleeping():
            self._clear(HINT_STALE)
            return False
        if count <= 0 or not self._accepts_sleeping_window():
            fresh = self._is_fresh()
        else:
            fresh = True
        if not self._check_fresh(fresh, self._consequence(u'nichts hochgeladen')):
            # Das Upload-Fenster beginnt hier neu. Sonst mittelte der
            # naechste Versuch (nach PUSH_RETRY s, wenn der Sensor wieder
            # liefert) bis zu STAT_INT s alte Werte von vor dem Ausfall
            # mit ein paar neuen.
            self._push_totals = totals
            return False
        pm_25, pm_10 = self._window_mean(self._push_totals, totals)
        self._push_totals = totals
        headers = {
            'Content-Type': 'application/json',
            'X-Pin': '1',
            'X-Sensor': config.XSENSOR,
        }
        # P1 = PM10, P2 = PM2.5, Werte als Text -- so erwartet es die API.
        data = json.dumps({
            'software_version': SOFTWARE_VERSION,
            'sensordatavalues': [
                {'value_type': 'P1', 'value': _value(pm_10)},
                {'value_type': 'P2', 'value': _value(pm_25)},
            ],
        })
        try:
            status_code = self._send(data, headers)
        except Exception as exc:
            # Kein Netz darf den Thread nicht beenden; der naechste
            # Versuch folgt nach STAT_INT.
            message = u'Fehler bei Datenübertragung: {0}'.format(to_text(exc))
            self._state.report_error(message)
            write_log(0, u'Upload fehlgeschlagen: {0}'.format(to_text(exc)))
            self._uploaded(False, message)
            return True

        if status_code == 201:
            self._state.clear_error()
            text = u'{0}: Daten zu luftdaten übertragen.'.format(
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            self._state.set_status(text)
            write_log(1, text)
            self._uploaded(True, u'Daten zu luftdaten übertragen.')
        else:
            message = u'Fehler bei Datenübertragung, Status Code {0}.'.format(status_code)
            self._state.report_error(message)
            write_log(0, u'Upload Status Code {0}'.format(status_code))
            self._uploaded(False, message)
        return True

    def _uploaded(self, ok, message):
        now = self._clock()
        self._set_upload_info(last_at=now, last_ok=ok, last_message=message,
                              next_at=now + self._stat_interval)

    def _set_upload_info(self, **fields):
        """Aendert einzelne Felder der Upload-Anzeige im AppState."""
        info = self._state.upload_info() or {
            'last_at': None, 'last_ok': None, 'last_message': u'', 'next_at': None}
        info.update(fields)
        self._state.set_upload_info(info)

    def _send(self, data, headers):
        """POST zu luftdaten, liefert den HTTP-Statuscode.

        Scheitert HTTPS dauerhaft an TLS (siehe is_tls_error), wird sofort
        ueber HTTP wiederholt, und alle weiteren Uploads bleiben bei HTTP.
        """
        url = upload_url(config.LUFTDATEN_URL,
                         have_ssl=False if self._plain_http else None)
        try:
            return post_json(url, data, headers, timeout=self.UPLOAD_TIMEOUT)
        except Exception as exc:
            if not url.startswith('https://') or not is_tls_error(exc):
                raise
            write_log(0, u'HTTPS fehlgeschlagen ({0}), Upload ab jetzt ueber HTTP'
                      .format(to_text(exc)))
            self._plain_http = True
            return post_json(upload_url(url, have_ssl=False), data, headers,
                             timeout=self.UPLOAD_TIMEOUT)

    def _push(self):
        """Ein faelliger Upload, mit der Planung des naechsten."""
        started = _now()
        sent = self._push_step()
        # So lange stand die Aufzeichnung; das laufende Fenster ist um
        # diese Zeit laenger (siehe _point_interval). Mehr als zwei
        # Timeouts (HTTPS und HTTP-Rueckfall) ist eher Schlaf, den unter
        # Python 2 time.time mitzaehlt.
        self._window_busy += min(max(0.0, _now() - started), 2 * self.UPLOAD_TIMEOUT)
        if sent:
            self._last_push = _now()
            self._push_retry_at = None
        else:
            # Ohne aktuellen Messwert (etwa direkt nach dem Verbinden)
            # bald wieder versuchen statt erst nach STAT_INT.
            self._push_retry_at = _now() + min(self._interval(), self.PUSH_RETRY)

    def _push_due(self, now):
        """Wann (monotonic) der naechste Upload faellig ist: beim ersten
        Mal sofort, danach STAT_INT nach dem letzten."""
        if self._push_retry_at is not None:
            return self._push_retry_at
        if self._last_push is None:
            return now
        since = now - self._last_push
        if since < 0:
            # Uhr zurueckgestellt (unter Python 2 ist _now nur time.time).
            return now
        return self._last_push + self._stat_interval

    # -- Ablauf -------------------------------------------------------
    def _mode(self):
        """Der aktive Modus laut AppState oder None."""
        if self._state.recording:
            return MODE_TRIP
        if self._state.local:
            return MODE_LOCAL
        if self._state.stationary:
            return MODE_STATIONARY
        return None

    def _wait_in_mode(self, seconds, mode):
        """Wartet, reagiert aber in Tick-Abstand auf einen Moduswechsel.

        Gewartet wird gegen eine feste Deadline statt in Schritten
        herunterzuzaehlen: jeder Event.wait() kostet etwas Overhead, der
        sich sonst aufaddiert.

        Liefert True, wenn vorzeitig abgebrochen wurde (Beenden oder
        Moduswechsel).
        """
        deadline = _now() + seconds
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                return False
            step = self._tick if self._tick < remaining else remaining
            if self._state.wait(step):
                return True
            if self._mode() != mode:
                return True

    def _wait_until_due(self, mode):
        """Wartet in Tick-Schritten, bis ein Punkt oder (stationaer) ein
        Upload faellig ist. Liefert (punkt_faellig, upload_faellig) oder
        None, wenn vorher beendet oder der Modus gewechselt wurde.

        Die Termine werden bei jedem Tick neu berechnet: wird das
        Messintervall in der Oberflaeche verkuerzt, ist der Punkt evtl.
        sofort faellig. Wichtig ist das schnelle Reagieren auch fuer Stop
        (sonst bleiben die KML-Dateien ein ganzes Intervall lang
        unabgeschlossen) und fuer den stationaeren Modus, der sonst bis zu
        STAT_INT Sekunden lang den Start einer Messfahrt verschluckt.
        Gewartet wird bis genau zum Termin, nicht in festen Schritten,
        damit sich der Overhead von Event.wait() nicht aufaddiert.
        """
        while True:
            # Kommen wieder Werte, verschwindet der Hinweis "Kein aktueller
            # Messwert" gleich, nicht erst mit dem naechsten Punkt -- bei
            # 15 min Intervall stuende er sonst bis zu 15 min neben
            # frischen Live-Werten.
            if (self._hints[HINT_STALE] is not None
                    and self._has_current_or_sleeping_value()):
                self._clear(HINT_STALE)
            now = _now()
            record_at = self._window_start + self._interval()
            push_at = self._push_due(now) if mode == MODE_STATIONARY else None
            self._publish(now, record_at, push_at)
            record_due = now >= record_at
            push_due = push_at is not None and now >= push_at
            if record_due or push_due:
                return record_due, push_due
            next_at = record_at if push_at is None else min(record_at, push_at)
            if self._state.wait(min(self._tick, next_at - now)):
                return None
            if self._mode() != mode:
                return None

    def _publish(self, now, record_at, push_at):
        """Meldet die naechsten Termine als Wanduhrzeit an den AppState,
        fuer die Anzeige "naechster Punkt in ...". Nur bei Aenderung."""
        if (record_at, push_at) == self._published:
            return
        self._published = (record_at, push_at)
        wall = self._clock()
        self._state.set_next_point_at(wall + max(0.0, record_at - now))
        if push_at is not None:
            self._set_upload_info(next_at=wall + max(0.0, push_at - now))

    def _start_window(self):
        """Neues Aufzeichnungsfenster ab jetzt: der naechste Punkt mittelt
        alle Sensorwerte ab hier."""
        self._window_start = _now()
        self._window_interval = self._interval()
        self._window_busy = 0.0
        self._window_totals = self._state.sample_totals()

    def _advance_window(self):
        """Das naechste Fenster beginnt dort, wo der eben faellige Punkt
        faellig war -- so summiert sich keine Verspaetung auf. Liegt das
        mehr als ein Intervall zurueck (das Geraet schlief), beginnt es
        jetzt, sonst kaemen die verpassten Punkte alle auf einmal."""
        now = _now()
        interval = self._interval()
        due_at = self._window_start + interval
        if now - due_at > interval:
            self._window_start = now
        else:
            self._window_start = min(due_at, now)
        self._window_interval = interval
        self._window_busy = 0.0

    def _run_once(self):
        """Ein Durchlauf der Hauptschleife.

        Wechselt der Modus, werden alte Dateien geschlossen, neue
        geoeffnet und ein neues Fenster begonnen. Dann wird gewartet, bis
        ein Punkt (jedes Messintervall, auch ohne Modus fuer den Verlauf)
        oder ein Upload (nur stationaer) faellig ist. Beim Stop werden
        ausserdem eigene Hinweise weggeraeumt.
        """
        mode = self._mode()
        # Auch ein direkter Wechsel Messfahrt <-> lokal ohne Stop
        # braucht neue Dateien.
        if self._files_open and mode != self._files_mode:
            if mode is None:
                # Gestoppt: die Hinweise der Messung sind erledigt. Vor dem
                # Schliessen, damit ein Fehler beim letzten Punkt (siehe
                # _flush_window) stehen bleibt.
                self._clear(HINT_STALE)
                self._clear(HINT_FAILURE)
            self._close_files()

        if self._window_start is None or mode != self._window_mode:
            if self._window_mode == MODE_STATIONARY and mode != MODE_STATIONARY:
                self._set_upload_info(next_at=None)
            self._window_mode = mode
            self._start_window()
            if mode == MODE_STATIONARY:
                self._push_totals = self._window_totals
                self._push_retry_at = None

        if mode is not None and not self._files_open:
            self._open_files(mode)

        due = self._wait_until_due(mode)
        if due is None:
            return
        record_due, push_due = due
        if record_due:
            try:
                self._record_step()
            finally:
                self._advance_window()
        if push_due:
            self._push()

    def run(self):
        while self._state.sensing:
            try:
                self._run_once()
            except Exception as exc:
                # Etwa Speicher voll oder Ordner weg. Der Thread darf daran
                # nicht still sterben, waehrend die Oberflaeche weiter
                # "aktiv" zeigt. Das Fenster ist schon weitergerueckt,
                # der naechste Versuch kommt mit dem naechsten Punkt.
                self._report(HINT_FAILURE,
                             u'Aufzeichnung gestört: {0}'.format(to_text(exc)))
                self._wait_in_mode(self._tick, self._mode())

        # Auch beim Beenden kommt das angefangene Fenster noch in die Datei.
        if self._files_open:
            self._close_files()
        # Geplant ist nichts mehr.
        self._state.set_next_point_at(None)
        if self._state.upload_info() is not None:
            self._set_upload_info(next_at=None)
        write_log(0, u'sensingStop!')
