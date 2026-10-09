# -*- coding: utf-8 -*-
"""Aufzeichnung (KML/CSV) und stationaerer Modus.

Entspricht der frueheren Funktion start_sensor(). Alle Wartezeiten
laufen ueber state.wait(), damit das Programm sich beenden laesst,
ohne bis zu vier Minuten am sleep(240) zu haengen.
"""

from __future__ import absolute_import

import datetime
import os
import threading
import time

import config
import kml
from logging_util import write_log

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

    str(51.4391) liefert je nach Rechenweg 51.439099999999996 --
    dieses Float-Rauschen stand bisher in CSV und KML. Sechs
    Nachkommastellen entsprechen etwa 11 cm und sind damit deutlich
    genauer als jedes Handy-GPS.
    """
    return '%.6f' % value


_UMLAUTS = [(u'ä', u'ae'), (u'ö', u'oe'), (u'ü', u'ue'),
            (u'Ä', u'ae'), (u'Ö', u'oe'), (u'Ü', u'ue'),
            (u'ß', u'ss')]


def slugify(text, maxlen=40):
    """Freitext in einen Dateinamen-Baustein verwandeln.

    "Kletterhalle Duisburg" -> "kletterhalle_duisburg". Leerer oder
    unbrauchbarer Text ergibt '', dann bleibt der Dateiname wie bisher.
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


def _timestamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H_%M_%S')


class Recorder(threading.Thread):

    # Wie oft geprueft wird, ob eine Taste gedrueckt wurde.
    TICK = 0.5

    def __init__(self, state, outdir=None, kml_interval=None,
                 stat_interval=None, tick=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._outdir = outdir or config.OUTDIR
        # Ueberschreibbar, damit Tests nicht 5 Sekunden warten muessen.
        self._kml_interval = config.KML_INT if kml_interval is None else kml_interval
        self._stat_interval = config.STAT_INT if stat_interval is None else stat_interval
        # Wie schnell ein Tastendruck bemerkt wird.
        self._tick = self.TICK if tick is None else tick
        self._files_open = False
        self._local_run = False
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
        """Legt die Dateinamen fuer eine Aufzeichnung fest.

        Die lokale Messung schreibt nur CSV: sie findet an einem festen
        Ort statt, eine KML-Spur aus lauter gleichen Punkten waere
        nutzlos -- und ohne GPS-Fix entstuende sie ohnehin nicht.
        """
        stamp = _timestamp()
        join = os.path.join
        self._local_run = local
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
        write_log(1, 'Aufzeichnung nach {0}'.format(self._fname_csv))
        self.last_files = (self._fname_25, self._fname_10, self._fname_csv)

    def _close_files(self):
        if self._fname_25:
            kml.close_kml(self._fname_25)
        if self._fname_10:
            kml.close_kml(self._fname_10)
        self._files_open = False
        write_log(1, 'KML-Dateien abgeschlossen')

    # -- Ein Messschritt ----------------------------------------------
    def _record_step(self):
        pm_25, pm_10 = self._state.measurement()
        lat, lon, utc = self._state.position()

        # Nur mit gueltigem Fix eine Linie zeichnen -- und nicht bei
        # der lokalen Messung, die gar keine Spur erzeugt.
        if not self._local_run and -90 <= lat <= 90 and lat != 0:
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
            str(pm_25), str(pm_10), _coord(lat), _coord(lon),
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            self._fname_csv)

        self._pm_10_sum += pm_10
        self._pm_25_sum += pm_25
        self._avg_count += 1
        self._state.set_status(u'Mittelwerte: {0:.1f}, {1:.1f}'.format(
            self._pm_10_sum / self._avg_count,
            self._pm_25_sum / self._avg_count))

    # -- Stationaerer Modus -------------------------------------------
    def _push_step(self):
        pm_25, pm_10 = self._state.measurement()
        headers = {
            'Content-Type': 'application/json',
            'X-Pin': '1',
            'X-Sensor': config.XSENSOR,
        }
        data = ('{"software_version": "your_version", "sensordatavalues":'
                '[{"value_type":"P1","value":"%s"},'
                '{"value_type":"P2","value":"%s"}]}' % (pm_10, pm_25))
        try:
            status_code = post_json(upload_url(config.LUFTDATEN_URL), data, headers)
        except Exception as exc:
            # Vorher stuerzte der Thread hier ohne Netz komplett ab.
            self._state.report_error(u'Fehler bei Datenübertragung: {0}'.format(exc))
            write_log(0, 'Upload fehlgeschlagen: {0}'.format(exc))
            return

        if status_code == 201:
            self._state.clear_error()
            text = u'{0}: Daten zu luftdaten übertragen.'.format(
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            self._state.set_status(text)
            write_log(1, text)
        else:
            # Lief frueher ohne 'global' ins Leere und erreichte das
            # Frontend nie.
            self._state.report_error(
                u'Fehler bei Datenübertragung, Status Code {0}.'.format(status_code))
            write_log(0, 'Upload Status Code {0}'.format(status_code))

    def _wait_recording(self, seconds):
        """Wartet zwischen zwei Messwerten, reagiert dabei aber in
        Tick-Abstand auf Stop. Sonst blieben die KML-Dateien nach dem
        Stop-Klick bis zu KML_INT Sekunden unabgeschlossen -- und ein
        unabgeschlossenes KML ist in Google Earth wertlos.

        Gegen eine feste Deadline gewartet, nicht in nominalen Schritten
        heruntergezaehlt: jeder Event.wait() kostet etwas Timer-Overhead,
        der sich sonst aufaddiert und das Messintervall verschiebt.

        Liefert True, wenn vorzeitig abgebrochen wurde.
        """
        deadline = _now() + seconds
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                return False
            step = self._tick if self._tick < remaining else remaining
            if self._state.wait(step):
                return True
            if not self._state.recording:
                return True

    # -- Hauptschleife ------------------------------------------------
    def run(self):
        while self._state.sensing:
            writing = self._state.recording or self._state.local
            if writing:
                if not self._files_open:
                    self._open_files(local=self._state.local)
                self._wait_recording(self._kml_interval)
                if not self._state.sensing:
                    break
                if self._state.recording or self._state.local:
                    self._record_step()
                continue

            if self._files_open:
                self._close_files()

            if self._state.stationary:
                self._push_step()
                if self._state.wait(self._stat_interval):
                    break
                continue

            if self._state.wait(self._tick):
                break

        if self._files_open:
            self._close_files()
        write_log(0, 'sensingStop!')
