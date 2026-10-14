# -*- coding: utf-8 -*-
"""HTTP-Routen der Oberflaeche (bottle).

create_app() baut die App fuer main.py. Die Routen lesen und setzen den
AppState und fragen beim Transport die gekoppelten Geraete ab; die
Hardware bedienen sie nicht. Sensor, GPS und Aufzeichnung laufen in
eigenen Threads und reagieren auf den Zustand. Das Diagramm zeichnet
chart.py als SVG aus dem Verlauf im AppState.

Eine eigene Bottle()-Instanz statt der globalen Modul-Dekoratoren:
jeder Aufruf liefert eine unabhaengige App.
"""

from __future__ import absolute_import

import math
import re
import threading
import time

from bottle import Bottle, request, response, static_file, template

import config
import kml
import settings
from logging_util import to_text, write_log


# Absoluter Pfad, weil das Arbeitsverzeichnis je nach QPython-Version
# ein anderes ist. Uebergeben als template_lookup=; ein lookup= haelt
# bottle fuer eine Template-Variable und sucht dann in ./views/. Eine
# feste Liste, weil bottle den Template-Cache ueber ihre id() fuehrt.
TEMPLATE_LOOKUP = [config.TEMPLATEDIR]

def _query(name, default=u''):
    """Einen Query-Parameter als Text lesen.

    bottle dekodiert Query-Werte als latin-1; aus %C3%BC wuerde so
    Buchstabensalat statt eines Umlauts. getunicode() rechnet das um,
    fehlt aber in manchen bottle-Versionen -- daher der Rueckfall.
    Leere Werte ergeben default.
    """
    value = None
    getunicode = getattr(request.query, 'getunicode', None)
    if getunicode is not None:
        try:
            value = getunicode(name)
        except Exception:
            value = None
    if value is None:
        value = request.query.get(name)
        if value is not None and not isinstance(value, type(u'')):
            value = value.decode('utf-8', 'replace')
    return value if value else default


def _int_or_none(value):
    return None if value is None else int(value)


def _int_query(name, default):
    """Einen Query-Parameter als Zahl lesen; fehlt er oder ist er keine
    ganze Zahl, gilt default."""
    try:
        return int(_query(name) or default)
    except (TypeError, ValueError):
        return default


def _clamp(value, lowest, highest):
    return max(lowest, min(highest, value))


def _seconds_until(epoch, now):
    """Ganze Sekunden bis epoch (aufgerundet, nie negativ) oder None."""
    if epoch is None:
        return None
    return int(math.ceil(max(0.0, epoch - now)))


def _clock_label(epoch):
    """Ortszeit eines Zeitpunkts als '14:35:20', auf die volle Sekunde
    aufgerundet wie _seconds_until."""
    local = time.localtime(math.ceil(epoch))
    return u'{0:02d}:{1:02d}:{2:02d}'.format(local.tm_hour, local.tm_min, local.tm_sec)


def _interval_label(seconds):
    """30 -> '30 s', 300 -> '5 min'."""
    if seconds >= 60 and seconds % 60 == 0:
        return u'{0} min'.format(seconds // 60)
    return u'{0} s'.format(seconds)


def _session_view(session, now):
    """Sitzung fuer /status/: dazu die Laufzeit in Sekunden, Mittelwerte
    auf eine Nachkommastelle."""
    if session is None:
        return None
    view = dict(session)
    end = session.get('ended') or now
    view['elapsed'] = int(max(0.0, end - session['started']))
    for key in ('avg_pm25', 'avg_pm10'):
        if view.get(key) is not None:
            view[key] = round(view[key], 1)
    return view


def _upload_view(info, now):
    """Upload-Stand fuer /status/: dazu die Sekunden bis zum naechsten."""
    if info is None:
        return None
    view = dict(info)
    view['next_in'] = _seconds_until(info.get('next_at'), now)
    for key in ('last_pm25', 'last_pm10'):
        if view.get(key) is not None:
            view[key] = round(view[key], 1)
    return view


def _measurement_fresh_for_status(snap, age):
    """Ob der letzte Wert in der Oberflaeche noch eingestuft wird.

    Bei geplantem SDS011-Sleep/Wake ist eine laengere Stille geplant; dann ist
    der letzte Wert waehrend des Sensorzyklus nicht "veraltet".
    """
    if age is None:
        return False
    if age <= config.MAX_MEASUREMENT_AGE:
        return True
    if (snap['connection'] == u'verbunden'
            and snap['record_interval'] >= config.SDS011_POWER_SAVE_MIN_INTERVAL):
        limit = (max(snap['record_interval'],
                     config.SDS011_POWER_SAVE_SETTLE
                     + config.SDS011_POWER_SAVE_SAMPLE_WINDOW)
                 + config.SDS011_POWER_SAVE_SILENCE_SLACK)
        return age <= limit
    return False


# Zeitraeume des Diagramms in Sekunden, 0 = alles.
CHART_RANGES = (600, 3600, 21600, 0)
MAP_FRAGMENT_RE = re.compile(r'^(.*#)([^/]+)/([^/]+)/([^/]+)$')


def _map_coord(value):
    return '%.5f' % float(value)


def _map_url_at_position(fallback_url, lat, lon):
    """Sensor.community-Karte aus der konfigurierten Karte ableiten.

    So bleiben Domain und Zoomstufe aus config.py erhalten, nur die
    Koordinaten werden ersetzt. Ist die Karte anders formatiert, bleibt
    der feste Link unveraendert.
    """
    match = MAP_FRAGMENT_RE.match(fallback_url)
    if not match:
        return fallback_url
    return '%s%s/%s/%s' % (match.group(1), match.group(2),
                           _map_coord(lat), _map_coord(lon))


def _sensor_position():
    url = config.LINKS.get('karte', getattr(config, 'SENSOR_MAP_URL', ''))
    match = MAP_FRAGMENT_RE.match(url)
    if not match:
        return None
    try:
        lat = float(match.group(3))
        lon = float(match.group(4))
    except (TypeError, ValueError):
        return None
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None
    return lat, lon


def _distance_m(a_lat, a_lon, b_lat, b_lon):
    radius = 6371000.0
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    dlat = lat2 - lat1
    dlon = math.radians(b_lon - a_lon)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    h = min(1.0, max(0.0, h))
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _fresh_position(state):
    lat, lon, _utc = state.position()
    age = state.gps_age()
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if (age is None or age > config.GPS_MAX_AGE or
            lat < -90 or lat > 90 or lon < -180 or lon > 180 or
            (lat == 0 and lon == 0)):
        return None
    return lat, lon


def _link_url(state, name):
    url = config.LINKS.get(name)
    if url is None:
        return None
    if name == 'karte_position':
        position = _fresh_position(state)
        if position is not None:
            return _map_url_at_position(config.LINKS.get('karte', url),
                                        position[0], position[1])
    return url


def _stationary_position_check(state):
    """(ok, entfernung_m, erlaubte_entfernung_m).

    Ohne GPS, ohne frischen Fix oder ohne parsebaren Sensorstandort wird
    nicht blockiert. Die Pruefung soll falsche oeffentliche Uploads
    verhindern, aber Laptop-Betrieb und schlechten Empfang nicht lahmlegen.
    """
    if not state.snapshot().get('gps_available'):
        return True, None, config.STATIONARY_MAX_DISTANCE_M
    target = _sensor_position()
    position = _fresh_position(state)
    if target is None or position is None:
        return True, None, config.STATIONARY_MAX_DISTANCE_M
    distance = int(round(_distance_m(position[0], position[1],
                                     target[0], target[1])))
    return (distance <= config.STATIONARY_MAX_DISTANCE_M,
            distance, config.STATIONARY_MAX_DISTANCE_M)


def create_app(state, on_shutdown=None, transport=None, open_url=None):
    """Die Bottle-App mit allen Routen bauen.

    state: der gemeinsame AppState. on_shutdown: wird von /__exit in
    einem eigenen Thread gerufen. transport: liefert die gekoppelten
    Geraete fuer /devices/ und /connect/; ohne ihn bleibt die Liste leer.
    open_url: oeffnet eine Adresse im Browser des Systems (Android);
    ohne sie bleiben die Links in der Oberflaeche gewoehnliche Links.
    """
    app = Bottle()

    @app.route('/')
    def index():
        return template('index.html', template_lookup=TEMPLATE_LOOKUP,
                        xsensor=config.XSENSOR, outdir=config.OUTDIR,
                        intervals=config.RECORD_INT_CHOICES,
                        stationary_intervals=config.STATIONARY_RECORD_INT_CHOICES,
                        links=config.LINKS, open_external=open_url is not None)

    @app.route('/open/')
    def open_link():
        """Oeffnet einen der Links aus config.LINKS im Browser des Systems.

        Nur Namen, keine Adressen: sonst koennte jede Seite, die den
        Server erreicht, beliebige Adressen auf dem Handy oeffnen."""
        name = _query('link')
        url = _link_url(state, name)
        if url is None:
            return {'value': u'Unbekannter Link.', 'refused': True, 'opened': False}
        if open_url is None:
            # Am PC oeffnet der Browser den Link selbst.
            return {'value': u'', 'opened': False, 'url': url}
        try:
            open_url(url)
        except Exception as exc:
            write_log(0, u'Link nicht geoeffnet: {0}'.format(to_text(exc)))
            return {'value': u'Browser ließ sich nicht öffnen: {0}'.format(to_text(exc)),
                    'refused': True, 'opened': False, 'url': url}
        write_log(1, u'Link im Browser geoeffnet: {0}'.format(url))
        return {'value': u'Im Browser geöffnet.', 'opened': True, 'url': url}

    @app.route('/static/<filename:path>')
    def serve_static(filename):
        # no-cache: der Browser fragt jedes Mal nach (meist ein billiges
        # 304). Ohne den Kopf cachen Chrome und WebView heuristisch, nach
        # einem Update liefe tagelang altes app.js zum neuen Template.
        # Der Kopf muss an die Antwort von static_file: sie ersetzt beim
        # Ausliefern alle Koepfe des globalen response.
        res = static_file(filename, root=config.STATICDIR)
        res.set_header('Cache-Control', 'no-cache')
        return res

    # -- Sensorverbindung ---------------------------------------------
    @app.route('/devices/')
    def devices():
        """Gekoppelte Geraete fuer die Auswahlliste, dazu das vorgewaehlte."""
        found = []
        if transport is not None:
            try:
                found = transport.available_devices()
            except Exception as exc:
                write_log(0, u'Geraeteliste nicht lesbar: {0}'.format(to_text(exc)))
                state.report_error(u'Geräteliste nicht lesbar: {0}'.format(to_text(exc)))
                # Den simulierten Sensor trotzdem anbieten.
                simulated = getattr(transport, 'simulated_devices', None)
                if simulated is not None:
                    found = simulated()
        selected, _ = state.device()
        if selected is None and found:
            # Das Modul aus config.py vorauswaehlen, falls gekoppelt --
            # am PC stehen sonst Kopfhoerer und Co. ganz oben.
            ids = [entry['id'] for entry in found]
            configured = config.SDS011_BLUETOOTH_DEVICE_ID
            selected = configured if configured in ids else ids[0]
        return {'devices': found, 'selected': selected}

    @app.route('/connect/')
    def connect():
        device_id = _query('device') or None
        refused = _refuse_mixing(device_id)
        if refused:
            return refused
        name = u''
        if device_id and transport is not None:
            try:
                for entry in transport.available_devices():
                    if entry['id'] == device_id:
                        name = entry['name']
                        break
            except Exception:
                pass
        if device_id:
            state.set_device(device_id, name)
        # Der eigentliche Verbindungsaufbau passiert im SensorReader --
        # die Route blockiert nicht, sie aeussert nur den Wunsch.
        state.connection_wanted = True
        write_log(1, u'Verbindung angefordert: {0}'.format(device_id or 'Standard'))
        return {'value': u'Verbindung wird aufgebaut...'}

    @app.route('/disconnect/')
    def disconnect():
        state.connection_wanted = False
        write_log(1, 'Trennung angefordert')
        return {'value': u'Verbindung getrennt.'}

    def _refuse_mixing(device_id):
        """None, solange kein Modus laeuft oder echt/simuliert gleich
        bleibt, sonst die Ablehnung: eine Datei soll nicht halb echte und
        halb erfundene Werte enthalten."""
        if not (state.recording or state.local or state.stationary):
            return None
        current, _ = state.device()
        if device_id is None or (config.is_simulation(device_id)
                                 == config.is_simulation(current)):
            return None
        message = (u'Wechsel zwischen echtem und simuliertem Sensor nicht möglich: '
                   u'erst die laufende Messung beenden.')
        write_log(1, message)
        return {'value': message, 'refused': True}

    def _requires_real_sensor(what):
        """None bei echtem Sensor, sonst die Ablehnung: simulierte Werte
        duerfen nie oeffentlich hochgeladen werden."""
        if not config.is_simulation(state.device()[0]):
            return None
        message = (u'%s nicht möglich: der Sensor ist simuliert, '
                   u'erfundene Werte werden nicht hochgeladen.' % what)
        write_log(1, message)
        return {'value': message, 'refused': True}

    def _requires_sensor(what):
        """None, wenn ein Sensor verbunden ist, sonst die Ablehnung.

        Ohne Sensor entstuenden Dateien voller Nullen, die wie eine echte
        Messung aussehen. Die Oberflaeche sperrt die Knoepfe schon; die
        Pruefung hier faengt veraltete Seiten ab. Die Meldung erscheint
        zusaetzlich als Fehler in der Statusanzeige."""
        if state.is_connected():
            return None
        message = u'%s nicht möglich: kein Sensor verbunden.' % what
        state.report_error(message)
        write_log(1, message)
        return {'value': message, 'refused': True}

    def _requires_no_other_mode(what):
        """None, wenn kein anderer Modus laeuft, sonst die Ablehnung.

        Die Modi schliessen sich aus. Die Knoepfe sperren das nur nach
        dem Stand der letzten Statusabfrage; eine veraltete Seite oder
        ein zweites Geraet koennte sonst umschalten."""
        active = [name for flag, name in ((state.recording, u'Messfahrt'),
                                          (state.local, u'Lokale Messung'),
                                          (state.stationary, u'Stationärer Modus'))
                  if flag and name != what]
        if not active:
            return None
        # Nur in der Antwort, nicht als bleibender Fehler: nach dem
        # Beenden des anderen Modus waere der Hinweis falsch.
        message = u'%s nicht möglich: erst %s beenden.' % (what, active[0])
        write_log(1, message)
        return {'value': message, 'refused': True}

    def _requires_stationary_position():
        ok, distance, limit = _stationary_position_check(state)
        if ok:
            return None
        message = (u'Station\u00e4rer Modus nicht m\u00f6glich: aktuelle GPS-Position '
                   u'ist ca. {0} m vom konfigurierten Sensorstandort entfernt '
                   u'(erlaubt: {1} m).'.format(distance, limit))
        state.report_error(message)
        write_log(1, message)
        return {'value': message, 'refused': True,
                'distance_m': distance, 'limit_m': limit}

    # Pruefen und Umschalten in einem Zug -- der Webserver bearbeitet
    # Anfragen parallel, zwei Starts zugleich ergaeben sonst zwei Modi.
    mode_lock = threading.Lock()
    # Laden, aendern, speichern in einem Zug: bei zwei Anfragen zugleich
    # ginge sonst eine Aenderung verloren.
    settings_lock = threading.Lock()

    def _store_interval(seconds):
        with settings_lock:
            state.set_record_interval(seconds)
            stored = settings.load()
            stored['record_interval'] = seconds
            return settings.save(stored)

    def _ensure_stationary_interval():
        if state.record_interval() in config.STATIONARY_RECORD_INT_CHOICES:
            return
        state.set_record_interval(config.STATIONARY_RECORD_INT_CHOICES[0])

    @app.route('/start/')
    def start_measure():
        with mode_lock:
            return _start_measure()

    def _start_measure():
        refused = (_requires_sensor(u'Messfahrt')
                   or _requires_no_other_mode(u'Messfahrt'))
        if refused:
            return refused
        if not state.recording:
            state.set_trip_name(_query('name'))
        state.recording = True
        state.local = False
        state.stationary = False
        state.clear_error()
        place = state.trip_name()
        state.set_status(u'Messfahrt aktiv%s.'
                         % (u' - ' + place if place else u''))
        write_log(1, 'Start der Aufzeichnung')
        return {'value': u'Start der Aufzeichnung der Messwerte.'}

    @app.route('/stopp/')
    def stopp():
        state.recording = False
        state.set_status(u'Aufzeichnung inaktiv.')
        write_log(1, 'Aufzeichnung angehalten')
        return {'value': u'Aufzeichnung der Messwerte angehalten.'}

    @app.route('/staton/')
    def start_stat():
        with mode_lock:
            return _start_stat()

    def _start_stat():
        # Hier besonders wichtig: der stationaere Modus laedt die Werte
        # zu sensor.community (luftdaten) hoch. Nullen ohne Sensor landeten in einem
        # oeffentlichen Datensatz.
        refused = (_requires_sensor(u'Stationärer Modus')
                   or _requires_real_sensor(u'Stationärer Modus')
                   or _requires_stationary_position()
                   or _requires_no_other_mode(u'Stationärer Modus'))
        if refused:
            return refused
        state.set_place(u'')
        state.set_trip_name(u'')
        _ensure_stationary_interval()
        state.recording = False
        state.local = False
        state.stationary = True
        state.clear_error()
        state.set_status(u'Stationärer Modus aktiv.')
        return {'value': u'Stationärer Modus gestartet.'}

    @app.route('/statoff/')
    def stopp_stat():
        state.stationary = False
        state.set_status(u'Stationärer Modus inaktiv.')
        return {'value': u'Stationärer Modus gestoppt.'}

    # -- Lokale Messung: nur Datei, kein Upload ------------------------
    @app.route('/localon/')
    def start_local():
        with mode_lock:
            return _start_local()

    def _start_local():
        refused = (_requires_sensor(u'Lokale Messung')
                   or _requires_no_other_mode(u'Lokale Messung'))
        if refused:
            return refused
        state.set_trip_name(u'')
        state.set_place(_query('place'))
        state.recording = False
        # Die lokale Messung laedt nichts hoch; das tut nur der
        # stationaere Modus.
        state.stationary = False
        state.local = True
        state.clear_error()
        place = state.place()
        state.set_status(u'Lokale Messung aktiv%s.'
                         % (u' - ' + place if place else u''))
        write_log(1, u'Lokale Messung gestartet: {0}'.format(place or '(ohne Ort)'))
        return {'value': u'Lokale Messung gestartet. Es wird nichts hochgeladen.'}

    @app.route('/localoff/')
    def stopp_local():
        state.local = False
        state.set_status(u'Lokale Messung beendet.')
        write_log(1, 'Lokale Messung beendet')
        return {'value': u'Lokale Messung beendet.'}

    # -- Messintervall und Verlauf ------------------------------------
    @app.route('/interval/')
    def set_interval():
        """Messintervall umstellen und fuer den naechsten Start merken.
        Der Recorder liest es bei jedem Tick, es wirkt also sofort."""
        seconds = _int_query('seconds', None)
        choices = (config.STATIONARY_RECORD_INT_CHOICES if state.stationary
                   else config.RECORD_INT_CHOICES)
        if seconds not in choices:
            return {'value': u'Ungültiges Messintervall.', 'refused': True,
                    'interval': state.record_interval()}
        saved = _store_interval(seconds)
        write_log(1, u'Messintervall: {0} s'.format(seconds))
        label = _interval_label(seconds)
        if not saved:
            return {'value': u'Messintervall: {0} (nicht dauerhaft gespeichert).'.format(label),
                    'interval': seconds}
        return {'value': u'Messintervall: {0}.'.format(label), 'interval': seconds}

    @app.route('/history/')
    def history():
        """Verlauf der Intervall-Mittelwerte; range in Sekunden, 0 = alles.
        recorded als 0/1: 1 = steht auch in einer Datei."""
        now = time.time()
        range_s = _int_query('range', 0)
        since = now - range_s if range_s > 0 else None
        # Das Intervall ist die echte Fensterlaenge (siehe Recorder), also
        # oft krumm; Zehntelsekunden reichen.
        points = [[round(epoch, 3), pm_25, pm_10, round(interval, 1), 1 if recorded else 0]
                  for epoch, pm_25, pm_10, interval, recorded in state.history(since)]
        return {'now': now, 'interval': state.record_interval(),
                'rev': state.history_rev(), 'points': points}

    @app.route('/history/clear/')
    def clear_history():
        """Leert nur den sichtbaren Verlauf, nicht Messdateien oder Upload."""
        state.clear_history()
        return {'value': u'Plot geleert.',
                'history_rev': state.history_rev(),
                'raw_history_rev': state.raw_history_rev()}

    def _chart_message(points, raw=False):
        """Text fuer ein leeres Diagramm; None = chart.py waehlt selbst
        ("Keine Messwerte in diesem Zeitraum" bzw. "Noch keine Messwerte").
        chart.py zeigt ihn nur, wenn im Zeitraum kein Punkt liegt.

        Die Seite laedt das Bild nur bei neuem Verlauf, anderem
        Verbindungszustand oder nach einer Minute neu. Ein "in 870 s"
        stuende so lange still; die Uhrzeit des ersten Punkts bleibt
        dagegen richtig, Server und Browser laufen auf demselben Geraet."""
        if not state.is_connected():
            return u'Kein Sensor verbunden'
        if raw and not points:
            return u'Warte auf Rohwerte'
        if points:
            return None
        due = state.next_point_at()
        if due is None:
            return None
        return u'Erster Mittelwert um {0}'.format(_clock_label(due))

    @app.route('/chart.svg')
    def chart_svg():
        """Das Diagramm als SVG, gezeichnet aus dem Verlauf. w und h sind
        die echte Groesse auf der Seite, damit die Schrift nicht skaliert."""
        # Erst hier importiert: so laufen die uebrigen Routen auch ohne
        # chart.py.
        import chart
        range_s = _int_query('range', 3600)
        if range_s not in CHART_RANGES:
            range_s = 3600
        series = _query('series', u'mean')
        raw = series == u'raw'
        width = _clamp(_int_query('w', 640), 240, 1600)
        height = _clamp(_int_query('h', 320), 140, 900)
        now = time.time()
        # Der ganze Verlauf: den Zeitraum schneidet chart.py selbst zu und
        # unterscheidet so "nichts im Zeitraum" von "noch gar nichts".
        points = state.raw_history() if raw else state.history()
        svg = chart.render_svg(points, now, range_s=range_s, width=width,
                               height=height, interval=state.record_interval(),
                               message=_chart_message(points, raw=raw))
        response.content_type = 'image/svg+xml; charset=utf-8'
        response.set_header('Cache-Control', 'no-store')
        return svg.encode('utf-8')

    @app.route('/status/')
    def status():
        """Alles, was die Oberflaeche bei der Statusabfrage anzeigt."""
        snap = state.snapshot()
        now = time.time()
        age = state.measurement_age()
        fresh = _measurement_fresh_for_status(snap, age)
        stat_pos_ok, stat_pos_distance, stat_pos_limit = _stationary_position_check(state)
        active_place = snap['trip_name'] if snap['recording'] else snap['place']
        ret_data = {
            'value': snap['status_text'],
            'lat': '%.5f' % float(snap['lat']),
            'lon': '%.5f' % float(snap['lon']),
            'gps_available': snap['gps_available'],
            'gps_age': _int_or_none(state.gps_age()),
            'gps_max_age': config.GPS_MAX_AGE,
            'pm_10': '%6.1f' % snap['pm_10'],
            'pm_10_color': kml.color_selection_rgb(snap['pm_10'], 'pm_10'),
            'pm_25': '%6.1f' % snap['pm_25'],
            'pm_25_color': kml.color_selection_rgb(snap['pm_25'], 'pm_25'),
            'error_msg': snap['error_msg'],
            # Die Knoepfe richten sich nach diesen Werten, nicht nach
            # dem letzten Klick; so stimmen sie auch nach einem Reload.
            'recording': snap['recording'],
            'local': snap['local'],
            'stationary': snap['stationary'],
            'place': active_place,
            'trip_name': snap['trip_name'],
            'connection': snap['connection'],
            'connection_error': snap['connection_error'],
            'connection_wanted': snap['connection_wanted'],
            'device': snap['device'] or '',
            'device_name': snap['device_name'],
            # Erfundene Werte: die Oberflaeche kennzeichnet sie und sperrt
            # den stationaeren Modus.
            'simulated': config.is_simulation(snap['device']),
            'interval': snap['record_interval'],
            'intervals': list(config.RECORD_INT_CHOICES),
            'stationary_intervals': list(config.STATIONARY_RECORD_INT_CHOICES),
            'measurement_age': _int_or_none(age),
            'measurement_usable': snap['measurement_usable'],
            # Einstufung nur fuer einen frischen Wert; ein alter bliebe
            # nach einem Abbruch sonst gruen stehen.
            'pm_25_level': kml.level(snap['pm_25'], 'pm_25') if fresh else 'none',
            'pm_10_level': kml.level(snap['pm_10'], 'pm_10') if fresh else 'none',
            'history_rev': snap['history_rev'],
            'raw_history_rev': snap['raw_history_rev'],
            'next_point_in': _seconds_until(snap['next_point_at'], now),
            'session': _session_view(snap['session'], now),
            'upload': _upload_view(snap['upload_info'], now),
            'outdir': to_text(config.OUTDIR),
            'stat_interval': config.STAT_INT,
            'stationary_position_ok': stat_pos_ok,
            'stationary_distance_m': stat_pos_distance,
            'stationary_max_distance_m': stat_pos_limit,
        }
        return ret_data

    @app.route('/__exit', method=['GET', 'HEAD'])
    def exit_route():
        write_log(0, 'exit-route!')
        state.shutdown()
        if on_shutdown is not None:
            # Eigener Thread: on_shutdown wartet auf das Ende der
            # Mess-Threads und stoppt zuletzt den Webserver; im
            # Request-Handler hielte das die Antwort auf.
            worker = threading.Thread(target=on_shutdown)
            worker.daemon = True
            worker.start()
        return {'value': u'...und Tschüss!'}

    return app
