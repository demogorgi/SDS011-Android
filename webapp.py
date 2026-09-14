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


def create_app(state, on_shutdown=None, transport=None):
    app = Bottle()

    @app.route('/')
    def index():
        return template('index.html', lookup=[config.TEMPLATEDIR])

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
            selected = found[0]['id']
        return {'devices': found, 'selected': selected}

    @app.route('/connect/')
    def connect():
        device_id = request.query.get('device') or None
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

    @app.route('/start/')
    def start_measure():
        state.recording = True
        state.stationary = False
        state.set_status(u'Aufzeichnung aktiv.')
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
        state.recording = False
        state.stationary = True
        state.set_status(u'Stationaerer Modus aktiv.')
        return {'value': u'Stationaerer Modus gestartet.'}

    @app.route('/statoff/')
    def stopp_stat():
        state.stationary = False
        state.set_status(u'Stationaerer Modus inaktiv.')
        return {'value': u'Stationaerer Modus gestoppt.'}

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
            'stationary': snap['stationary'],
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
