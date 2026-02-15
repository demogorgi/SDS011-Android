#qpy:webapp:Feinstaubmessung
#qpy://localhost:8080/
"""
Siehe: https://edu.qpython.org/qpython-webapp/your-first-webapp.html
"""

##
## Skript basiert auf den Quellen
## https://github.com/optiprime
## https://www.byteyourlife.com/
## START DER KONFIGURATIONSOPTIONEN
##

LOG_LEVEL = 1

from pathlib import Path
BASEDIR = Path(__file__).resolve().parent
OUTDIR_PATH = BASEDIR / "output"
OUTDIR_PATH.mkdir(parents=True, exist_ok=True)
OUTDIR      = str(OUTDIR_PATH)                 # <-- String, damit OUTDIR + "/..." wieder geht
LOGFILE     = str(OUTDIR_PATH / "logfile.txt")
TEMPLATEDIR = str(BASEDIR / "views")
STATICDIR   = str(BASEDIR / "static")

KML_INT = 5
GPS_INT = 5
SSP_UUID = '00001101-0000-1000-8000-00805F9B34FB'
# Bluetooth MAC-Addresse des HC05/HC06-Moduls, welcher die Verbindung zum SDS011-Sensor herstellt.
SDS011_bluetooth_device_id = '00:14:03:05:59:17'
# https://deutschland.maps.sensor.community/#16/51.4385/6.7882
XSENSOR = 'raspi-00000000a5c85ba8'

##
## ENDE DER KONFIGURATIONSOPTIONEN
##

import sys
import os
import time
import string
import struct
import datetime
from threading import Thread
import threading
import androidhelper
import base64
import select
import subprocess
import requests
# See: https://github.com/qpython-android/qpython3/issues/61
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = "TLS13-CHACHA20-POLY1305-SHA256:TLS13-AES-128-GCM-SHA256:TLS13-AES-256-GCM-SHA384:ECDHE:!COMPLEMENTOFDEFAULT"

import kml

global sensing
sensing = True

global g_lat, g_lng, g_utc
g_lat = 0
g_lng = 0
g_utc = datetime.datetime.utcnow()

# Aufzeichnung ja/nein
global run
run = False

# Stationär ja/nein
global run_stat
run_stat = False

global status_text
status_text = "inaktiv"

global display_lat
global display_lon

display_lat = "keine GPS Aufzeichnung aktiv"
display_lon = "keine GPS Aufzeichnung aktiv"

global pm_10
global pm_25
pm_10 = 0
pm_25 = 0

global error_msg
error_msg = ""

# Funktion fuer das Erfassen von Fehlermeldungen
# die waehrend dem Ablauf des Progammes entstehen koennen.
def write_log(level, msg):
  if level <= LOG_LEVEL:
    global error_msg
    error_msg = msg
    message = msg
    fname = LOGFILE
    with open(fname,'a+') as file:
      file.write(str(message))
      file.write("\n")
      file.close()

# Klasse um auf den GPSD Stream via Thread zuzugreifen.
class GpsdStreamReader(threading.Thread):
  def __init__(self):
    global g_lat, g_lng, g_utc
    threading.Thread.__init__(self)

    self.droid = androidhelper.Android()
    self.droid.startLocating(5000, 10)
    g_lat, g_lng = self.getGpsData()
    g_utc = datetime.datetime.utcnow()
    self.current_value = None
    # Der Thread wird ausgefuehrt
    self.running = True

  def run(self):
    global g_lat, g_lng, g_utc
    while t_gps.running:
      # Lese den naechsten Datensatz von GPSD
      g_lat, g_lng = self.getGpsData()
      time.sleep(GPS_INT)

  def getGpsData(self):
    lat = 0
    lng = 0

    loc = self.droid.readLocation().result
    if loc == {}:
      loc = self.droid.getLastKnownLocation().result
    if loc != {}:
      try:
        n = loc['gps']
      except KeyError:
        n = loc['network']
      if n != None:
        lat = n['latitude']
        lng = n['longitude']
    return (lat, lng)

  def stop(self):
    self.running = False
    self.droid.stopLocating()
    self.droid.exit()
    write_log(0, "locatingStop!")
# Ende: Klasse um auf den GPSD Stream via Thread zuzugreifen.

# Klasse um auf den SDS011 Sensor via Thread zuzugreifen.
class SDS011StreamReader(threading.Thread):
  def __init__(self):
    global byte
    global lastbyte
    # Variablen fuer die Messwerte vom Feinstaubsensor.
    byte, lastbyte = '\\x00', '\\x00'

    threading.Thread.__init__(self)

    self.droid = androidhelper.Android()
    self.connID = None

    self.current_value = None
    # Der Thread wird ausgefuehrt
    self.running = True

  def run(self):
    global pm_25
    global pm_10
    global byte
    global lastbyte

    while t_sds011.running:
      lastbyte = byte
      byte = self.getBluetoothData(1)
      time.sleep(1)

      # Wenn es ein gültiges Datenpaket gibt bearbeite dieses
      write_log(3, 'lastbyte={}, byte={}'.format(lastbyte, byte))
      exlastbyte = '\\xaa'
      exbyte = '\\xc0'
      if lastbyte == exlastbyte and byte == exbyte:
        write_log(3, "\n lastbyte {} und byte {} passen zur Erwartung {} und {}. \n".format(lastbyte, byte, exlastbyte, exbyte))
        try:
          # Es werden 8 Byte eingelesen.
          sentence = self.getBluetoothData(8)
          write_log(3, "sentence: {}, class: {}, length: {}".format(sentence, sentence.__class__, len(sentence)))
          sentence = sentence.replace("\\/", "/").encode('latin-1').decode('unicode_escape').encode('latin-1')
          write_log(3, "sentence: {}, class: {}, length: {}".format(sentence, sentence.__class__, len(sentence)))
          # Das eingelesene Datenpaket wird dekodiert.
          readings = struct.unpack('<hhxxcc',sentence)
        except Exception as e:
          write_log(0, ("\n SDS011 Datenpaket kann nicht gelesen werden. \n"+str(e)))

        pm_25 = round(readings[0]/10.0, 3)
        pm_10 = round(readings[1]/10.0, 3)
        write_log(3, 'pm_25={}, pm_10={}'.format(pm_25, pm_10))
      else:
        write_log(3, "\n lastbyte {} und byte {} passen NICHT zur Erwartung {} und {}. \n".format(lastbyte, byte, exlastbyte, exbyte))

  def getBluetoothData(self, size):
    global error_msg

    buffer = ''
    while len(buffer) < size:
      while (len(self.droid.bluetoothActiveConnections().result) == 0):
        if self.connID != None:
          self.droid.bluetoothStop(self.connID)
          self.connID = None

        write_log(1, "Connecting/Reconnecting...")
        self.droid.toggleBluetoothState(True,False)
        success = self.droid.bluetoothConnect(SSP_UUID, SDS011_bluetooth_device_id)
        if success.error == None:
          self.connID = success.result
          write_log(1, "Connected")
        else:
          error_msg = "Problem beim Verbinden mit Feinstaubsensor!"
          write_log(0, error_msg)
          time.sleep(1)

      try:
        write_log(3, "TRY BLUETOOTH")
        result = self.droid.bluetoothReadBinary(size - len(buffer), self.connID).result
        write_log(3, "RESULT {} CLASS {}".format(result, result.__class__))
        if result != None:
          write_log(3, "TRY BUFFER")
          buffer += str(base64.b64decode(result))[2:-1]
          write_log(3, "BUFFER: {}".format(buffer))
      except Exception as e:
        write_log(0, "Cannot read bluetooth data: {}".format(e))
        time.sleep(1)

    error_msg = ""

    write_log(3, "getBluetoothData({}) {}".format(size, buffer))
    return buffer

  def stop(self):
    self.running = False
    self.droid.bluetoothStop(self.connID)
    self.droid.exit()
    write_log(0, "bluetoothStop!")
# Ende: Klasse um auf den SDS011 Sensor via Thread zuzugreifen.

def start_sensor():
  global sensing
  global run
  global display_lat
  global display_lon
  global pm_10
  global pm_25
  global pm_10_sum
  global pm_25_sum
  global avg_count
  global status_text
  global g_lat, g_lng, g_utc

  save_file = False

  # GPS Koordinaten-Variable Vorgaengerwert.
  lat_old = "initial"
  lon_old = "initial"

  # Feinstaubwerte 25 und 10 als Vorgaengerwert.
  pm_old_25 = 0
  pm_old_10 = 0

  pm_10_sum = 0
  pm_25_sum = 0
  avg_count = 0

  while sensing:

    while run:
      if save_file == False:
        fname25_line = OUTDIR + '/feinstaub_25_line_' + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.kml'
        fname10_line = OUTDIR + '/feinstaub_10_line_' + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.kml'
        fname_csv    = OUTDIR + '/feinstaub_'         + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.csv'
      save_file = True

      # Hier wird das Intervall gesetzt wie oft ein Wert
      # in die KML Datei geschrieben werden soll
      time.sleep(KML_INT)

      # Nur wenn eine gueltige FIX Positon bekannt ist
      # Zeichne die GPS Daten und Feinstaubwerte in einer
      # KML Datei auf.

      if -90 <= g_lat <= 90 and g_lat != 0:
        if lat_old == "initial":
          lat_old = g_lat

        if lon_old == "initial":
          lon_old = g_lng

        color_25 = kml.color_selection(pm_25)
        color_10 = kml.color_selection(pm_10)

        kml.write_kml_line(str(pm_25), str(pm_old_25), str(lon_old), str(lat_old), str(g_lat), str(g_lng), str(g_utc), fname25_line, "25", color_25)
        kml.write_kml_line(str(pm_10), str(pm_old_10), str(lon_old), str(lat_old), str(g_lat), str(g_lng), str(g_utc), fname10_line, "10", color_10)

        lat_old = g_lat
        lon_old = g_lng

        pm_old_25 = pm_25
        pm_old_10 = pm_10

      kml.write_csv(str(pm_25), str(pm_10), str(g_lat), str(g_lng), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fname_csv)

      pm_10_sum += pm_10
      pm_25_sum += pm_25
      avg_count += 1

      status_text = "Mittelwerte: {:.1f}, {:.1f}".format(pm_10_sum / avg_count, pm_25_sum / avg_count)

    if run == False:
      if save_file == True:
        # Hier werden die KML Dateien geschlossen.
        kml.close_kml(fname25_line)
        time.sleep(0.2)
        kml.close_kml(fname10_line)
        time.sleep(0.2)
        save_file = False

    while run_stat:
        status_text = ''
        headers = { 'Content-Type': 'application/json', 'X-Pin': '1', 'X-Sensor': XSENSOR }
        data = '{"software_version": "your_version", "sensordatavalues":[{"value_type":"P1","value":"' + str(pm_10) + '"},{"value_type":"P2","value":"' + str(pm_25) + '"}]}'
        response = requests.post('https://api.luftdaten.info/v1/push-sensor-data/', headers=headers, data=data, timeout=30)
        status_code = response.status_code
        if status_code == 201:
            status_text = "{}: Daten per api.luftdaten übertragen.".format(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        else:
            error_msg = "Fehler bei Datenübertragung, Status Code {}.".format(status_code)
        time.sleep(240)
        write_log(0, status_text)

  write_log(0, "sensingStop!")

# Hier folgt der Abschnitt fuer den Web-Server
from bottle import get, run, template, static_file, debug, route

@route('/')
def index():
  return template(TEMPLATEDIR + '/index.html', static_url=static_file)

@route('/static/<filename:path>')
def serve_static(filename):
    return static_file(filename, root=STATICDIR)

# >>>stationary mode
@route('/staton/', methods=['GET'])
def startstat():
       global run
       run = False
       global run_stat
       run_stat = True
       global status_text
       status_text = "Stationärer Modus aktiv."
       ret_data = {"value": "Stationärer Modus gestartet."}
       return ret_data

@route('/statoff/', methods=['GET'])
def stoppstat():
       global run_stat
       run_stat = False
       global status_text
       status_text = "Stationärer Modus inaktiv."
       ret_data = {"value": "Stationärer Modus gestoppt."}
       return ret_data
# <<<stationary mode

@route('/start/')
def start_measure():
  global run
  run = True
  global status_text
  status_text = "Aufzeichnung aktiv."
  ret_data = {"value": "Start der Aufzeichnung der Messwerte."}
  write_log(0, ret_data)
  return ret_data

@route('/stopp/')
def stopp():
  global run
  run = False
  global status_text
  status_text = "Aufzeichnung inaktiv."
  ret_data = {"value": "Aufzeichnung der Messwerte angehalten."}
  write_log(0, ret_data)
  return ret_data

@route('/status/')
def status():
  global status_text
  global display_lat
  global display_lon
  global pm_10
  global pm_25
  global error_msg

  display_lat = "%.5f" % float(g_lat)
  display_lon = "%.5f" % float(g_lng)
  ret_data = {"value": status_text, "lat": display_lat, "lon": display_lon,
      "pm_10": "%6.1f" % pm_10, "pm_10_color": kml.color_selection_rgb(pm_10, "pm_10"),
      "pm_25": "%6.1f" % pm_25, "pm_25_color": kml.color_selection_rgb(pm_25, "pm_25"),
      "error_msg": error_msg}
  write_log(3, ret_data)
  return ret_data

@route('/__exit', method=['GET','HEAD'])
def __exit():
  try:
    write_log(0, "exit-route!")
    global run
    global run_stat
    global sensing
    run = False
    run_stat = False
    sensing = False
    t_start_sensor.join()
    write_log(0, "sensing joined")
    t_sds011.stop()
    t_sds011.join()
    write_log(0, "sds11 joined")
    t_gps.stop()
    t_gps.join()
    write_log(0, "gps joined")
    droid.exit()
    write_log(0, "droid exit")
    write_log(0, "...und Tschüss!")
  except Exception as e:
    write_log(0, "__exit-Exception: " + e)

#########################################

############
### MAIN ###
############

if __name__ == '__main__':
  try:
    if os.path.exists(LOGFILE):
      os.remove(LOGFILE)

    android_platform = (os.environ.get("ANDROID_ROOT") != None)
    write_log(2, "android_platform {}".format(android_platform))

    droid = androidhelper.Android()
    droid.wakeLockAcquirePartial()
    #droid.wakeLockAcquireDim()

    # Start des Threads der den GPS Empfaenger ausliesst.
    write_log(1, "HALLO GPS?")
    t_gps = GpsdStreamReader()
    t_gps.start()
    write_log(1, "HALLO GPS!")

    # Start des Threads, der den Feinstaubsensor ueber den USB-Serial Konverter ausliesst.
    write_log(1, "HALLO SDS?")
    t_sds011 = SDS011StreamReader()
    t_sds011.start()
    write_log(1, "HALLO SDS!")

    ## Kurze Pause um zu warten bis die beiden Threads t_gps und
    ## t_sds01 starten konnten.
    #time.sleep(3)
    write_log(1, "SENSOR GESTARTET?")
    t_start_sensor = Thread(target=start_sensor)
    t_start_sensor.start()
    write_log(1, "SENSOR GESTARTET!")


    ### Starten des Web-Servers.
    debug(True)
    a = run(port=8080)
    write_log(0, "Class: " + str(type(a)))
  except Exception as e:
    write_log(0, "__exit-Exception: " + str(e))



