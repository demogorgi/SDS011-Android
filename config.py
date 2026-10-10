# -*- coding: utf-8 -*-
"""Einstellungen der App und Erkennung der Laufumgebung.

Der Block zwischen START und ENDE DER KONFIGURATIONSOPTIONEN ist zum
Anpassen gedacht. Darunter stehen die
abgeleiteten Pfade und Hilfsfunktionen: Android oder PC, echte oder
simulierte Hardware, Wahl des Ausgabeverzeichnisses. Importiert nichts
aus dem Projekt, damit jedes Modul es ohne Zirkelimport laden kann.
Laeuft unter Python 2.7 und 3, deshalb os.path statt pathlib.
"""

from __future__ import absolute_import

import os

##
## START DER KONFIGURATIONSOPTIONEN
##

# 0 = nur Fehler, 1 = Betriebsmeldungen, 2 = Details, 3 = Protokoll-Debug
LOG_LEVEL = 1

# Takt in Sekunden, in dem Messfahrt und lokale Messung einen Messpunkt
# schreiben (KML/CSV).
KML_INT = 5
# Intervall in Sekunden, in dem die GPS-Position neu gelesen wird.
GPS_INT = 5
# Kommt so viele Sekunden keine neue Position, wird das GPS ab- und
# wieder angemeldet (wirksam nur unter Android). Bleibt es stumm,
# verdoppelt sich die Wartezeit bis zu GPS_RESTART_MAX.
GPS_RESTART_AFTER = 60
GPS_RESTART_MAX = 600
# Hoechstalter in Sekunden der letzten neuen GPS-Position. Ist sie
# aelter, bleiben die Koordinaten in CSV und Spur leer, und die Spur
# beginnt danach neu statt mit einer geraden Linie von der alten
# Position. Dieselbe Schwelle gilt fuer die Anzeige "GPS: aktuell".
GPS_MAX_AGE = 15
# Intervall in Sekunden zwischen zwei Uploads im stationaeren Modus.
STAT_INT = 240
# Hoechstalter in Sekunden eines Messwerts, der aufgezeichnet oder
# hochgeladen wird. Der Sensor sendet etwa einmal pro Sekunde -- bleibt
# er laenger stumm, ist die Verbindung weg.
MAX_MEASUREMENT_AGE = 10

# UUID des Serial Port Profile (SPP), ueber das Android die Verbindung
# zum Bluetooth-Modul aufbaut.
SSP_UUID = '00001101-0000-1000-8000-00805F9B34FB'
# RFCOMM-Kanal am PC. Fest eingetragen, weil die Standardbibliothek
# keine Dienstsuche kann; HC05/HC06 bieten SPP ueblicherweise auf
# Kanal 1 an.
RFCOMM_CHANNEL = 1
# Bluetooth MAC-Adresse des HC05/HC06-Moduls, welches die Verbindung
# zum SDS011-Sensor herstellt.
SDS011_BLUETOOTH_DEVICE_ID = '00:14:03:05:59:17'
# Sensor-ID fuer den Upload zu sensor.community (Header X-Sensor) im
# stationaeren Modus. Karte:
# https://deutschland.maps.sensor.community/#16/51.4385/6.7882
XSENSOR = 'raspi-00000000a5c85ba8'
LUFTDATEN_URL = 'https://api.luftdaten.info/v1/push-sensor-data/'

# Nur auf dem Geraet selbst erreichbar. Mit 0.0.0.0 koennte jeder im
# selben WLAN die GPS-Position lesen, die App beenden oder den
# oeffentlichen Upload starten. Per SDS011_HOST ueberschreibbar.
HTTP_HOST = '127.0.0.1'
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
    """Legt das Ausgabeverzeichnis an und liefert seinen Pfad.

    Ohne os.makedirs(exist_ok=), das es unter Python 2 nicht gibt; der
    zweite isdir-Test faengt ab, dass es gerade jemand anders anlegt.
    """
    if not os.path.isdir(OUTDIR):
        try:
            os.makedirs(OUTDIR)
        except OSError:
            if not os.path.isdir(OUTDIR):
                raise
    return OUTDIR


def http_host():
    """Adresse des Webservers, per SDS011_HOST ueberschreibbar."""
    return os.environ.get('SDS011_HOST') or HTTP_HOST


def http_port():
    """Port des Webservers, per SDS011_PORT ueberschreibbar.

    Testlaeufe sollten einen eigenen Port waehlen: Unter Windows binden
    sich dank SO_REUSEADDR mehrere Prozesse ohne Fehler an denselben
    Port, und ein Test landet sonst unbemerkt bei einer alten Instanz.
    """
    return int(os.environ.get('SDS011_PORT') or HTTP_PORT)


def on_android():
    """True unter Android, erkannt an ANDROID_ROOT, das Android jedem
    Prozess setzt."""
    return os.environ.get('ANDROID_ROOT') is not None


def is_writable_dir(path):
    """Legt path bei Bedarf an und prueft mit einer Probedatei, ob
    geschrieben werden darf. Liefert True oder False.

    Nicht os.access(): das meldet unter Android Schreibrecht, auch wenn
    der Speicher per Berechtigung gesperrt ist.
    """
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
    beschreibbar, sonst output/ neben dem Programm.

    android und preferred ersetzen fuer Tests die Erkennung bzw.
    ANDROID_OUTDIR.
    """
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


# Erst hier, weil choose_outdir() die Funktionen oben braucht. Wird
# einmal beim Import festgelegt; unter Android legt die Pruefung
# ANDROID_OUTDIR dabei schon an.
OUTDIR = choose_outdir()
LOGFILE = os.path.join(OUTDIR, 'logfile.txt')
