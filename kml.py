from main import write_log
import os
import datetime

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

# Diese Funktion schreibt die KML Datei mit der zurückgelegten Wegstrecke.
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
