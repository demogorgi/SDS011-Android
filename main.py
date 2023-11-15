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
OUTDIR = '/storage/emulated/0/qpython/projects3/SDS011-Android-main/output'
LOGFILE = OUTDIR + '/logfile.txt'
TEMPLATEDIR = '/storage/emulated/0/qpython/projects3/SDS011-Android-main/views'
STATICDIR = '/storage/emulated/0/qpython/projects3/SDS011-Android-main/static'
KML_INT = 5
SSP_UUID = '00001101-0000-1000-8000-00805F9B34FB'
# Bluetooth MAC-Addresse des HC05/HC06-Moduls, welcher die Verbindung zum SDS011-Sensor herstellt.
SDS011_bluetooth_device_id = '00:14:03:05:59:17'

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

global session
session = None

global g_lat, g_lng, g_utc
g_lat = 0
g_lng = 0
g_utc = datetime.datetime.utcnow()

global run
run = False

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

# Hier wird die Farbe fuer die Linie festgelegt.
def color_selection(value):
  if 50 <= value:
    color = "#C80000FF"
  elif 48.52941176 <= value < 50.00000000:
    color = "#C8000FFF"
  elif 47.05882353 <= value < 48.52941176:
    color = "#C8001EFF"
  elif 45.58823529 <= value < 47.05882353:
    color = "#C8002DFF"
  elif 44.11764706 <= value < 45.58823529:
    color = "#C8003CFF"
  elif 42.64705882 <= value < 44.11764706:
    color = "#C8004BFF"
  elif 41.17647059 <= value < 42.64705882:
    color = "#C8005AFF"
  elif 39.70588235 <= value < 41.17647059:
    color = "#C80069FF"
  elif 38.23529412 <= value < 39.70588235:
    color = "#C80078FF"
  elif 36.76470588 <= value < 38.23529412:
    color = "#C80087FF"
  elif 35.29411765 <= value < 36.76470588:
    color = "#C80096FF"
  elif 33.82352941 <= value < 35.29411765:
    color = "#C800A5FF"
  elif 32.35294118 <= value < 33.82352941:
    color = "#C800B4FF"
  elif 30.88235294 <= value < 32.35294118:
    color = "#C800C3FF"
  elif 29.41176471 <= value < 30.88235294:
    color = "#C800D2FF"
  elif 27.94117647 <= value < 29.41176471:
    color = "#C800E1FF"
  elif 26.47058824 <= value < 27.94117647:
    color = "#C800F0FF"
  elif 25 <= value < 26.47058824:
    color = "#C800FFFF"
  elif 23.52941176 <= value < 25.00000000:
    color = "#C800FFF0"
  elif 22.05882353 <= value < 23.52941176:
    color = "#C800FFE1"
  elif 20.58823529 <= value < 22.05882353:
    color = "#C800FFD2"
  elif 19.11764706 <= value < 20.58823529:
    color = "#C800FFC3"
  elif 17.64705882 <= value < 19.11764706:
    color = "#C800FFB4"
  elif 16.17647059 <= value < 17.64705882:
    color = "#C800FFA5"
  elif 14.70588235 <= value < 16.17647059:
    color = "#C800FF96"
  elif 13.23529412 <= value < 14.70588235:
    color = "#C800FF87"
  elif 11.76470588 <= value < 13.23529412:
    color = "#C800FF78"
  elif 10.29411765 <= value < 11.76470588:
    color = "#C800FF69"
  elif 8.823529412 <= value < 10.29411765:
    color = "#C800FF5A"
  elif 7.352941176 <= value < 8.823529412:
    color = "#C800FF4B"
  elif 5.882352941 <= value < 7.352941176:
    color = "#C800FF3C"
  elif 4.411764706 <= value < 5.882352941:
    color = "#C800FF2D"
  elif 2.941176471 <= value < 4.411764706:
    color = "#C800FF1E"
  elif 1.470588235 <= value < 2.941176471:
    color = "#C800FF0F"
  elif 0 <= value < 1.470588235:
    color = "#C800FF00"

  return color

# und hier fuer die Darstellung im Frontend 
# Grenzwerte
# Zum Schutz der menschlichen Gesundheit gelten seit dem 1. Januar 2005 europaweit Grenzwerte fuer die Feinstaubfraktion PM10.
# Der Tagesgrenzwert betraegt 50 mikrogramm/m3 und darf nicht oefter als 35mal im Jahr ueberschritten werden. Der zulaessige Jahresmittelwert betraegt 40 mikrogramm/m3.
# Fuer die noch kleineren Partikel PM2,5 gilt seit 2008 europaweit ein Zielwert von 25 mikrogramm/m3 im Jahresmittel, der bereits seit dem 1. Januar 2010 eingehalten werden soll.
# Seit 1. Januar 2015 ist dieser Wert verbindlich einzuhalten.
def color_selection_rgb(value, pm):
  if pm == "pm_10":
    # red   
    if 50 <= value:
      color = "#F00014"
    # orange
    elif 40 <= value < 50:
      color = "#FF7814"
    # green
    elif 0 <= value < 40:
      color = "#2bef0d"               
  elif pm == "pm_25":
    # red   
    if 50 <= value:
      color = "#F00014"
    # orange
    elif 25 <= value <= 49:
      color = "#FF7814"
    # green
    elif 0 <= value < 25:
      color = "#2bef0d"               

  return color

# Diese Funktion schreibt die CSV Datei mit den Feinstaubwerten und
# den GPS Koordinaten.
def write_csv(pm_25, pm_10, value_lat, value_lon, value_time, value_fname):
  lat = value_lat
  lon = value_lon
  time = value_time
  fname = value_fname
  with open(fname,'a') as file:
    line = time + ";" + pm_25 + ";" + pm_10 + ";" + lat + ";" + lon
    line = line.replace(".", ",")
    file.write(line)
    file.write('\n')
    file.close()

# Diese Funktion schreibt die KML Datei mit der zurueck gelegten Wegstrecke.
def write_kml_line(value_pm, value_pm_old, value_lon_old, value_lat_old, value_lat, value_lon, value_time, value_fname, type, value_color):
  pm = value_pm
  pm_old = value_pm_old
  lat_old = value_lat_old
  lon_old = value_lon_old
  lat = value_lat
  lon = value_lon
  time = value_time
  fname = value_fname
  color = value_color 
  try:
    if os.path.exists(fname):
      with open(fname,'a+') as file:
        # Hier ist eine sehr gute Dokumentation zu finden ueber
        # den Aufbau von KML Dateien.
        # https://developers.google.com/kml/documentation/kml_tut
        file.write("   <Placemark>\n")
        file.write("   <name>"+ pm +"</name>\n")
        file.write("    <description>"+ pm +"</description>\n")
        file.write("    <Point>\n")
        file.write("      <coordinates>" + lon + "," + lat + "," + pm + "</coordinates>\n")
        file.write("    </Point>\n")
        file.write("       <LineString>\n")
        file.write("           <altitudeMode>relativeToGround</altitudeMode>\n")
        file.write("           <coordinates>" + lon + "," + lat + "," + pm + "\n           "+ lon_old+ ","+ lat_old+ "," + pm_old + "</coordinates>\n")
        file.write("       </LineString>\n")
        file.write("       <Style>\n")
        file.write("           <LineStyle>\n")
        file.write("               <color>" + color + "</color>\n")
        file.write("               <width>8</width>\n")
        file.write("           </LineStyle>\n")
        file.write("       </Style>\n")
        file.write("   </Placemark>\n") 
        file.close()
    else:
      with open(fname,'a+') as file:
        file.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        file.write("<kml xmlns='http://earth.google.com/kml/2.1'>\n")
        file.write("<Document>\n")
        file.write("   <name> Feinstaub_Linie_"+type+"_" + datetime.datetime.now().strftime ("%Y%m%d") + ".kml </name>\n")
        file.write('\n')
        file.close()    
  except Exception as e:
    write_log(0, e)

# Diese Funktion schliesst das KML File ab.
def close_kml(file_name):
  try:
    with open(file_name,'a+') as file:
      file.write("  </Document>\n")
      file.write("</kml>\n")  
      file.close()
  except Exception as e:
    write_log(0, e)

# Klasse um auf den GPSD Stream via Thread zuzugreifen.
class GpsdStreamReader(threading.Thread):
  def __init__(self):
    global session
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
    global session
    global g_lat, g_lng, g_utc
    while t_gps.running:
      # Lese den naechsten Datensatz von GPSD
      g_lat, g_lng = self.getGpsData()
      time.sleep(5)

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

# Klasse um auf den SDS001 Sensor via Thread zuzugreifen.
class SDS001StreamReader(threading.Thread):
  def __init__(self):
    global byte
    global lastbyte
    global ser
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
    global ser

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
        write_log(1, 'pm_25={}, pm_10={}'.format(pm_25, pm_10))
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

def start_sensor():
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

  while True:

    while run:
      if save_file == False:
        fname25_line = OUTDIR + '/feinstaub_25_line_' + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.kml'
        fname10_line = OUTDIR + '/feinstaub_10_line_' + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.kml'        
        fname_csv    = OUTDIR + '/feinstaub_'         + datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S") + '.csv'
      save_file = True

      # Hier wird der Intervall gesetzt wie oft ein Wert
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

        color_25 = color_selection(pm_25)
        color_10 = color_selection(pm_10)

        write_kml_line(str(pm_25), str(pm_old_25), str(lon_old), str(lat_old), str(g_lat), str(g_lng), str(g_utc), fname25_line, "25", color_25)
        write_kml_line(str(pm_10), str(pm_old_10), str(lon_old), str(lat_old), str(g_lat), str(g_lng), str(g_utc), fname10_line, "10", color_10)

        lat_old = g_lat
        lon_old = g_lng

        pm_old_25 = pm_25
        pm_old_10 = pm_10

      write_csv(str(pm_25), str(pm_10), str(g_lat), str(g_lng), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fname_csv)

      pm_10_sum += pm_10
      pm_25_sum += pm_25
      avg_count += 1

      status_text = "Mittelwerte: {:.1f}, {:.1f}".format(pm_10_sum / avg_count, pm_25_sum / avg_count)

    if run == False:
      if save_file == True:
        # Hier werden die KML Dateien geschlossen.
        close_kml(fname25_line)
        time.sleep(0.2) 
        close_kml(fname10_line)
        time.sleep(0.2)                 
        save_file = False

# Hier folgt der Abschnitt fuer den Web-Server
from bottle import get, run, template, static_file, debug, route

@route('/')
def index():
  return template(TEMPLATEDIR + '/index.html', static_url=static_file)

@route('/static/<filename:path>')
def serve_static(filename):
    return static_file(filename, root=STATICDIR)

## stationary mode
#@app.route('/staton/', methods=['GET'])
#def startstat():
#       global run
#       run = True
#       global status_text
#       status_text = "Halleluja aktiv."
#       ret_data = {"value": "Halleluja."}
#       return jsonify(ret_data)
#
#@app.route('/statoff/', methods=['GET'])
#def stoppstat():
#       global run
#       run = False
#       global status_text
#       status_text = "Halleluja inaktiv."      
#       ret_data = {"value": "Halleluja."}
#       return jsonify(ret_data)
## stationary mode

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
      "pm_10": "%6.1f" % pm_10, "pm_10_color": color_selection_rgb(pm_10, "pm_10"),
      "pm_25": "%6.1f" % pm_25, "pm_25_color": color_selection_rgb(pm_25, "pm_25"),
      "error_msg": error_msg}
  write_log(3, ret_data)
  return ret_data

@route('/__exit', method=['GET','HEAD'])
def __exit():
    global server
    server.stop()

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
    
    write_log(1, "HALLO ANDROID?")
    droid = androidhelper.Android()
    droid.wakeLockAcquirePartial()
    write_log(1, "HALLO ANDROID!")
    
    # Start des Threads der den GPS Empfaenger ausliesst.
    write_log(1, "HALLO GPS?")
    t_gps = GpsdStreamReader()
    t_gps.start()
    write_log(1, "HALLO GPS!")
    
    # Start des Threads, der den Feinstaubsensor ueber den USB-Serial Konverter ausliesst.
    write_log(1, "HALLO SDS?")
    t_sds011 = SDS001StreamReader()
    t_sds011.start()
    write_log(1, "HALLO SDS!")
    
    # Kurze Pause um zu warten bis die beiden Threads t_gps und 
    # t_sds01 starten konnten.
    time.sleep(3)
    write_log(1, "SENSOR GESTARTET?")
    t_start_sensor = Thread(target=start_sensor)
    t_start_sensor.start()
    write_log(1, "SENSOR GESTARTET!")
    
    
    ### Starten des Web-Servers.
    debug(True)
    run(port=8080)
  except Exception as e:
    write_log(0, e)
    
