# -*- coding: utf-8 -*-
"""HTTP-Routen der Oberflaeche (bottle).

create_app() baut die App fuer main.py. Die Routen lesen und setzen den
AppState und fragen beim Transport die gekoppelten Geraete ab; die
Hardware bedienen sie nicht. Sensor, GPS und Aufzeichnung laufen in
eigenen Threads und reagieren auf den Zustand.

Eine eigene Bottle()-Instanz statt der globalen Modul-Dekoratoren:
jeder Aufruf liefert eine unabhaengige App.
"""

from __future__ import absolute_import

import threading

from bottle import Bottle, request, static_file, template

import config
import kml
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


def create_app(state, on_shutdown=None, transport=None):
    """Die Bottle-App mit allen Routen bauen.

    state: der gemeinsame AppState. on_shutdown: wird von /__exit in
    einem eigenen Thread gerufen. transport: liefert die gekoppelten
    Geraete fuer /devices/ und /connect/; ohne ihn bleibt die Liste leer.
    """
    app = Bottle()

    @app.route('/')
    def index():
        return template('index.html', template_lookup=TEMPLATE_LOOKUP,
                        xsensor=config.XSENSOR, outdir=config.OUTDIR)

    @app.route('/static/<filename:path>')
    def serve_static(filename):
        return static_file(filename, root=config.STATICDIR)

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

    # Pruefen und Umschalten in einem Zug -- der Webserver bearbeitet
    # Anfragen parallel, zwei Starts zugleich ergaeben sonst zwei Modi.
    mode_lock = threading.Lock()

    @app.route('/start/')
    def start_measure():
        with mode_lock:
            return _start_measure()

    def _start_measure():
        refused = (_requires_sensor(u'Messfahrt')
                   or _requires_no_other_mode(u'Messfahrt'))
        if refused:
            return refused
        state.recording = True
        state.local = False
        state.stationary = False
        state.clear_error()
        state.set_status(u'Messfahrt aktiv.')
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
                   or _requires_no_other_mode(u'Stationärer Modus'))
        if refused:
            return refused
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

    @app.route('/status/')
    def status():
        """Alles, was die Oberflaeche bei der Statusabfrage anzeigt."""
        snap = state.snapshot()
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
            'place': snap['place'],
            'connection': snap['connection'],
            'connection_error': snap['connection_error'],
            'connection_wanted': snap['connection_wanted'],
            'device': snap['device'] or '',
            'device_name': snap['device_name'],
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
