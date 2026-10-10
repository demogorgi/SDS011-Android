# -*- coding: utf-8 -*-
"""Aufzeichnung (KML/CSV) und Upload im stationaeren Modus.

main.py startet den Recorder als Thread. Er liest Messwert und Position
aus dem AppState (state.py), den Sensor selbst liest er nicht. Alle
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
    """Thread, der je nach Modus aufzeichnet oder hochlaedt.

    Laeuft, solange state.sensing gesetzt ist, und schliesst zum Schluss
    offene KML-Dateien. Eigene Probleme zeigt er als Hinweis in der
    Oberflaeche an, statt still zu sterben.
    """

    # Wie oft geprueft wird, ob eine Taste gedrueckt wurde.
    TICK = 0.5

    def __init__(self, state, outdir=None, kml_interval=None,
                 stat_interval=None, tick=None, max_age=None, gps_max_age=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._outdir = outdir or config.OUTDIR
        # Die Parameter ausser state sind fuer Tests, damit sie nicht
        # KML_INT oder STAT_INT Sekunden warten muessen.
        self._kml_interval = config.KML_INT if kml_interval is None else kml_interval
        self._stat_interval = config.STAT_INT if stat_interval is None else stat_interval
        self._tick = self.TICK if tick is None else tick
        self._max_age = config.MAX_MEASUREMENT_AGE if max_age is None else max_age
        self._gps_max_age = config.GPS_MAX_AGE if gps_max_age is None else gps_max_age
        # Nach einem TLS-Fehler bleibt der Upload bei HTTP.
        self._plain_http = False
        self._files_open = False
        self._files_mode = None
        self._local_run = False
        # Eigene Hinweise in der Oberflaeche, je Art. Nur die raeumt der
        # Recorder wieder weg, nicht etwa einen Verbindungsfehler.
        self._hints = {HINT_STALE: None, HINT_FAILURE: None}
        # Zeitpunkt (monotonic) des letzten Uploads. Bleibt beim Aus- und
        # Wiedereinschalten erhalten: nie oefter als alle STAT_INT senden.
        self._last_push = None
        self.last_files = None
        self._fname_25 = None
        self._fname_10 = None
        self._fname_csv = None
        self._reset_averages()
        # Vorgaengerwerte fuer die KML-Linien.
        self._lat_old = None
        self._lon_old = None
        self._pm_old_25 = 0
        self._pm_old_10 = 0

    # -- Dateien ------------------------------------------------------
    def _reset_averages(self):
        self._pm_10_sum = 0.0
        self._pm_25_sum = 0.0
        self._avg_count = 0

    def _open_files(self, local=False):
        """Beginnt eine neue Aufzeichnung: Dateinamen, Mittelwerte, Spur.

        Die lokale Messung schreibt nur CSV: sie findet an einem festen
        Ort statt, eine KML-Spur aus lauter gleichen Punkten waere
        nutzlos -- und ohne GPS-Fix entstuende sie ohnehin nicht.
        """
        stamp = _timestamp()
        join = os.path.join
        self._local_run = local
        self._files_mode = MODE_LOCAL if local else MODE_TRIP
        if local:
            slug = slugify(self._state.place())
            name = 'feinstaub_%s_%s.csv' % (slug, stamp) if slug                 else 'feinstaub_lokal_%s.csv' % stamp
            self._fname_25 = None
            self._fname_10 = None
            self._fname_csv = join(self._outdir, name)
        else:
            self._fname_25 = join(self._outdir, 'feinstaub_25_line_%s.kml' % stamp)
            self._fname_10 = join(self._outdir, 'feinstaub_10_line_%s.kml' % stamp)
            self._fname_csv = join(self._outdir, 'feinstaub_%s.csv' % stamp)
        self._files_open = True
        self._reset_averages()
        self._lat_old = None
        self._lon_old = None
        write_log(1, u'Aufzeichnung nach {0}'.format(to_text(self._fname_csv)))
        self.last_files = (self._fname_25, self._fname_10, self._fname_csv)

    def _close_files(self):
        if self._fname_25:
            kml.close_kml(self._fname_25)
        if self._fname_10:
            kml.close_kml(self._fname_10)
        self._files_open = False
        write_log(1, 'KML-Dateien abgeschlossen')

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

    def _fresh_measurement(self, consequence):
        """(pm_25, pm_10) oder None, wenn kein aktueller Messwert da ist.

        Nach einem Verbindungsabbruch bleibt der letzte Wert im AppState
        stehen. Ohne diese Pruefung wuerde er weiter aufgezeichnet und
        sogar oeffentlich hochgeladen, als waere er frisch. Bei None
        erscheint ein Hinweis, der die Folge nennt (consequence, etwa
        'nichts aufgezeichnet').
        """
        age = self._state.measurement_age()
        if age is None or age > self._max_age:
            self._report(HINT_STALE,
                         u'Kein aktueller Messwert vom Sensor - {0}.'.format(consequence))
            return None
        self._clear(HINT_STALE)
        return self._state.measurement()

    # -- Ein Messschritt ----------------------------------------------
    def _record_step(self):
        """Ein Messpunkt: CSV-Zeile, bei Messfahrt mit GPS-Fix zusaetzlich
        je ein KML-Segment fuer PM2.5 und PM10. Zeigt die Mittelwerte im
        Status an. Ohne aktuellen Messwert wird nichts geschrieben."""
        values = self._fresh_measurement(u'nichts aufgezeichnet')
        if values is None:
            # Die Spur nach der Luecke neu beginnen, statt eine gerade
            # Linie ueber den ganzen Ausfall zu ziehen.
            self._lat_old = None
            self._lon_old = None
            return
        pm_25, pm_10 = values
        lat, lon, utc = self._state.position()
        # Nur eine aktuelle Position zaehlt. Die letzte bekannte kann
        # von gestern sein, und ohne Signal bleibt sie einfach stehen.
        gps_age = self._state.gps_age()
        has_fix = (gps_age is not None and gps_age <= self._gps_max_age
                   and -90 <= lat <= 90 and lat != 0)
        if not has_fix:
            self._lat_old = None
            self._lon_old = None

        # Linie nur mit Fix -- und nicht bei der lokalen Messung, die gar
        # keine Spur erzeugt.
        if not self._local_run and has_fix:
            if self._lat_old is None:
                self._lat_old = lat
                self._lon_old = lon
                # Auch die Messwerte, sonst zieht das erste Placemark
                # eine senkrechte Linie von 0 auf den aktuellen Wert.
                self._pm_old_25 = pm_25
                self._pm_old_10 = pm_10

            kml.write_kml_line(
                str(pm_25), str(self._pm_old_25), _coord(self._lon_old),
                _coord(self._lat_old), _coord(lat), _coord(lon), str(utc),
                self._fname_25, '25', kml.color_selection(pm_25))
            kml.write_kml_line(
                str(pm_10), str(self._pm_old_10), _coord(self._lon_old),
                _coord(self._lat_old), _coord(lat), _coord(lon), str(utc),
                self._fname_10, '10', kml.color_selection(pm_10))

            self._lat_old = lat
            self._lon_old = lon
            self._pm_old_25 = pm_25
            self._pm_old_10 = pm_10

        kml.write_csv(
            str(pm_25), str(pm_10),
            _coord(lat) if has_fix else '', _coord(lon) if has_fix else '',
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            self._fname_csv)

        self._pm_10_sum += pm_10
        self._pm_25_sum += pm_25
        self._avg_count += 1
        self._state.set_status(u'Mittelwerte: {0:.1f}, {1:.1f}'.format(
            self._pm_10_sum / self._avg_count,
            self._pm_25_sum / self._avg_count))
        # Erst nach einem gelungenen Schreiben: ein bleibender
        # Schreibfehler soll nicht bei jedem Versuch kurz verschwinden.
        self._clear(HINT_FAILURE)

    # -- Stationaerer Modus -------------------------------------------
    def _push_step(self):
        """Laedt den aktuellen Wert zu luftdaten (sensor.community) hoch.

        Liefert False, wenn mangels aktuellem Messwert nichts gesendet
        wurde, sonst True -- auch wenn der Upload scheiterte.
        """
        values = self._fresh_measurement(u'nichts hochgeladen')
        if values is None:
            return False
        pm_25, pm_10 = values
        headers = {
            'Content-Type': 'application/json',
            'X-Pin': '1',
            'X-Sensor': config.XSENSOR,
        }
        # P1 = PM10, P2 = PM2.5, Werte als Text -- so erwartet es die API.
        data = json.dumps({
            'software_version': SOFTWARE_VERSION,
            'sensordatavalues': [
                {'value_type': 'P1', 'value': str(pm_10)},
                {'value_type': 'P2', 'value': str(pm_25)},
            ],
        })
        try:
            status_code = self._send(data, headers)
        except Exception as exc:
            # Kein Netz darf den Thread nicht beenden; der naechste
            # Versuch folgt nach STAT_INT.
            self._state.report_error(u'Fehler bei Datenübertragung: {0}'.format(to_text(exc)))
            write_log(0, u'Upload fehlgeschlagen: {0}'.format(to_text(exc)))
            return True

        if status_code == 201:
            self._state.clear_error()
            text = u'{0}: Daten zu luftdaten übertragen.'.format(
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            self._state.set_status(text)
            write_log(1, text)
        else:
            self._state.report_error(
                u'Fehler bei Datenübertragung, Status Code {0}.'.format(status_code))
            write_log(0, u'Upload Status Code {0}'.format(status_code))
        return True

    def _send(self, data, headers):
        """POST zu luftdaten, liefert den HTTP-Statuscode.

        Scheitert HTTPS dauerhaft an TLS (siehe is_tls_error), wird sofort
        ueber HTTP wiederholt, und alle weiteren Uploads bleiben bei HTTP.
        """
        url = upload_url(config.LUFTDATEN_URL,
                         have_ssl=False if self._plain_http else None)
        try:
            return post_json(url, data, headers)
        except Exception as exc:
            if not url.startswith('https://') or not is_tls_error(exc):
                raise
            write_log(0, u'HTTPS fehlgeschlagen ({0}), Upload ab jetzt ueber HTTP'
                      .format(to_text(exc)))
            self._plain_http = True
            return post_json(upload_url(url, have_ssl=False), data, headers)

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

        Wichtig fuer Stop (sonst bleiben die KML-Dateien bis zu KML_INT
        Sekunden unabgeschlossen) und fuer den stationaeren Modus, der
        sonst bis zu STAT_INT Sekunden lang den Start einer Messfahrt
        verschluckt.

        Gewartet wird gegen eine feste Deadline statt in Schritten
        herunterzuzaehlen: jeder Event.wait() kostet etwas Overhead, der
        sich sonst aufaddiert und das Messintervall verschiebt.

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

    # -- Hauptschleife ------------------------------------------------
    def _run_once(self):
        """Ein Durchlauf der Hauptschleife, je nach Modus:

        Messfahrt/lokal: KML_INT warten, dann einen Messpunkt schreiben.
        Stationaer: hochladen, dann STAT_INT warten. Kein Modus: eigene
        Hinweise wegraeumen und einen Tick warten.
        """
        mode = self._mode()
        # Auch ein direkter Wechsel Messfahrt <-> lokal ohne Stop
        # braucht neue Dateien.
        if self._files_open and mode != self._files_mode:
            self._close_files()

        if mode in (MODE_TRIP, MODE_LOCAL):
            if not self._files_open:
                self._open_files(local=(mode == MODE_LOCAL))
            if not self._wait_in_mode(self._kml_interval, mode):
                self._record_step()
            return

        if mode == MODE_STATIONARY:
            if self._last_push is not None:
                since = _now() - self._last_push
                if 0 <= since < self._stat_interval:
                    self._wait_in_mode(self._stat_interval - since, mode)
                    return
            if self._push_step():
                self._last_push = _now()
                self._wait_in_mode(self._stat_interval, mode)
            else:
                # Ohne aktuellen Messwert (etwa direkt nach dem Verbinden)
                # bald wieder versuchen statt erst nach STAT_INT.
                self._wait_in_mode(self._kml_interval, mode)
            return

        # Kein Modus aktiv: alte Hinweise sind erledigt.
        self._clear(HINT_STALE)
        self._clear(HINT_FAILURE)
        self._state.wait(self._tick)

    def run(self):
        while self._state.sensing:
            try:
                self._run_once()
            except Exception as exc:
                # Etwa Speicher voll oder Ordner weg. Der Thread darf daran
                # nicht still sterben, waehrend die Oberflaeche weiter
                # "aktiv" zeigt.
                self._report(HINT_FAILURE,
                             u'Aufzeichnung gestört: {0}'.format(to_text(exc)))
                self._wait_in_mode(self._kml_interval, self._mode())

        if self._files_open:
            self._close_files()
        write_log(0, u'sensingStop!')
