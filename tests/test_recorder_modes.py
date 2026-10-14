# -*- coding: utf-8 -*-
"""Recorder: Takt, Moduswechsel, veraltete Messwerte, Schreibfehler.

Laufen mit echten Threads, aber kurzen Intervallen.
"""

from __future__ import absolute_import

import glob
import io
import json
import os
import re
import shutil
import tempfile
import time
import tokenize
import unittest
from xml.etree import ElementTree

import config
import kml
import recorder as recorder_module
from recorder import Recorder
from state import AppState, monotonic


def _csv_rows(directory, skip=None):
    """Messzeilen aller CSV-Dateien, ohne Kopfzeilen; Dateien, deren Name
    skip enthaelt, bleiben aussen vor."""
    rows = []
    for name in sorted(os.listdir(directory)):
        if name.endswith('.csv') and not (skip and skip in name):
            with io.open(os.path.join(directory, name), encoding='utf-8') as fh:
                rows.extend(r for r in fh.read().splitlines()
                            if r and r != kml.CSV_HEADER)
    return rows


def _wait_for(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class RecorderTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = AppState()
        self.state.set_measurement(12.3, 45.6)
        self.state.set_position(51.4385, 6.7882)
        self.state.mark_gps_fix()
        self.recorder = None
        self._saved_post = recorder_module.post_json
        self.posts = []

        def fake_post(url, body, headers, timeout=30):
            self.posts.append(body)
            return 201
        recorder_module.post_json = fake_post

    def tearDown(self):
        self.state.shutdown()
        if self.recorder is not None:
            self.recorder.join(5)
        recorder_module.post_json = self._saved_post
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, **kwargs):
        options = {'outdir': self.tmp, 'record_interval': 0.3, 'tick': 0.02}
        options.update(kwargs)
        self.recorder = Recorder(self.state, **options)
        self.recorder.start()
        return self.recorder


class IntervalTest(RecorderTestCase):

    def test_local_mode_keeps_the_interval(self):
        """Die lokale Messung schrieb jeden Tick (0,5 s) eine Zeile statt
        einmal je Messintervall (5 s) -- zehnmal zu viele, fast nur Duplikate."""
        self.start()
        self.state.local = True
        time.sleep(1.05)
        self.state.local = False
        rows = _csv_rows(self.tmp)
        # 1,05 s bei 0,3 s Intervall: drei Zeilen. Vorher waren es ~50.
        self.assertGreaterEqual(len(rows), 2, rows)
        self.assertLessEqual(len(rows), 4, rows)


class StaleMeasurementTest(RecorderTestCase):

    def test_stale_value_is_not_recorded(self):
        """Nach einem Verbindungsabbruch bleibt der letzte Wert stehen --
        er darf nicht als frische Messung in die Datei."""
        self.state.set_measurement(12.3, 45.6, at=monotonic() - 100)
        self.start(max_age=10)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        self.assertEqual(_csv_rows(self.tmp), [])

        # Kommen wieder Werte, wird wieder geschrieben und der Hinweis
        # verschwindet.
        self.state.set_measurement(20.0, 30.0)
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp)))
        self.assertEqual(self.state.error(), u'')

    def test_missing_value_is_not_recorded(self):
        """Direkt nach dem Verbinden ist noch kein Paket da -- dann darf
        keine Zeile mit 0,0 entstehen."""
        self.state = AppState()
        self.state.set_position(51.4385, 6.7882)
        self.state.mark_gps_fix()
        self.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        time.sleep(0.4)
        self.assertEqual(_csv_rows(self.tmp), [])

    def test_settling_value_is_not_recorded_or_uploaded(self):
        """Rohwerte aus der Einschwingzeit bleiben sichtbar, zaehlen aber
        nicht fuer CSV oder Upload."""
        self.state = AppState()
        self.state.set_position(51.4385, 6.7882)
        self.state.set_measurement(5.0, 8.0, usable=False)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._open_files(recorder_module.MODE_LOCAL)
        rec._record_step()
        self.assertEqual(_csv_rows(self.tmp), [])

        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertFalse(rec._push_step())
        self.assertEqual(self.posts, [])

        self.state.set_measurement(10.0, 20.0, usable=True)
        self.assertTrue(rec._push_step())
        self.assertEqual(len(self.posts), 1)

    def test_track_restarts_after_a_gap(self):
        """Nach einem Ausfall keine gerade Linie ueber die ganze Luecke."""
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._open_files(recorder_module.MODE_TRIP)
        rec._record_step()
        self.assertIsNotNone(rec._lat_old)
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        # Ein Fenster ohne neue Werte: der Sensor schweigt seit 100 s.
        rec._start_window()
        rec._record_step()
        self.assertIsNone(rec._lat_old)

    def test_clock_set_back_counts_as_stale(self):
        """Unter Python 2 ist monotonic nur time.time -- eine
        zurueckgestellte Uhr darf einen alten Wert nicht frisch machen."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() + 100)
        self.assertIsNone(self.state.measurement_age())

    def test_hint_disappears_after_stop(self):
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.start(max_age=10)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: self.state.error()))
        self.state.local = False
        self.assertTrue(_wait_for(lambda: self.state.error() == u''))

    def test_stale_value_is_not_uploaded(self):
        # Der alte Code lud hier den veralteten Wert hoch.
        self.state.set_measurement(12.3, 45.6, at=monotonic() - 100)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertFalse(rec._push_step())
        self.assertEqual(self.posts, [])
        self.assertIn(u'nichts hochgeladen', self.state.error())

    def test_fresh_value_is_uploaded(self):
        # Positivkontrolle: frische Werte gehen weiterhin raus.
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertTrue(rec._push_step())
        self.assertEqual(len(self.posts), 1)
        payload = json.loads(self.posts[0])
        values = {v['value_type']: v['value'] for v in payload['sensordatavalues']}
        self.assertEqual(values, {'P1': '45.6', 'P2': '12.3'})
        self.assertEqual(payload['software_version'], 'SDS011-Android')

    def test_upload_errors_are_not_cleared_by_fresh_values(self):
        """Der Recorder raeumt nur seine eigenen Hinweise weg."""
        self.state.report_error(u'Verbindung zum Sensor verloren')
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._fresh_measurement(u'nichts aufgezeichnet')
        self.assertEqual(self.state.error(), u'Verbindung zum Sensor verloren')

    def test_window_with_values_is_recorded_after_a_short_dropout(self):
        """Bei 15 min Intervall verwarf ein Aussetzer kurz vor dem
        Fensterende die ganze Viertelstunde, obwohl sie Werte hatte."""
        rec = Recorder(self.state, outdir=self.tmp, record_interval=900, max_age=10)
        rec._open_files(recorder_module.MODE_LOCAL)
        rec._start_window()
        self.state.set_measurement(20.0, 30.0, at=monotonic() - 30)
        rec._record_step()
        rows = _csv_rows(self.tmp)
        self.assertEqual([r.split(';')[1:3] for r in rows], [[u'20,0', u'30,0']], rows)
        self.assertEqual(self.state.error(), u'')

    def test_hint_goes_away_while_waiting(self):
        """Der Hinweis stand bis zum naechsten Punkt -- bei 15 min
        Intervall bis zu 15 min neben frischen Live-Werten."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.state.set_record_interval(0.1)
        self.recorder = Recorder(self.state, outdir=self.tmp, tick=0.02, max_age=10)
        self.recorder.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        self.state.set_record_interval(60)
        time.sleep(0.3)
        self.assertIn(u'Kein aktueller Messwert', self.state.error())
        self.state.set_measurement(5.0, 6.0)
        self.assertTrue(_wait_for(lambda: self.state.error() == u'', timeout=1.0),
                        self.state.error())
        # Weggeraeumt hat ihn das Warten, kein neuer Punkt.
        self.assertEqual(_csv_rows(self.tmp), [])

    def test_upload_after_outage_sends_only_new_values(self):
        """Nach einem Ausfall mittelte der erste Upload bis zu STAT_INT
        Sekunden alte Werte von vor dem Ausfall mit ein paar neuen."""
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertTrue(rec._push_step())
        for _ in range(3):                              # vor dem Ausfall
            self.state.set_measurement(100.0, 100.0, at=monotonic() - 100)
        self.assertFalse(rec._push_step())              # Sensor schweigt
        self.state.set_measurement(5.0, 6.0)            # wieder da
        self.assertTrue(rec._push_step())
        values = {v['value_type']: v['value']
                  for v in json.loads(self.posts[-1])['sensordatavalues']}
        self.assertEqual(values, {'P1': '6.0', 'P2': '5.0'})

    def test_power_save_sleep_window_is_uploaded(self):
        """Bei 5 min Messintervall schlaeft der SDS011 planmaessig; der
        Upload darf Werte aus diesem Fenster nicht als veraltet verwerfen."""
        self.state.set_record_interval(300)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertTrue(rec._push_step())
        self.state.set_measurement(10.0, 20.0, at=monotonic() - 100)
        self.assertTrue(rec._push_step())
        values = {v['value_type']: v['value']
                  for v in json.loads(self.posts[-1])['sensordatavalues']}
        self.assertEqual(values, {'P1': '20.0', 'P2': '10.0'})

    def test_power_save_sleep_without_new_values_is_no_error(self):
        """Ist im geplanten Schlaf seit dem letzten Upload noch kein neuer
        Wert gekommen, wird nichts gesendet, aber auch kein Ausfall gemeldet."""
        self.state.set_record_interval(300)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        self.assertTrue(rec._push_step())
        self.posts[:] = []
        self.state.set_measurement(12.3, 45.6, at=monotonic() - 100)
        rec._push_totals = self.state.sample_totals()
        self.assertFalse(rec._push_step())
        self.assertEqual(self.posts, [])
        self.assertEqual(self.state.error(), u'')

    def test_stale_hint_clears_during_power_save_sleep(self):
        """Der rote Hinweis darf im geplanten 5-min-Sensorzyklus nicht
        stehen bleiben, waehrend der naechste Punkt erst in Minuten kommt."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.state.set_record_interval(0.1)
        self.recorder = Recorder(self.state, outdir=self.tmp, tick=0.02, max_age=10)
        self.recorder.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Kein aktueller Messwert' in self.state.error()))
        self.state.set_record_interval(300)
        self.assertTrue(_wait_for(lambda: self.state.error() == u'', timeout=1.0),
                        self.state.error())


class ModeSwitchTest(RecorderTestCase):

    def test_trip_starts_promptly_after_stationary(self):
        """Der stationaere Modus wartete STAT_INT (240 s) am Stueck --
        eine danach gestartete Messfahrt begann erst Minuten spaeter."""
        self.start(stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: self.posts))
        self.state.stationary = False
        self.state.recording = True
        # Der stationaere Modus schreibt eine eigene CSV; gezaehlt wird
        # nur die der Messfahrt.
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp, skip='stationaer'),
                                  timeout=2.0),
                        'Messfahrt hat nach 2 s noch nichts geschrieben')

    def test_stationary_retries_soon_without_value(self):
        """Ohne aktuellen Wert wartet stationaer nur bis zum naechsten
        Messpunkt, nicht auf einen separaten Upload-Timer."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.start(stat_interval=60, max_age=10)
        self.state.stationary = True
        time.sleep(0.2)
        self.assertEqual(self.posts, [])
        self.state.set_measurement(3.0, 4.0)
        self.assertTrue(_wait_for(lambda: self.posts, timeout=2.0))

    def test_switch_without_stop_gets_new_files(self):
        """Lokal -> Messfahrt ohne Stop schrieb die Fahrt in die
        lokale CSV, ohne KML."""
        self.state.set_place(u'Halle')
        self.start()
        self.state.local = True
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp)))
        # Reihenfolge wie in /start/: recording zuerst, local danach --
        # der Recorder sieht also direkt LOCAL -> TRIP.
        self.state.recording = True
        self.state.local = False

        def done():
            files = os.listdir(self.tmp)
            return (len([f for f in files if f.endswith('.csv')]) == 2
                    and len([f for f in files if f.endswith('.kml')]) == 2)
        self.assertTrue(_wait_for(done), os.listdir(self.tmp))

    def test_toggling_stationary_does_not_upload_more_often(self):
        """Aus- und wieder einschalten darf keinen Sofort-Upload ausloesen;
        gesendet wird erst mit einem neuen Messpunkt."""
        self.start(stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: self.posts))
        for _ in range(3):
            self.state.stationary = False
            time.sleep(0.1)
            self.state.stationary = True
            time.sleep(0.1)
        self.assertEqual(len(self.posts), 1)


class WriteErrorTest(RecorderTestCase):

    def test_write_error_does_not_kill_the_recorder(self):
        """Speicher voll o. ae.: der Thread starb still, die Oberflaeche
        zeigte weiter "aktiv"."""
        calls = []
        original = kml.write_csv

        def flaky(*args):
            calls.append(1)
            if len(calls) <= 3:
                raise IOError('No space left on device')
            return original(*args)

        kml.write_csv = flaky
        self.addCleanup(setattr, kml, 'write_csv', original)
        self.start(record_interval=0.1)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: u'Aufzeichnung gestört' in self.state.error()))
        self.assertTrue(self.recorder.is_alive())

        # Solange es scheitert, bleibt der Hinweis stehen -- er
        # verschwindet erst nach dem ersten gelungenen Schreiben.
        seen_empty_before_success = False
        deadline = time.time() + 3.0
        while time.time() < deadline and not _csv_rows(self.tmp):
            if self.state.error() == u'' and not _csv_rows(self.tmp):
                seen_empty_before_success = True
            time.sleep(0.005)
        self.assertTrue(_csv_rows(self.tmp))
        self.assertFalse(seen_empty_before_success)
        self.assertTrue(_wait_for(lambda: self.state.error() == u''))


class GpsAgeTest(RecorderTestCase):
    """Nur eine aktuelle Position gehoert in Spur und CSV."""

    def _trip_step(self, **kwargs):
        rec = Recorder(self.state, outdir=self.tmp, **kwargs)
        rec._open_files(recorder_module.MODE_TRIP)
        rec._record_step()
        return rec

    def test_fresh_fix_is_drawn(self):
        rec = self._trip_step(gps_max_age=15)
        self.assertTrue(os.path.exists(rec._fname_25))
        self.assertIn(u'51,438500', _csv_rows(self.tmp)[0])

    def test_stale_fix_is_neither_drawn_nor_written(self):
        """Die letzte bekannte Position kann von gestern sein."""
        self.state.mark_gps_fix(monotonic() - 100)
        rec = self._trip_step(gps_max_age=15)
        self.assertFalse(os.path.exists(rec._fname_25))
        self.assertIsNone(rec._lat_old)
        row = _csv_rows(self.tmp)[0]
        self.assertTrue(row.endswith(u';;'), row)
        self.assertNotIn(u'51,4385', row)

    def test_track_restarts_after_gps_gap(self):
        """Fix bei A, dann Stille, dann Fix bei B: keine gerade Linie
        von A nach B ueber die Luecke."""
        rec = Recorder(self.state, outdir=self.tmp, gps_max_age=15)
        rec._open_files(recorder_module.MODE_TRIP)
        rec._record_step()                                  # A
        self.state.mark_gps_fix(monotonic() - 100)          # Stille
        rec._record_step()
        self.state.set_position(51.5, 6.9)                  # B
        self.state.mark_gps_fix()
        rec._record_step()
        with io.open(rec._fname_25, encoding='utf-8') as fh:
            kml_text = fh.read()
        segments = []
        for block in re.findall(r'<LineString>.*?<coordinates>(.*?)</coordinates>',
                                kml_text, re.S):
            points = [p.split(',')[:2] for p in block.split()]
            segments.append(frozenset(tuple(p) for p in points))
        a = ('6.788200', '51.438500')
        b = ('6.900000', '51.500000')
        self.assertTrue(segments)
        self.assertNotIn(frozenset([a, b]), segments)

    def test_clock_set_back_means_no_fix(self):
        self.state.mark_gps_fix(monotonic() + 100)
        self.assertIsNone(self.state.gps_age())

    def test_no_fix_ever_leaves_coordinates_empty(self):
        """Am PC gibt es kein GPS -- dort stand bisher 0,000000."""
        self.state = AppState()
        self.state.set_measurement(1.0, 2.0)
        self._trip_step()
        self.assertTrue(_csv_rows(self.tmp)[0].endswith(u';;'))


class TlsFallbackTest(RecorderTestCase):
    """Altes Android: ssl vorhanden, aber Zertifikate veraltet."""

    def test_falls_back_to_http_and_stays_there(self):
        urls = []

        def picky(url, body, headers, timeout=30):
            urls.append(url)
            if url.startswith('https://'):
                raise IOError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')
            return 201
        recorder_module.post_json = picky
        rec = Recorder(self.state, outdir=self.tmp)
        rec._push_step()
        rec._push_step()
        self.assertTrue(urls[0].startswith('https://'))
        self.assertTrue(urls[1].startswith('http://'))
        # Der zweite Upload versucht HTTPS gar nicht erst.
        self.assertEqual(len(urls), 3)
        self.assertTrue(urls[2].startswith('http://'))
        self.assertEqual(self.state.error(), u'')

    def test_upload_waits_at_most_15_s(self):
        """Der Upload laeuft im Recorder-Thread; mit 30 s Timeout fehlten
        bei haengendem Netz 30 s lang Punkte und CSV-Zeilen. Das gilt
        auch fuer den Rueckfall auf HTTP."""
        timeouts = []

        def picky(url, body, headers, timeout=None):
            timeouts.append(timeout)
            if url.startswith('https://'):
                raise IOError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')
            return 201
        recorder_module.post_json = picky
        rec = Recorder(self.state, outdir=self.tmp)
        rec._push_step()
        self.assertEqual(len(timeouts), 2)
        self.assertTrue(all(t is not None and t <= 15 for t in timeouts), timeouts)

    def test_other_errors_do_not_switch_to_http(self):
        urls = []

        def offline(url, body, headers, timeout=30):
            urls.append(url)
            raise IOError('Network is unreachable')
        recorder_module.post_json = offline
        rec = Recorder(self.state, outdir=self.tmp)
        rec._push_step()
        self.assertEqual(len(urls), 1)
        self.assertIn(u'Network is unreachable', self.state.error())

    def test_tls_error_detection(self):
        import ssl
        try:
            from urllib.error import URLError
        except ImportError:
            from urllib2 import URLError
        tls = recorder_module.is_tls_error
        # Dauerhaft: veraltete Zertifikate, Protokoll zu alt.
        self.assertTrue(tls(URLError(ssl.SSLError(
            1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed'))))
        self.assertTrue(tls(IOError('<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>')))
        self.assertTrue(tls(ssl.SSLError(1, '[SSL: UNSUPPORTED_PROTOCOL] unsupported protocol')))
        # Voruebergehend: langsames oder abreissendes Mobilnetz. Der Text
        # enthaelt '_ssl.c', das darf nicht auf HTTP umschalten.
        self.assertFalse(tls(URLError(ssl.SSLError(
            '_ssl.c:1059: The handshake operation timed out'))))
        self.assertFalse(tls(ssl.SSLError(8, 'EOF occurred in violation of protocol')))
        self.assertFalse(tls(IOError('timed out')))
        self.assertFalse(tls(IOError('Network is unreachable')))

    def test_handshake_timeout_keeps_https(self):
        urls = []

        def slow(url, body, headers, timeout=30):
            urls.append(url)
            raise IOError('_ssl.c:1059: The handshake operation timed out')
        recorder_module.post_json = slow
        rec = Recorder(self.state, outdir=self.tmp)
        rec._push_step()
        rec._push_step()
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(u.startswith('https://') for u in urls), urls)


class WindowMeanTest(RecorderTestCase):
    """Ein Punkt ist der Mittelwert aller Sensorwerte seines Intervalls,
    nicht der zufaellige Momentanwert am Ende."""

    def _local(self):
        rec = Recorder(self.state, outdir=self.tmp, record_interval=5)
        rec._open_files(recorder_module.MODE_LOCAL)
        rec._start_window()
        return rec

    def test_csv_holds_the_mean_of_the_window(self):
        rec = self._local()
        for pm_25, pm_10 in ((10.0, 20.0), (20.0, 40.0), (30.0, 60.0)):
            self.state.set_measurement(pm_25, pm_10)
        rec._record_step()
        row = _csv_rows(self.tmp)[0]
        # Momentanwert waere 30,0;60,0.
        self.assertEqual(row.split(';')[1:3], [u'20,0', u'40,0'], row)
        self.assertEqual(self.state.history()[-1][1:3], (20.0, 40.0))

    def test_next_window_only_counts_new_values(self):
        rec = self._local()
        self.state.set_measurement(100.0, 100.0)
        rec._record_step()
        self.state.set_measurement(2.0, 4.0)
        self.state.set_measurement(4.0, 8.0)
        rec._record_step()
        rows = _csv_rows(self.tmp)
        self.assertEqual(rows[1].split(';')[1:3], [u'3,0', u'6,0'], rows)

    def test_mean_has_no_float_noise(self):
        rec = self._local()
        for _ in range(3):
            self.state.set_measurement(1.1, 2.2)    # Summe 3.3000000000000003
        rec._record_step()
        row = _csv_rows(self.tmp)[0]
        self.assertEqual(row.split(';')[1:3], [u'1,1', u'2,2'], row)
        self.assertEqual(self.state.history()[-1][1:3], (1.1, 2.2))

    def test_empty_window_takes_the_current_value(self):
        """Intervall kuerzer als der Sensortakt: kein Wert im Fenster."""
        rec = self._local()
        rec._record_step()
        self.assertEqual(_csv_rows(self.tmp)[0].split(';')[1:3], [u'12,3', u'45,6'])

    def test_upload_sends_the_mean_since_the_last_upload(self):
        rec = Recorder(self.state, outdir=self.tmp)
        rec._push_step()                        # erster Upload: Momentanwert
        for pm_25, pm_10 in ((10.0, 20.0), (20.0, 40.0), (30.0, 60.0)):
            self.state.set_measurement(pm_25, pm_10)
        rec._push_step()
        values = [{v['value_type']: v['value'] for v in json.loads(body)['sensordatavalues']}
                  for body in self.posts]
        self.assertEqual(values, [{'P1': '45.6', 'P2': '12.3'},
                                  {'P1': '40.0', 'P2': '20.0'}])


class LiveIntervalTest(RecorderTestCase):
    """Das Messintervall kommt aus dem AppState; eine Umstellung in der
    Oberflaeche wirkt sofort, nicht erst nach dem alten Intervall."""

    def test_shorter_interval_takes_effect_at_once(self):
        self.state.set_record_interval(60)
        self.recorder = Recorder(self.state, outdir=self.tmp, tick=0.02)
        self.recorder.start()
        self.state.local = True
        time.sleep(0.3)
        self.assertEqual(_csv_rows(self.tmp), [])
        self.state.set_record_interval(0.2)
        self.assertTrue(_wait_for(lambda: _csv_rows(self.tmp), timeout=1.5),
                        'neues Messintervall wirkt nicht')

    def test_next_point_is_announced(self):
        self.state.set_record_interval(30)
        self.recorder = Recorder(self.state, outdir=self.tmp, tick=0.02)
        self.recorder.start()
        self.assertTrue(_wait_for(lambda: self.state.next_point_at() is not None))
        self.assertAlmostEqual(self.state.next_point_at() - time.time(), 30, delta=1.0)
        self.state.set_record_interval(10)
        self.assertTrue(_wait_for(
            lambda: abs(self.state.next_point_at() - time.time() - 10) < 1.0))


class HistoryTest(RecorderTestCase):
    """Der Verlauf fuer das Diagramm entsteht immer, nicht nur waehrend
    einer Messung -- aber nur gespeicherte Punkte tragen recorded=True."""

    def test_without_mode_points_are_a_preview(self):
        self.start(record_interval=0.1)
        self.assertTrue(_wait_for(lambda: len(self.state.history()) >= 2))
        self.assertTrue(all(not p[4] for p in self.state.history()))
        self.assertEqual(os.listdir(self.tmp), [])
        point = self.state.history()[0]
        self.assertAlmostEqual(point[0], time.time(), delta=5)
        self.assertEqual(point[1:4], (12.3, 45.6, 0.1))

    def test_with_mode_points_are_recorded(self):
        self.start(record_interval=0.1)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: len([p for p in self.state.history() if p[4]]) >= 2))
        self.state.shutdown()
        self.recorder.join(5)
        recorded = [p for p in self.state.history() if p[4]]
        # Jeder gespeicherte Punkt steht genau einmal in der Datei.
        self.assertEqual(len(recorded), len(_csv_rows(self.tmp)))

    def test_no_point_without_fresh_value(self):
        """Ohne Sensor kein Punkt -- und ohne Modus auch kein Hinweis."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        self.start(record_interval=0.05, max_age=10)
        time.sleep(0.3)
        self.assertEqual(self.state.history(), [])
        self.assertEqual(self.state.error(), u'')

    def test_failed_write_still_shows_the_value(self):
        """Ein Schreibfehler laesst den Punkt im Diagramm, aber nicht als
        gespeichert."""
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_LOCAL)
        original = kml.write_csv

        def broken(*args):
            raise IOError('No space left on device')
        kml.write_csv = broken
        self.addCleanup(setattr, kml, 'write_csv', original)
        self.assertRaises(IOError, rec._record_step)
        self.assertEqual([p[4] for p in self.state.history()], [False])
        self.assertEqual(self.state.session()['points'], 0)


class PointIntervalTest(RecorderTestCase):
    """Ein Punkt traegt die Fensterlaenge, ueber die er gemittelt hat --
    das Diagramm erkennt daran Luecken und das Band "gespeichert"."""

    def setUp(self):
        RecorderTestCase.setUp(self)
        self.t = 1000.0
        saved = recorder_module._now
        recorder_module._now = lambda: self.t
        self.addCleanup(setattr, recorder_module, '_now', saved)

    def _recorder(self, seconds):
        self.state.set_record_interval(seconds)
        rec = Recorder(self.state, outdir=self.tmp)
        rec._start_window()
        return rec

    def test_regular_point_has_the_set_interval(self):
        rec = self._recorder(5)
        self.t += 5
        rec._record_step()
        self.assertEqual(self.state.history()[-1][3], 5)

    def test_shortened_interval_point_spans_the_window(self):
        """15 min -> 5 s nach 10 min: der sofort faellige Punkt mittelt
        10 min, trug aber 5 s -- im Diagramm eine falsche Luecke."""
        rec = self._recorder(900)
        self.t += 600
        self.state.set_record_interval(5)
        rec._record_step()
        self.assertAlmostEqual(self.state.history()[-1][3], 600)

    def test_sleep_is_not_bridged(self):
        """Schlief das Geraet, kamen keine Werte -- der Punkt danach darf
        nicht so tun, als haette er die ganze Stunde gemittelt."""
        rec = self._recorder(5)
        self.t += 3600
        self.state.set_measurement(1.0, 2.0)
        rec._record_step()
        self.assertEqual(self.state.history()[-1][3], 5)

    def test_shortened_after_sleep_is_capped_too(self):
        rec = self._recorder(900)
        self.t += 3600
        self.state.set_record_interval(5)
        rec._record_step()
        self.assertAlmostEqual(self.state.history()[-1][3], 900)

    def test_hanging_upload_is_part_of_the_window(self):
        """Waehrend eines haengenden Uploads kamen die Sensorwerte weiter;
        der Punkt danach mittelt sie und traegt die echte Laenge."""
        def slow(url, body, headers, timeout=None):
            self.t += 15
            return 201
        recorder_module.post_json = slow
        rec = self._recorder(5)
        self.t += 2
        rec._push()
        rec._record_step()
        self.assertAlmostEqual(self.state.history()[-1][3], 17)
        # Das naechste Fenster ist wieder normal.
        rec._advance_window()
        self.t += 5
        rec._record_step()
        self.assertEqual(self.state.history()[-1][3], 5)

    def _stationary_initial_recorder(self):
        self.state.set_record_interval(300)
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_STATIONARY)
        rec._window_mode = recorder_module.MODE_STATIONARY
        rec._start_window()
        rec._stationary_initial_pending = True
        rec._push_totals = rec._window_totals
        return rec

    def test_stationary_initial_point_uses_first_wake_window(self):
        rec = self._stationary_initial_recorder()
        awake = config.SDS011_POWER_SAVE_SETTLE + config.SDS011_POWER_SAVE_SAMPLE_WINDOW
        self.t += awake
        self.state.set_measurement(20.0, 30.0)
        self.assertTrue(rec._record_step())
        self.assertAlmostEqual(self.state.history()[-1][3], awake)
        rec._advance_window(True)
        self.assertFalse(rec._stationary_initial_pending)
        self.assertAlmostEqual(rec._window_start, self.t)
        self.assertAlmostEqual(rec._window_start + 300, self.t + 300)

    def test_stationary_initial_point_requires_new_sample(self):
        rec = self._stationary_initial_recorder()
        self.t += config.SDS011_POWER_SAVE_SETTLE + config.SDS011_POWER_SAVE_SAMPLE_WINDOW
        self.assertFalse(rec._record_step())
        self.assertEqual(_csv_rows(self.tmp), [])
        rec._advance_window(False)
        self.assertTrue(rec._stationary_initial_pending)
        retry_due = rec._window_start + rec._stationary_initial_seconds()
        self.assertAlmostEqual(retry_due, self.t + rec.PUSH_RETRY)


class FlushWindowTest(RecorderTestCase):
    """Stop, Moduswechsel und Beenden verwarfen das angefangene
    Intervall -- bei 15 min bis zu 15 min Messung, und eine kurze Messung
    hinterliess gar keine Datei."""

    def _measure(self, **kwargs):
        self.start(record_interval=60, **kwargs)
        self.state.local = True
        self.assertTrue(_wait_for(lambda: self.state.session() is not None))
        started = time.time()
        for pm_25, pm_10 in ((10.0, 20.0), (30.0, 40.0)):
            self.state.set_measurement(pm_25, pm_10)
        time.sleep(0.2)
        return started

    def _wait_stopped(self):
        self.assertTrue(_wait_for(lambda: not self.state.session()['active']))

    def test_stop_writes_the_started_window(self):
        started = self._measure()
        self.state.set_status(u'Aufzeichnung inaktiv.')
        self.state.local = False
        self._wait_stopped()
        rows = _csv_rows(self.tmp)
        self.assertEqual([r.split(';')[1:3] for r in rows], [[u'20,0', u'30,0']], rows)
        session = self.state.session()
        self.assertEqual(session['points'], 1)
        self.assertTrue(session['file'])
        point = self.state.history()[-1]
        self.assertTrue(point[4])
        # Traegt die echte Laenge, nicht 60 s: das Band "gespeichert"
        # beginnt nicht vor der Messung.
        self.assertLess(point[3], time.time() - started + 0.5)
        # Der Statustext der Oberflaeche nach dem Stop bleibt stehen.
        self.assertEqual(self.state.status(), u'Aufzeichnung inaktiv.')

    def test_switch_writes_the_started_window(self):
        self._measure()
        self.state.recording = True
        self.state.local = False
        self.assertTrue(_wait_for(lambda: self.state.session()['mode']
                                  == recorder_module.MODE_TRIP))
        self.assertEqual(len(_csv_rows(self.tmp)), 1)

    def test_shutdown_writes_the_started_window(self):
        self._measure()
        self.state.shutdown()
        self.recorder.join(5)
        self.assertEqual(len(_csv_rows(self.tmp)), 1)
        self.assertFalse(self.state.session()['active'])

    def test_empty_window_writes_nothing(self):
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_LOCAL)
        rec._start_window()
        rec._close_files()
        self.assertEqual(os.listdir(self.tmp), [])

    def test_write_error_still_closes_the_kml(self):
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_TRIP)
        rec._start_window()
        rec._record_step()
        self.state.set_measurement(20.0, 30.0)
        original = kml.write_csv

        def broken(*args):
            raise IOError('No space left on device')
        kml.write_csv = broken
        self.addCleanup(setattr, kml, 'write_csv', original)
        rec._close_files()
        for name in (rec._fname_25, rec._fname_10):
            with open(name, 'rb') as handle:
                ElementTree.parse(handle)
        self.assertIn(u'Aufzeichnung gestört', self.state.error())
        self.assertFalse(self.state.session()['active'])

    def test_write_error_on_stop_stays_visible(self):
        """Den Fehler beim letzten Punkt raeumte der Stop gleich wieder
        weg; er stand nur im Log."""
        self._measure()
        original = kml.write_csv

        def broken(*args):
            raise IOError('No space left on device')
        kml.write_csv = broken
        self.addCleanup(setattr, kml, 'write_csv', original)
        self.state.local = False
        self._wait_stopped()
        time.sleep(0.2)
        self.assertIn(u'Aufzeichnung gestört', self.state.error())


class StationaryRecordingTest(RecorderTestCase):

    def test_stationary_writes_its_own_csv_and_uploads(self):
        self.start(record_interval=0.1, stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: self.posts and _csv_rows(self.tmp)))
        files = os.listdir(self.tmp)
        self.assertEqual(len(files), 1, files)
        self.assertTrue(re.match(r'feinstaub_stationaer_\d{8}_\d\d_\d\d_\d\d\.csv$', files[0]),
                        files)
        self.assertTrue(any(p[4] for p in self.state.history()))
        self.assertEqual(self.state.session()['mode'], recorder_module.MODE_STATIONARY)

    def test_upload_info(self):
        self.start(record_interval=0.1, stat_interval=60)
        self.state.stationary = True
        self.assertTrue(_wait_for(lambda: (self.state.upload_info() or {}).get('last_at')))
        self.assertTrue(_wait_for(lambda: (self.state.upload_info() or {}).get('next_at', 0)
                                  > time.time()))
        info = self.state.upload_info()
        self.assertTrue(info['last_ok'])
        self.assertIn(u'übertragen', info['last_message'])
        self.assertAlmostEqual(info['last_pm25'], 12.3)
        self.assertAlmostEqual(info['last_pm10'], 45.6)
        self.assertAlmostEqual(info['next_at'] - time.time(), 0.1, delta=0.5)
        # Nach dem Ausschalten ist kein Upload mehr geplant.
        self.state.stationary = False
        self.assertTrue(_wait_for(lambda: self.state.upload_info()['next_at'] is None))
        self.assertTrue(self.state.upload_info()['last_ok'])

    def test_failed_upload_is_reported(self):
        recorder_module.post_json = lambda url, body, headers, timeout=30: 500
        rec = Recorder(self.state, outdir=self.tmp)
        self.assertTrue(rec._push_step())
        info = self.state.upload_info()
        self.assertFalse(info['last_ok'])
        self.assertIn(u'Status Code 500', info['last_message'])

    def test_stale_hint_does_not_flicker(self):
        """Stationaer wird aufgezeichnet und hochgeladen. Mit zwei
        verschiedenen Hinweisen wechselte der Text bei jedem Schritt und
        landete jedes Mal neu im Log."""
        self.state.set_measurement(1.0, 2.0, at=monotonic() - 100)
        rec = Recorder(self.state, outdir=self.tmp, max_age=10)
        rec._open_files(recorder_module.MODE_STATIONARY)
        rec._record_step()
        after_record = self.state.error()
        self.assertFalse(rec._push_step())
        self.assertEqual(self.state.error(), after_record)
        self.assertIn(u'nichts aufgezeichnet', after_record)
        self.assertIn(u'nichts hochgeladen', after_record)


class SessionTest(RecorderTestCase):

    def test_session_follows_the_recording(self):
        self.state.set_place(u'Halle')
        rec = Recorder(self.state, outdir=self.tmp, clock=lambda: 1000.0)
        rec._open_files(recorder_module.MODE_LOCAL)
        session = self.state.session()
        self.assertEqual(session['mode'], recorder_module.MODE_LOCAL)
        self.assertTrue(session['active'])
        self.assertEqual(session['started'], 1000.0)
        self.assertIsNone(session['ended'])
        self.assertEqual(session['points'], 0)
        self.assertIsNone(session['avg_pm25'])
        self.assertTrue(session['file'].startswith(u'feinstaub_halle_'), session)
        self.assertEqual(session['place'], u'Halle')

        rec._start_window()
        self.state.set_measurement(10.0, 20.0)
        rec._record_step()
        rec._start_window()
        self.state.set_measurement(20.0, 30.0)
        rec._record_step()
        session = self.state.session()
        self.assertEqual(session['points'], 2)
        self.assertAlmostEqual(session['avg_pm25'], 15.0)
        self.assertAlmostEqual(session['avg_pm10'], 25.0)
        self.assertEqual(self.state.status(), u'Mittelwerte: 25.0, 15.0')

        rec._close_files()
        session = self.state.session()
        self.assertFalse(session['active'])
        self.assertEqual(session['ended'], 1000.0)
        self.assertEqual(session['points'], 2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, session['file'])))

    def test_trip_session_uses_name(self):
        self.state.set_trip_name(u'Von Essen nach Duisburg')
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_TRIP)
        session = self.state.session()
        self.assertEqual(session['place'], u'Von Essen nach Duisburg')
        self.assertTrue(session['file'].startswith(u'feinstaub_von_essen_nach_duisburg_'),
                        session)
        self.assertIn('von_essen_nach_duisburg_25_line_', os.path.basename(rec._fname_25))

    def test_trip_session_without_name_has_no_place(self):
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_TRIP)
        self.assertEqual(self.state.session()['place'], u'')

    def test_session_without_points_names_no_file(self):
        rec = Recorder(self.state, outdir=self.tmp)
        rec._open_files(recorder_module.MODE_TRIP)
        rec._close_files()
        self.assertEqual(self.state.session()['file'], u'')

    def test_stop_ends_the_session(self):
        self.start(record_interval=0.1)
        self.state.recording = True
        self.assertTrue(_wait_for(lambda: (self.state.session() or {}).get('points')))
        self.assertTrue(self.state.session()['active'])
        self.state.recording = False
        self.assertTrue(_wait_for(lambda: not self.state.session()['active']))
        self.assertIsNotNone(self.state.session()['ended'])


class HostTest(unittest.TestCase):

    def test_only_reachable_from_the_device_by_default(self):
        saved = os.environ.pop('SDS011_HOST', None)
        try:
            self.assertEqual(config.http_host(), '127.0.0.1')
            os.environ['SDS011_HOST'] = '0.0.0.0'
            self.assertEqual(config.http_host(), '0.0.0.0')
        finally:
            os.environ.pop('SDS011_HOST', None)
            if saved is not None:
                os.environ['SDS011_HOST'] = saved


class UnicodeFormatTest(unittest.TestCase):
    """Unter Python 2 wirft '...{0}'.format(u'Mülheim') einen
    UnicodeEncodeError -- /localon/ antwortete mit 500, sobald der Ort
    einen Umlaut hatte. Vorlagen fuer .format() deshalb immer u''.

    Ueber tokenize statt ast: das sieht das u-Praefix auf jeder
    Python-Version (ast erst ab 3.8)."""

    @staticmethod
    def _offenders(path):
        skip = (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                tokenize.INDENT, tokenize.DEDENT)
        with io.open(path, encoding='utf-8') as fh:
            tokens = [t for t in tokenize.generate_tokens(fh.readline)
                      if t[0] not in skip]
        found = []
        run = []
        run_start = 0
        for i, tok in enumerate(tokens):
            if tok[0] == tokenize.STRING:
                if not run:
                    run_start = i
                run.append(tok)
                continue
            # ('a' 'b').format(...): die Klammer gehoert zum Literal.
            if run and tok[1] == ')' and run_start > 0 and tokens[run_start - 1][1] == '(':
                continue
            if (run and tok[1] == '.' and i + 1 < len(tokens)
                    and tokens[i + 1][1] == 'format'):
                # Bei aneinandergehaengten Literalen genuegt ein u-Teil.
                prefixes = [t[1][:t[1].index(t[1][-1])].lower() for t in run]
                if not any('u' in prefix for prefix in prefixes):
                    found.append('%s:%d' % (os.path.basename(path), run[0][2][0]))
            run = []
        return found

    def test_detector_sees_byte_templates(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, 'probe.py')
        with io.open(path, 'w', encoding='utf-8') as fh:
            fh.write(u"a = '{0}'.format(1)\n"
                     u"b = u'{0}'.format(1)\n"
                     u"c = ('x'\n     u'{0}').format(1)\n"
                     u"d = ('x'\n     '{0}').format(1)\n")
        self.assertEqual(self._offenders(path), ['probe.py:1', 'probe.py:5'])

    def test_format_templates_are_unicode(self):
        offenders = []
        for name in sorted(glob.glob(os.path.join(config.BASEDIR, '*.py'))):
            offenders.extend(self._offenders(name))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
