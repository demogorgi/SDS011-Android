# SDS011-Android

Mobile Feinstaubmessung mit dem Sensor **SDS011**, angebunden über ein
Bluetooth-Modul **HC-05/HC-06**. Das Programm läuft unter **QPython 2**
oder **QPython 3L** auf dem Handy und zeigt Messwerte, GPS-Position und
Verlauf in einer Weboberfläche unter `http://localhost:8080`. Es zeichnet
Messfahrten als KML/CSV auf, misst an festen Orten oder lädt Werte zu
luftdaten.info (sensor.community) hoch. Am PC läuft es mit echtem Sensor
per Bluetooth oder mit simulierter Hardware.

<p align="center">Angelehnt an<br>https://github.com/optiprime/Feinstaubsensor</p>

<div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Screenshot_QPython%203L.jpg" width=20% alt="Screenshot der Weboberfläche"></div>

## Hardware

SDS011 und HC-06 werden wie unten verdrahtet und über USB von einer
Powerbank versorgt.

* Schaltplan:
  <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Wiring.jpg" width=30% alt="Verdrahtung"></div>
* Beispielaufbau:
  <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Sample_setup.jpg" width=30% alt="Beispielaufbau"></div>

Das Modul einmal in den Bluetooth-Einstellungen von Android koppeln (PIN
meist `1234`).

## Installation auf dem Handy

1. **QPython 2** oder **QPython 3L** installieren.
2. Den Projektordner so kopieren, dass `main.py` hier liegt:
   * QPython 2: `Interner Speicher/qpython/projects/<Name>/main.py`
   * QPython 3L: `Interner Speicher/qpython/projects3/<Name>/main.py`

   Quelle ist entweder das Repository
   ([ZIP](https://github.com/demogorgi/SDS011-Android/archive/refs/heads/main.zip),
   darin der Ordner `SDS011-Android-main`) oder das Paket
   `SDS011-Android-qpython2.zip`, das zusätzlich `bottle.py` enthält
   (liegt nicht im Repository).
3. **bottle** bereitstellen:
   * Aus `SDS011-Android-qpython2.zip` installiert: nichts zu tun.
   * Sonst in der QPython-Konsole:
     `import pip; pip.main(['install', 'bottle'])`. Alternativ `bottle.py`
     (eine einzelne Datei) neben `main.py` legen.

   Weitere Pakete braucht die App nicht, auch nicht für den Upload.
4. **Berechtigungen** für QPython in den Android-Einstellungen:
   * **Bluetooth** bzw. **Geräte in der Nähe**: für Geräteliste und
     Verbindung zum Sensor.
   * **Standort: „Immer“**: für die Messfahrt, damit das GPS auch bei
     ausgeschaltetem Bildschirm liefert.
   * **Speicher/Dateien**: für `Download/Feinstaub`. Ohne diese
     Berechtigung landen die Dateien in `output/` neben `main.py`.
   * **Akku-Optimierung aus**: sonst bremst Android die Messung bei
     ausgeschaltetem Bildschirm aus. Die App hält zusätzlich einen
     Wake-Lock.
5. Sensor einschalten, dann in QPython *Programs → Projects → <Name> →
   Run*. Die Oberfläche öffnet sich unter `http://localhost:8080`.

**Messung bei ausgeschaltetem Bildschirm:** Bewährt hat sich, im
QPython-Terminal, in dem die App läuft, über das Menü (drei Punkte)
*Enable wakelock* einzuschalten und das Terminal danach in den
Hintergrund (*Background*) zu schicken. So bleibt die App aktiv, und
Android trennt die Bluetooth-Verbindung nicht. *Enable wifi lock* hält
das WLAN wach; das braucht man höchstens im stationären Modus, wenn der
Upload über WLAN läuft.

## Bedienung

**Sensor:** Das Modul aus der Liste der gekoppelten Geräte wählen und
*Verbinden* drücken. Vorgewählt ist `SDS011_BLUETOOTH_DEVICE_ID` aus
`config.py`, sofern gekoppelt. Die Anzeige darunter zeigt den Zustand
(*getrennt*, *verbinde*, *verbunden*, *wartet auf nächsten Versuch*).
Reißt die Verbindung ab, verbindet die App selbst neu, mit wachsenden
Abständen. *Trennen* beendet das sofort, auch mitten in einer Wartezeit.

**Messwerte:** PM10 und PM2.5 in µg/m³ mit Ampelfarbe: PM10 orange ab 40,
PM2.5 orange ab 25, beide rot ab 50. Darunter ein Verlaufsdiagramm (die
letzten 300 Abfragen). Wie oft die Seite abfragt, ist unter *Aktualisierung
der Anzeige* einstellbar (Standard 10 s). Das ändert nur die Anzeige, nicht
den Aufzeichnungstakt.

**GPS:** Breite und Länge mit Alter der Position:
* *aktuell (vor 3 s)*: höchstens `GPS_MAX_AGE` Sekunden alt, wird
  aufgezeichnet.
* *kein Signal seit 2 min*: es wird die letzte bekannte Position
  angezeigt, aber nicht aufgezeichnet.
* *noch kein Signal* bzw. *auf diesem Gerät nicht vorhanden* (PC).

Bleibt das GPS länger stumm, meldet die App es bei Android neu an (siehe
`GPS_RESTART_AFTER`).

### Die drei Modi

Alle drei brauchen einen verbundenen Sensor und schließen sich gegenseitig
aus: Ein Modus startet erst, wenn der laufende beendet ist. Sonst lautet
die Antwort z. B. „Messfahrt nicht möglich: erst Stationärer Modus
beenden.“

| Modus | Schreibt | GPS | Upload |
|---|---|---|---|
| **Messfahrt** | zwei KML-Spuren (PM2.5, PM10) und eine CSV, alle `KML_INT` s ein Punkt | ja, für die Spur | nein |
| **Lokale Messung** | nur CSV, Ortsname im Dateinamen | nicht nötig | nein |
| **Stationär** | keine Datei | nein | alle `STAT_INT` s zu luftdaten.info |

Bei Messfahrt und lokaler Messung zeigt der Status die Mittelwerte seit
Start (PM10, PM2.5).

* **Messfahrt:** Ohne aktuelle Position bleiben Breite und Länge in der CSV
  leer und die KML-Spur setzt aus. Danach beginnt sie neu, statt eine gerade
  Linie über die Lücke zu ziehen.
* **Lokale Messung:** z. B. Kreidestaub in der Kletterhalle. Der Ort
  aus dem Eingabefeld landet im Dateinamen, etwa
  `feinstaub_kletterhalle_duisburg_20261008_17_08_24.csv`. Ohne Ort heißt
  die Datei `feinstaub_lokal_<Zeit>.csv`.
* **Stationär:** Der einzige Modus, der Daten aus der Hand gibt. Er sendet
  öffentlich unter der Sensor-ID `XSENSOR`, also nur am mit luftdaten
  vereinbarten Standort einschalten. Hochgeladen wird per HTTPS. Fehlt
  QPython das `ssl`-Modul oder scheitert HTTPS dauerhaft an Zertifikaten
  bzw. Protokoll, geht der Upload über HTTP. Ein Timeout zählt nicht als
  dauerhaft. Auch nach Aus- und Wiedereinschalten wird nie öfter als alle
  `STAT_INT` Sekunden gesendet.

**Kein aktueller Messwert:** Ist der letzte Wert vom Sensor älter als
`MAX_MEASUREMENT_AGE` (Verbindung weg), wird nichts aufgezeichnet und nichts
hochgeladen. Rot erscheint dann „Kein aktueller Messwert vom Sensor -
nichts aufgezeichnet“ bzw. „... - nichts hochgeladen“. Sobald wieder Werte
kommen, verschwindet der Hinweis und die Messung läuft weiter.

**Speicherort:** Unter Android `Download/Feinstaub` (mit jedem Dateimanager
erreichbar). Am PC, oder wenn QPython dort nicht schreiben darf, `output/`
neben `main.py`. Das gültige Verzeichnis steht in der Oberfläche unter *Weitere
Informationen*.

## Dateiformate

**CSV:** eine Kopfzeile, dann eine Zeile pro Messpunkt, getrennt durch
`;`, mit Dezimalkomma (für ein deutsches Excel):

```
Zeit;PM2.5;PM10;Breite;Laenge
2026-10-10 00:42:55;9,8;20,2;51,440100;6,788400
2026-10-10 00:43:00;10,3;23,0;;
```

Koordinaten mit sechs Nachkommastellen. Ohne aktuelle Position (älter als
`GPS_MAX_AGE`, oder kein GPS wie am PC) bleiben Breite und Länge leer.

**KML:** `feinstaub_25_line_<Zeit>.kml` und `feinstaub_10_line_<Zeit>.kml`,
z. B. in Google Earth anzusehen. Jeder Punkt liegt so hoch wie sein
Messwert, die Linie ist von grün (0) über gelb (25) nach rot (ab 50)
gefärbt. Abgeschlossen werden die Dateien bei *Stop*, beim Moduswechsel
und beim regulären Beenden der App. Wird QPython hart beendet (Akku leer,
von Android geschlossen), fehlt der Abschluss zunächst; die App trägt ihn
beim nächsten Start nach.

<div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Dust-trajectory.jpg" width=50% alt="Feinstaubspur in Google Earth"></div>

**Log:** `logfile.txt` enthält den aktuellen Lauf, `logfile.1.txt` den
vorigen. Wie ausführlich, regelt `LOG_LEVEL`.

## Am PC

Python 2.7 oder 3.x mit bottle. `pip install -r requirements-dev.txt`
installiert bottle und den Linter ruff (ruff nur unter Python 3).

**Mit echtem Sensor:** Das HC-05/HC-06 einmal in den Bluetooth-Einstellungen
des Betriebssystems koppeln (Windows verlangt das für RFCOMM). Dann
`python main.py` starten, `http://localhost:8080` öffnen, unter *Sensor*
das Modul wählen und *Verbinden* drücken. Die Geräteliste kommt unter
Windows aus PowerShell (`Get-PnpDevice`), unter Linux aus `bluetoothctl`.
Verbunden wird per MAC-Adresse über `socket.AF_BLUETOOTH` aus der
Standardbibliothek, ohne COM-Port, pyserial oder PyBluez. Unter Windows
braucht das Python 3.9 oder neuer. Fehlt die Unterstützung, meldet die App
„Dieses Python kennt keine Bluetooth-Sockets.“ Kommt keine Verbindung zustande,
`RFCOMM_CHANNEL` in `config.py` prüfen.

**Simulation:** `SDS011_FAKE=1` ersetzt Sensor und GPS durch Simulationen
(Windows-cmd: `set SDS011_FAKE=1`). Der simulierte Sensor liefert
verrauschte, plausible Werte mit gelegentlichen Spitzen, das simulierte GPS
fährt eine kleine Runde.

```
SDS011_FAKE=1 python main.py
```

**Mit echtem Sensor gibt es am PC kein GPS.** Lokale Messung und
stationärer Modus brauchen keins. Eine Messfahrt läuft, schreibt aber nur
CSV mit leeren Koordinaten und keine KML-Spur.

**Umgebungsvariablen:**

| Variable | Wirkung |
|---|---|
| `SDS011_FAKE=1` | simulierter Sensor und simuliertes GPS |
| `SDS011_HOST` | Adresse des Webservers, Standard `127.0.0.1` |
| `SDS011_PORT` | Port des Webservers, Standard `8080` |

Der Webserver ist absichtlich nur vom eigenen Gerät erreichbar. Mit
`SDS011_HOST=0.0.0.0` kann jeder im selben WLAN die Position lesen, die App
beenden und den öffentlichen Upload starten. Die Oberfläche läuft nur über
`http://`, nicht `https://`.

## Konfiguration

Einstellbar in `config.py` zwischen *START* und *ENDE DER
KONFIGURATIONSOPTIONEN*:

| Option | Standard | Bedeutung |
|---|---|---|
| `LOG_LEVEL` | `1` | 0 nur Fehler, 1 Betrieb, 2 Details, 3 Protokoll-Debug |
| `KML_INT` | `5` | Sekunden zwischen zwei Messpunkten in KML/CSV |
| `GPS_INT` | `5` | Sekunden zwischen zwei GPS-Abfragen |
| `GPS_RESTART_AFTER` | `60` | GPS so viele Sekunden stumm: bei Android neu anmelden (nur auf dem Handy) |
| `GPS_RESTART_MAX` | `600` | Obergrenze dieser Wartezeit, sie verdoppelt sich bis dahin |
| `GPS_MAX_AGE` | `15` | Position älter als so viele Sekunden: nicht aufzeichnen |
| `STAT_INT` | `240` | Sekunden zwischen zwei Uploads im stationären Modus |
| `MAX_MEASUREMENT_AGE` | `10` | Messwert älter als so viele Sekunden: nicht aufzeichnen, nicht hochladen |
| `SSP_UUID` | SPP-Standard-UUID | Bluetooth-Dienst des HC-Moduls (Android) |
| `RFCOMM_CHANNEL` | `1` | RFCOMM-Kanal am PC |
| `SDS011_BLUETOOTH_DEVICE_ID` | `00:14:03:05:59:17` | MAC des eigenen Moduls, vorgewählt bzw. Rückfall, wenn keine Geräteliste kommt |
| `XSENSOR` | `raspi-…` | Sensor-ID bei luftdaten.info |
| `LUFTDATEN_URL` | `https://api.luftdaten.info/v1/push-sensor-data/` | Upload-Adresse |
| `HTTP_HOST` | `127.0.0.1` | Adresse des Webservers (überschreibbar per `SDS011_HOST`) |
| `HTTP_PORT` | `8080` | Port des Webservers (überschreibbar per `SDS011_PORT`) |
| `ANDROID_OUTDIR` | `/storage/emulated/0/Download/Feinstaub` | Ausgabeverzeichnis unter Android, `None` für `output/` |

## Entwicklung

### Python 2.7 und 3

Der Code muss unter **QPython 2 (Python 2.7)** und **QPython 3L** laufen.
Deshalb:

* keine f-Strings, kein Walrus, keine Annotationen, kein `pathlib`
* `"{0}".format(...)` statt `"{}".format(...)`
* jede Datei mit `# -*- coding: utf-8 -*-` und
  `from __future__ import absolute_import`
* Bytes als `bytearray` behandeln: nur `bytearray[i]` liefert in beiden
  Versionen ein `int`
* Text mit `u"..."` schreiben, Dateien mit
  `io.open(..., encoding='utf-8')`; Fremdtext über
  `logging_util.to_text()` umwandeln
* Funktionen, die es erst in Python 3 gibt (`time.monotonic`,
  `os.replace`, `exist_ok=`), nur mit Rückfall benutzen
* Kommentare und Docstrings mit ae/oe/ue/ss; echte Umlaute nur in
  Texten, die der Benutzer sieht

### Tests

`unittest` aus der Standardbibliothek, läuft unter Python 2.7 und 3.x:

```
python -m unittest discover -s tests -t .
```

Zwei Gruppen überspringen sich selbst, wenn ihre Voraussetzungen fehlen:

* **Python-2-Syntaxcheck** (`tests.test_py2_compat`) übersetzt alle Module
  mit einem Python 2 aus dem PATH oder aus `PYTHON2`:
  `PYTHON2=C:\Python27\python.exe python -m unittest tests.test_py2_compat`
* **Browsertests** (`tests.test_frontend_browser`) bedienen die Oberfläche
  in einem echten Chrome. Sie brauchen Playwright und einen installierten
  Chrome (`channel='chrome'`). Die Steuerung liegt in
  `tests/browsercheck.py` und läuft als eigener Prozess, weil ihre
  `async`-Syntax die Suite unter Python 2 schon beim Einsammeln
  abbrechen würde. Sie nutzt die Async-API, weil Playwrights Sync-API
  unter Python 3.14 abstürzt.

### Linter

```
ruff check .
```

Die Regeln stehen in `ruff.toml`. Bewusst ausgelassen sind die UP-Regeln
(sie schlagen f-Strings vor und entfernen `u`-Präfixe und coding-Zeilen)
und `B904` (`raise ... from` gibt es in Python 2 nicht). `ruff format` ist
abgeschaltet, weil es die `u`-Präfixe entfernt.

### Aufbau

Auf dem Handy wie am PC laufen drei Threads (Sensor, GPS, Aufzeichnung)
neben dem Webserver. Sie tauschen sich nur über den gemeinsamen `AppState`
aus. Die Hardware steckt hinter `transport.Transport` und
`gps.GpsSource`, mit je einer Android-, PC- und Simulationsvariante.

| Modul | Aufgabe | importiert aus dem Projekt |
|---|---|---|
| `config.py` | Einstellungen, Pfade, Umgebungsvariablen | – |
| `logging_util.py` | Logdatei, Log-Rotation, `to_text()` | config |
| `state.py` | gemeinsamer, thread-sicherer Zustand | – |
| `connection.py` | wachsende Wartezeiten (Backoff) | – |
| `protocol.py` | SDS011-Datenpakete zerlegen und bauen | – |
| `transport.py` | Transport-Schnittstelle, Bluetooth unter Android, Simulation | config, protocol, logging_util; bluetooth_desktop erst bei Bedarf |
| `bluetooth_desktop.py` | Bluetooth am PC über RFCOMM, Geräteliste | config, logging_util, transport |
| `sensor.py` | Sensor-Thread: verbinden, lesen, neu verbinden | state, connection, logging_util, protocol, transport |
| `gps.py` | GPS-Quellen und GPS-Thread | config, connection, logging_util, state |
| `recorder.py` | Aufzeichnungs-Thread: CSV/KML, Upload | config, kml, logging_util |
| `kml.py` | KML- und CSV-Zeilen schreiben, Ampelfarben | logging_util |
| `webapp.py` | Routen der Oberfläche (bottle) | config, kml, logging_util |
| `server.py` | mehrfädiger, stoppbarer Webserver | logging_util |
| `main.py` | startet und verdrahtet alles, beendet sauber | config, gps, sensor, transport, webapp, logging_util, recorder, server, state |
| `views/index.html` | Oberfläche (jQuery, Chart.js aus `static/`) | – |
