# -*- coding: utf-8 -*-
"""Konfiguration. Importiert nichts aus dem Projekt.

Laeuft unter Python 2.7 (QPython 2) und Python 3.x (QPython 3L),
deshalb os.path statt pathlib.
"""

from __future__ import absolute_import

import os

##
## START DER KONFIGURATIONSOPTIONEN
##

# 0 = nur Fehler, 1 = Betriebsmeldungen, 2 = Details, 3 = Protokoll-Debug
LOG_LEVEL = 1

# Intervall in Sekunden, in dem ein Messwert in KML/CSV geschrieben wird.
KML_INT = 5
# Intervall in Sekunden, in dem die GPS-Position neu gelesen wird.
GPS_INT = 5
# Intervall in Sekunden zwischen zwei Uploads im stationaeren Modus.
STAT_INT = 240

SSP_UUID = '00001101-0000-1000-8000-00805F9B34FB'
# RFCOMM-Kanal auf dem Desktop. HC05/HC06 bieten SPP ueblicherweise
# auf Kanal 1 an; die Standardbibliothek kann keine Dienstsuche.
RFCOMM_CHANNEL = 1
# Bluetooth MAC-Adresse des HC05/HC06-Moduls, welches die Verbindung
# zum SDS011-Sensor herstellt.
SDS011_BLUETOOTH_DEVICE_ID = '00:14:03:05:59:17'
# https://deutschland.maps.sensor.community/#16/51.4385/6.7882
XSENSOR = 'raspi-00000000a5c85ba8'
LUFTDATEN_URL = 'https://api.luftdaten.info/v1/push-sensor-data/'

HTTP_HOST = '0.0.0.0'
HTTP_PORT = 8080

##
## ENDE DER KONFIGURATIONSOPTIONEN
##

BASEDIR = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(BASEDIR, 'output')
LOGFILE = os.path.join(OUTDIR, 'logfile.txt')
TEMPLATEDIR = os.path.join(BASEDIR, 'views')
STATICDIR = os.path.join(BASEDIR, 'static')


def ensure_outdir():
    """Legt das Ausgabeverzeichnis an. os.makedirs(exist_ok=) gibt es
    unter Python 2 nicht."""
    if not os.path.isdir(OUTDIR):
        try:
            os.makedirs(OUTDIR)
        except OSError:
            if not os.path.isdir(OUTDIR):
                raise
    return OUTDIR


def http_port():
    """Port des Webservers, per SDS011_PORT ueberschreibbar.

    Unter Windows koennen sich dank SO_REUSEADDR mehrere Prozesse an
    denselben Port binden, ohne dass der zweite einen Fehler bekommt --
    Testlaeufe treffen sonst versehentlich eine alte Instanz.
    """
    return int(os.environ.get('SDS011_PORT') or HTTP_PORT)


def on_android():
    """True, wenn wir unter QPython auf einem Geraet laufen."""
    return os.environ.get('ANDROID_ROOT') is not None


def use_fake_hardware():
    """Steuert, ob echte oder simulierte Hardware benutzt wird.

    SDS011_FAKE=1 erzwingt die Simulation (auch auf dem Geraet),
    SDS011_FAKE=0 erzwingt echte Hardware. Ohne die Variable
    entscheidet die Plattform.
    """
    value = os.environ.get('SDS011_FAKE')
    if value is not None:
        return value.strip().lower() not in ('', '0', 'false', 'no')
    return not on_android()
