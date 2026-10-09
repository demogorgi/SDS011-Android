# -*- coding: utf-8 -*-
"""Webserver. Kennt nur den AppState, keine Threads und keine Hardware.

Wichtig: hier wird eine Bottle()-Instanz benutzt statt der
Modul-Dekoratoren. Dadurch faellt der Import von bottle.run weg, der
frueher die Aufzeichnungs-Flagge 'run' ueberschrieben hat.
"""

from __future__ import absolute_import

import threading

from bottle import Bottle, request, static_file, template

import config
import kml
from logging_util import write_log


# Absolut, damit es nicht auf das Arbeitsverzeichnis ankommt -- das ist
# je nach QPython-Version ein anderes. Frueher stand hier lookup= statt
# template_lookup=; bottle nahm das als Template-Variable und suchte in
# ./views/, was nur klappte, wenn zufaellig im Projektordner gestartet
# wurde. Eine feste Liste, weil bottle den Template-Cache ueber ihre
# id() fuehrt.
TEMPLATE_LOOKUP = [config.TEMPLATEDIR]

def _query(name, default=u''):
    """Einen Query-Parameter als Text lesen.

    bottle dekodiert Query-Werte latin-1; aus %C3%BC wuerde sonst
    Buchstabensalat statt eines Umlauts. getunicode() rechnet das um,
    ist aber nicht in jeder bottle-Version vorhanden -- daher der
    Rueckfall.
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


def create_app(state, on_shutdown=None, transport=None):
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
        """Gekoppelte Geraete zur Auswahl. Damit muss die MAC-Adresse
        nicht mehr im Quelltext stehen."""
        found = []
        if transport is not None:
            try:
                found = transport.available_devices()
            except Exception as exc:
                write_log(0, 'Geraeteliste nicht lesbar: {0}'.format(exc))
                state.report_error(u'Geraeteliste nicht lesbar: {0}'.format(exc))
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
        write_log(1, 'Verbindung angefordert: {0}'.format(device_id or 'Standard'))
        return {'value': u'Verbindung wird aufgebaut...'}

    @app.route('/disconnect/')
    def disconnect():
        state.connection_wanted = False
        write_log(1, 'Trennung angefordert')
        return {'value': u'Verbindung getrennt.'}

    def _requires_sensor(what):
        """Ohne verbundenen Sensor entstuenden Dateien voller Nullen --
        die sehen aus wie eine echte Messung. Auch serverseitig
        abgelehnt, damit eine veraltete Seite es nicht doch ausloest."""
        if state.is_connected():
            return None
        message = u'%s nicht moeglich: kein Sensor verbunden.' % what
        state.report_error(message)
        write_log(1, message)
        return {'value': message, 'refused': True}

    @app.route('/start/')
    def start_measure():
        refused = _requires_sensor(u'Aufzeichnung')
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
        # Hier waere es besonders unangenehm: der stationaere Modus
        # laedt die Werte zu api.luftdaten hoch. Nullen aus einem nicht
        # verbundenen Sensor landeten in einem oeffentlichen Datensatz.
        refused = _requires_sensor(u'Stationaerer Modus')
        if refused:
            return refused
        state.recording = False
        state.local = False
        state.stationary = True
        state.clear_error()
        state.set_status(u'Stationaerer Modus aktiv.')
        return {'value': u'Stationaerer Modus gestartet.'}

    @app.route('/statoff/')
    def stopp_stat():
        state.stationary = False
        state.set_status(u'Stationaerer Modus inaktiv.')
        return {'value': u'Stationaerer Modus gestoppt.'}

    # -- Lokale Messung: nur Datei, kein Upload ------------------------
    @app.route('/localon/')
    def start_local():
        refused = _requires_sensor(u'Lokale Messung')
        if refused:
            return refused
        state.set_place(_query('place'))
        state.recording = False
        # Ausdruecklich: die lokale Messung laedt nichts hoch. Das
        # passiert nur im stationaeren Modus.
        state.stationary = False
        state.local = True
        state.clear_error()
        place = state.place()
        state.set_status(u'Lokale Messung aktiv%s.'
                         % (u' - ' + place if place else u''))
        write_log(1, 'Lokale Messung gestartet: {0}'.format(place or '(ohne Ort)'))
        return {'value': u'Lokale Messung gestartet. Es wird nichts hochgeladen.'}

    @app.route('/localoff/')
    def stopp_local():
        state.local = False
        state.set_status(u'Lokale Messung beendet.')
        write_log(1, 'Lokale Messung beendet')
        return {'value': u'Lokale Messung beendet.'}

    @app.route('/status/')
    def status():
        snap = state.snapshot()
        ret_data = {
            'value': snap['status_text'],
            'lat': '%.5f' % float(snap['lat']),
            'lon': '%.5f' % float(snap['lon']),
            'pm_10': '%6.1f' % snap['pm_10'],
            'pm_10_color': kml.color_selection_rgb(snap['pm_10'], 'pm_10'),
            'pm_25': '%6.1f' % snap['pm_25'],
            'pm_25_color': kml.color_selection_rgb(snap['pm_25'], 'pm_25'),
            'error_msg': snap['error_msg'],
            # Damit das Frontend den Button-Zustand aus dem Server
            # ableiten kann statt aus dem letzten Klick -- nach einem
            # Reload stimmte er sonst nicht mehr.
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
            # Nicht im Request-Handler joinen -- das blockierte frueher
            # die Antwort, bis alle sleep()s durchgelaufen waren.
            worker = threading.Thread(target=on_shutdown)
            worker.daemon = True
            worker.start()
        return {'value': u'...und Tschuess!'}

    return app
