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

# Wohin Messdateien und Log unter Android geschrieben werden. Download/
# erreicht jeder Dateimanager ohne PC -- anders als Android/data/, das
# nur QPython selbst lesen darf. Ist das Verzeichnis nicht beschreibbar
# oder steht hier None, landet alles in output/ neben dem Programm.
ANDROID_OUTDIR = '/storage/emulated/0/Download/Feinstaub'

##
## ENDE DER KONFIGURATIONSOPTIONEN
##

BASEDIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_OUTDIR = os.path.join(BASEDIR, 'output')
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


def is_writable_dir(path):
    """Legt path bei Bedarf an und prueft mit einer Probedatei, ob
    geschrieben werden darf. os.access() luegt unter Android, wenn der
    Speicher per Berechtigung gesperrt ist."""
    probe = os.path.join(path, '.schreibtest')
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
        with open(probe, 'w') as handle:
            handle.write('ok')
        os.remove(probe)
        return True
    except (OSError, IOError):
        return False


def choose_outdir(android=None, preferred=None):
    """Ausgabeverzeichnis: unter Android ANDROID_OUTDIR, sofern
    beschreibbar, sonst output/ neben dem Programm."""
    if android is None:
        android = on_android()
    if preferred is None:
        preferred = ANDROID_OUTDIR
    if android and preferred and is_writable_dir(preferred):
        return preferred
    return FALLBACK_OUTDIR


def use_fake_hardware():
    """Steuert, ob echte oder simulierte Hardware benutzt wird.

    Standard ist echte Hardware -- auf dem Geraet wie am PC, wo der
    Sensor per Bluetooth angesprochen wird. SDS011_FAKE=1 schaltet die
    Simulation ein (zum Entwickeln ohne Sensor).
    """
    value = os.environ.get('SDS011_FAKE')
    if value is None:
        return False
    return value.strip().lower() not in ('', '0', 'false', 'no')


# Erst hier, weil choose_outdir() die Funktionen oben braucht.
OUTDIR = choose_outdir()
LOGFILE = os.path.join(OUTDIR, 'logfile.txt')
