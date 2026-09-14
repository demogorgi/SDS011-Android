#qpy:webapp:Feinstaubmessung
#qpy://localhost:8080/
# -*- coding: utf-8 -*-
"""Mobile Feinstaubmessung mit SDS011 unter QPython.

Siehe: https://edu.qpython.org/qpython-webapp/your-first-webapp.html

Skript basiert auf den Quellen
  https://github.com/optiprime
  https://www.byteyourlife.com/

Dieses Modul verdrahtet nur noch die Bausteine. Die Konfiguration liegt
in config.py.
"""

from __future__ import absolute_import

import sys

import bottle

import config
import gps
import sensor
import transport
import webapp
from logging_util import write_log, reset_logfile
from recorder import Recorder
from state import AppState


def build_threads(state):
    """Legt die drei Arbeits-Threads an."""
    gps_source = gps.create_gps(state)
    gps_reader = gps.GpsReader(state, gps_source)

    sensor_transport = transport.create_transport(state)
    sensor_reader = sensor.SensorReader(state, sensor_transport)

    recorder = Recorder(state)
    return gps_reader, sensor_reader, recorder


def main():
    config.ensure_outdir()
    reset_logfile()
    write_log(1, 'Start, Python {0}'.format(sys.version.split()[0]))
    write_log(1, 'Android: {0}, simulierte Hardware: {1}'.format(
        config.on_android(), config.use_fake_hardware()))

    state = AppState()

    droid = None
    if config.on_android():
        import androidhelper
        droid = androidhelper.Android()
        droid.wakeLockAcquirePartial()

    gps_reader, sensor_reader, recorder = build_threads(state)

    def shutdown():
        state.shutdown()
        for thread, name in ((recorder, 'recorder'),
                             (sensor_reader, 'sds011'),
                             (gps_reader, 'gps')):
            if hasattr(thread, 'stop'):
                thread.stop()
            thread.join(10)
            write_log(0, '{0} beendet (alive={1})'.format(name, thread.is_alive()))
        if droid is not None:
            try:
                droid.wakeLockRelease()
                droid.exit()
            except Exception as exc:
                write_log(0, 'droid.exit fehlgeschlagen: {0}'.format(exc))
        write_log(0, '...und Tschuess!')

    gps_reader.start()
    sensor_reader.start()
    recorder.start()
    write_log(1, 'Threads gestartet')

    app = webapp.create_app(state, on_shutdown=shutdown)
    try:
        bottle.run(app=app, host=config.HTTP_HOST, port=config.HTTP_PORT,
                   quiet=False)
    except KeyboardInterrupt:
        write_log(0, 'Abbruch per Tastatur')
    finally:
        shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        write_log(0, 'Abbruch: {0}'.format(exc))
        raise
