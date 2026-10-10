# -*- coding: utf-8 -*-
"""Schreibt die Ausgabedateien einer Messung: KML-Spur und CSV-Tabelle.

Wird vom Recorder benutzt; webapp holt sich nur die Ampelfarben fuer die
Anzeige. Importiert nichts aus main.py: main.py laeuft als __main__, ein
'import main' wuerde es ein zweites Mal laden, mit eigenem Satz Globals.
"""

from __future__ import absolute_import

import datetime
import io
import os

from logging_util import to_text, write_log

# KML-Linienfarbe zum Messwert: Verlauf in 35 Stufen von Gruen (0) ueber
# Gelb (25) nach Rot (ab 50). KML erwartet aabbggrr, nicht rrggbb.
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
  else:
    # Negative oder ungueltige Werte: neutral statt UnboundLocalError.
    color = "#C8FFFFFF"

  return color

# Ampelfarbe (rrggbb) fuer die Weboberflaeche, pm ist 'pm_10' oder 'pm_25'.
# Orange ab dem EU-Jahresmittelgrenzwert (PM10: 40, PM2,5: 25 ug/m3),
# Rot ab 50 ug/m3, dem EU-Tagesgrenzwert fuer PM10.
# Unbekanntes pm oder negativer Wert ergibt Weiss.
def color_selection_rgb(value, pm):
  if pm == "pm_10":
    if 50 <= value:
      color = "#F00014"
    elif 40 <= value < 50:
      color = "#FF7814"
    elif 0 <= value < 40:
      color = "#2bef0d"
    else:
      color = "#FFFFFF"
  elif pm == "pm_25":
    if 50 <= value:
      color = "#F00014"
    elif 25 <= value < 50:
      color = "#FF7814"
    elif 0 <= value < 25:
      color = "#2bef0d"
    else:
      color = "#FFFFFF"
  else:
    color = "#FFFFFF"

  return color

# Erste Zeile jeder CSV-Datei. Ohne Umlaut: Excel liest UTF-8 ohne BOM
# als ANSI.
CSV_HEADER = u'Zeit;PM2.5;PM10;Breite;Laenge'


# Haengt eine Zeile "Zeit;PM2,5;PM10;Breite;Laenge" an die CSV-Datei, bei
# einer neuen Datei zuerst die Kopfzeile. Punkte werden zu Kommas, damit
# ein deutsches Excel die Zahlen erkennt. Fehler gehen an den Aufrufer.
def write_csv(pm_25, pm_10, value_lat, value_lon, value_time, value_fname):
  lat = value_lat
  lon = value_lon
  time = value_time
  fname = value_fname
  new_file = not os.path.exists(fname) or os.path.getsize(fname) == 0
  with io.open(fname, 'a', encoding='utf-8', newline='') as file:
    if new_file:
      file.write(CSV_HEADER + u'\n')
    line = u"" + time + ";" + pm_25 + ";" + pm_10 + ";" + lat + ";" + lon
    line = line.replace(".", ",")
    file.write(line)
    file.write(u'\n')

# Legt den Kopf einer neuen KML-Datei an; type ('25' oder '10') geht in
# den Namen des Dokuments ein. Aufbau von KML:
# https://developers.google.com/kml/documentation/kml_tut
def _write_kml_header(fname, type):
  with io.open(fname, 'a', encoding='utf-8', newline='') as file:
    file.write(u"<?xml version='1.0' encoding='UTF-8'?>\n")
    file.write(u"<kml xmlns='http://earth.google.com/kml/2.1'>\n")
    file.write(u"<Document>\n")
    file.write(u"   <name> Feinstaub_Linie_" + type + "_"
               + datetime.datetime.now().strftime("%Y%m%d") + ".kml </name>\n")
    file.write(u"\n")

# Haengt ein Placemark an die KML-Spur: Punkt an der aktuellen Position
# und ein Liniensegment von der vorigen Position hierher. Das Segment
# liegt so viele Meter ueber Grund wie der Messwert, die Spur steigt in
# Google Earth also mit der Belastung. Alle Werte kommen als Text.
# Achtung Reihenfolge: alt kommt als (lon, lat), neu als (lat, lon).
# value_time wird nicht verwendet.
# Existiert die Datei noch nicht, wird zuerst der Kopf geschrieben. Ist
# sie schon abgeschlossen (etwa von repair_unclosed_kml einer zweiten
# App-Instanz), wird der Abschluss vorher entfernt -- sonst laegen die
# neuen Placemarks hinter </kml>.
# Liefert True oder bei einem Schreibfehler False (mit Logeintrag).
def write_kml_line(value_pm, value_pm_old, value_lon_old, value_lat_old, value_lat, value_lon, value_time, value_fname, type, value_color):
  pm = value_pm
  pm_old = value_pm_old
  lat_old = value_lat_old
  lon_old = value_lon_old
  lat = value_lat
  lon = value_lon
  fname = value_fname
  color = value_color
  try:
    if not os.path.exists(fname):
      _write_kml_header(fname, type)
    else:
      _strip_trailer(fname)
    with io.open(fname, 'a', encoding='utf-8', newline='') as file:
      file.write(u"   <Placemark>\n")
      file.write(u"   <name>" + pm + "</name>\n")
      file.write(u"    <description>" + pm + "</description>\n")
      file.write(u"    <Point>\n")
      file.write(u"      <coordinates>" + lon + "," + lat + "," + pm + "</coordinates>\n")
      file.write(u"    </Point>\n")
      file.write(u"       <LineString>\n")
      file.write(u"           <altitudeMode>relativeToGround</altitudeMode>\n")
      file.write(u"           <coordinates>" + lon + "," + lat + "," + pm + "\n           " + lon_old + "," + lat_old + "," + pm_old + "</coordinates>\n")
      file.write(u"       </LineString>\n")
      file.write(u"       <Style>\n")
      file.write(u"           <LineStyle>\n")
      file.write(u"               <color>" + color + "</color>\n")
      file.write(u"               <width>8</width>\n")
      file.write(u"           </LineStyle>\n")
      file.write(u"       </Style>\n")
      file.write(u"   </Placemark>\n")
    return True
  except Exception as e:
    write_log(0, u'KML-Fehler: {0}'.format(to_text(e)))
    return False

# Schliesst die KML-Datei ab. Liefert True, sonst False (mit Logeintrag),
# auch wenn die Datei fehlt. Ist sie schon abgeschlossen, bleibt sie so.
def close_kml(file_name):
  # Ohne geschriebenen Messwert gibt es keine Datei. Dann nichts anlegen:
  # nur die schliessenden Tags waeren kein gueltiges XML.
  if not os.path.exists(file_name):
    write_log(1, u'close_kml: {0} existiert nicht, nichts abzuschliessen'.format(to_text(file_name)))
    return False
  try:
    if _is_closed(file_name):
      return True
    with io.open(file_name, 'ab') as file:
      file.write(_KML_TRAILER)
    return True
  except Exception as e:
    write_log(0, u'KML-Fehler: {0}'.format(to_text(e)))
    return False

_KML_TRAILER = b"  </Document>\n</kml>\n"
_PLACEMARK_END = b"</Placemark>\n"
_HEADER_END = b"</name>\n"
# Ein Placemark ist gut 600 Byte gross; im letzten Stueck der Datei
# steckt also sicher das Ende des letzten vollstaendigen.
_TAIL = 8192


def _is_closed(path):
  with io.open(path, 'rb') as file:
    file.seek(0, 2)
    file.seek(max(0, file.tell() - 64))
    return file.read().rstrip().endswith(b'</kml>')


def _strip_trailer(path):
  """Entfernt einen Abschluss am Dateiende, damit weiter angehaengt werden
  kann. Ohne Abschluss passiert nichts."""
  with io.open(path, 'rb') as file:
    file.seek(0, 2)
    size = file.tell()
    file.seek(max(0, size - len(_KML_TRAILER)))
    if file.read() != _KML_TRAILER:
      return
  with io.open(path, 'r+b') as file:
    file.seek(size - len(_KML_TRAILER))
    file.truncate()


def _find_cut(file, size):
  """Byte-Position hinter dem letzten vollstaendigen Placemark, ersatzweise
  hinter dem Kopf; None, wenn auch der Kopf unvollstaendig ist."""
  start = max(0, size - _TAIL)
  file.seek(start)
  tail = file.read()
  cut = tail.rfind(_PLACEMARK_END)
  if cut >= 0:
    return start + cut + len(_PLACEMARK_END)
  if start > 0:
    # Grosse Datei ohne Placemark-Ende im letzten Stueck: nicht raten.
    return None
  cut = tail.find(_HEADER_END)
  return cut + len(_HEADER_END) if cut >= 0 else None


# Schliesst KML-Dateien ab, die ein harter Abbruch (Android beendet
# QPython, Akku leer) offen gelassen hat -- ohne Abschluss lehnt Google
# Earth sie ab. Ein halb geschriebenes letztes Placemark wird
# abgeschnitten; gelesen wird nur das Dateiende, gekuerzt wird an Ort und
# Stelle. Zeichnet eine zweite App-Instanz noch in eine solche Datei auf,
# entfernt write_kml_line den Abschluss beim naechsten Punkt wieder.
# Unreparierbare heissen danach *.kml.defekt, damit sie nicht bei jedem
# Start wieder auftauchen. Liefert die reparierten Namen.
def repair_unclosed_kml(directory):
  repaired = []
  try:
    names = sorted(os.listdir(directory))
  except OSError:
    return repaired
  for name in names:
    if not name.endswith('.kml'):
      continue
    path = os.path.join(directory, name)
    try:
      # Erst nur lesen: abgeschlossene Dateien duerfen schreibgeschuetzt sein.
      if _is_closed(path):
        continue
      with io.open(path, 'rb') as file:
        file.seek(0, 2)
        cut = _find_cut(file, file.tell())
      if cut is not None:
        with io.open(path, 'r+b') as file:
          file.seek(cut)
          file.truncate()
          file.write(_KML_TRAILER)
        repaired.append(name)
        continue
      os.rename(path, path + '.defekt')
      write_log(0, u'KML nicht reparierbar, umbenannt: {0}.defekt'.format(to_text(name)))
    except (IOError, OSError) as e:
      write_log(0, u'KML-Reparatur fehlgeschlagen: {0}'.format(to_text(e)))
  return repaired
