# -*- coding: utf-8 -*-
"""Webserver. Kennt nur den AppState, keine Threads und keine Hardware.

Wichtig: hier wird eine Bottle()-Instanz benutzt statt der
Modul-Dekoratoren. Dadurch faellt der Import von bottle.run weg, der
frueher die Aufzeichnungs-Flagge 'run' ueberschrieben hat.
"""

from __future__ import absolute_import

import threading

from bottle import Bottle, static_file, template

import config
import kml
from logging_util import write_log


def create_app(state, on_shutdown=None):
    app = Bottle()

    @app.route('/')
    def index():
        return template('index.html', lookup=[config.TEMPLATEDIR])

    @app.route('/static/<filename:path>')
    def serve_static(filename):
        return static_file(filename, root=config.STATICDIR)

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
