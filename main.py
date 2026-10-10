#qpy:webapp:Feinstaubmessung
#qpy://localhost:8080/
# -*- coding: utf-8 -*-
"""Mobile Feinstaubmessung mit SDS011 -- Startpunkt der App.

Startet GPS-Leser, Sensor-Leser und Recorder als Threads, dann den
Webserver mit der Oberflaeche, und faehrt beim Beenden alles geordnet
herunter. Messen, Orten und Aufzeichnen stecken in sensor, gps und
recorder; die Einstellungen stehen in config.py.

Die #qpy-Zeilen oben machen das Skript zur QPython-Webapp: QPython
oeffnet nach dem Start die angegebene Adresse, siehe
https://edu.qpython.org/qpython-webapp/your-first-webapp.html

Basiert auf den Quellen von https://github.com/optiprime und
https://www.byteyourlife.com/
"""

from __future__ import absolute_import

import sys
import threading

import bottle

import config
import gps
import sensor
import transport
import webapp
from logging_util import rotate_logfile, to_text, write_log
from recorder import Recorder
from server import StoppableWSGIRefServer
from state import AppState


def build_threads(state):
    """Legt GPS-Leser, Sensor-Leser und Recorder an, ohne sie zu starten.

    Liefert zusaetzlich den Transport zum Sensor, ueber den die
    Oberflaeche die Liste der Bluetooth-Geraete abfragt.
    """
    gps_source = gps.create_gps(state)
    gps_reader = gps.GpsReader(state, gps_source)

    sensor_transport = transport.create_transport()
    sensor_reader = sensor.SensorReader(state, sensor_transport)

    recorder = Recorder(state)
    return gps_reader, sensor_reader, recorder, sensor_transport


def main():
    """Startet die App und kehrt erst zurueck, wenn sie beendet ist."""
    config.ensure_outdir()
    rotate_logfile()
    write_log(1, u'Start, Python {0}'.format(sys.version.split()[0]))
    write_log(1, u'Android: {0}, simulierte Hardware: {1}'.format(
        config.on_android(), config.use_fake_hardware()))
    write_log(1, u'Ausgabeverzeichnis: {0}'.format(to_text(config.OUTDIR)))

    state = AppState()

    droid = None
    if config.on_android():
        import androidhelper
        droid = androidhelper.Android()
        # Haelt die CPU wach, wenn der Bildschirm ausgeht -- sonst
        # stocken Messung und GPS, sobald das Handy in der Tasche ist.
        droid.wakeLockAcquirePartial()

    gps_reader, sensor_reader, recorder, sensor_transport = build_threads(state)

    srv = StoppableWSGIRefServer(host=config.http_host(), port=config.http_port())

    # Beim Beenden ueber /__exit laeuft shutdown() zweimal: zuerst in
    # dem Thread, den die Route startet, dann aus dem finally unten,
    # sobald bottle.run() zurueckkehrt. Der Lock laesst den zweiten
    # Aufrufer warten, bis der erste fertig ist, statt ihn mittendrin
    # abzuschneiden; danach kehrt er sofort zurueck.
    shutdown_lock = threading.Lock()
    shutdown_state = {'done': False}

    def shutdown():
        with shutdown_lock:
            if shutdown_state['done']:
                return
            shutdown_state['done'] = True

            state.shutdown()
            for thread, name in ((recorder, 'recorder'),
                                 (sensor_reader, 'sds011'),
                                 (gps_reader, 'gps')):
                if hasattr(thread, 'stop'):
                    try:
                        thread.stop()
                    except Exception as exc:
                        write_log(0, u'{0}.stop() fehlgeschlagen: {1}'.format(name, to_text(exc)))
                thread.join(10)
                write_log(1, u'{0} beendet (alive={1})'.format(name, thread.is_alive()))

            if droid is not None:
                try:
                    droid.wakeLockRelease()
                    droid.exit()
                except Exception as exc:
                    write_log(0, u'droid.exit fehlgeschlagen: {0}'.format(to_text(exc)))

            # Zuletzt der Webserver -- danach kehrt bottle.run() zurueck.
            srv.stop(timeout=2.0)
            write_log(0, '...und Tschuess!')

    gps_reader.start()
    sensor_reader.start()
    recorder.start()
    write_log(1, 'Threads gestartet')

    app = webapp.create_app(state, on_shutdown=shutdown,
                            transport=sensor_transport)
    try:
        bottle.run(app=app, server=srv)
    except KeyboardInterrupt:
        write_log(0, 'Abbruch per Tastatur')
    finally:
        shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        write_log(0, u'Abbruch: {0}'.format(to_text(exc)))
        raise
