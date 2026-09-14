# SDS011-Android
This Repo contains a manual and python3 code to set up a SDS011 particulate sensor connected with the HC-06 bluetooth module under Android. The measurements are presented in a QPython 3L WebApp using the Python web framework bottle.

<p align="center">This project is heavily influenced by<br>https://github.com/optiprime/Feinstaubsensor</p>

However optiprimes code is not working under python3.x. The urge to get the setup running with QPython 3L led to this repository.

1. Install QPython 3L from Google Play https://play.google.com/store/apps/details?id=org.qpython.qpy3&gl=DE
2. Open In QPython 3L-App, choose console and execute
``import pip; pip.main(['install', 'bottle'])``
3. Download the repository https://github.com/demogorgi/SDS011-Android/archive/refs/heads/main.zip and unzip it
4. Copy the folder SDS011-Android-main (deepest level) to /storage/emulated/0/qpython/projects3 (Interner Speicher > qpython > projects3)
5. Assemble the dust sensor as shown in the image below and connect the USB plug with a power bank
   * Schematic:
     <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Wiring.jpg" width=30% alt=Wiring"></div>
   * My realisation:
     <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Sample_setup.jpg" width=30% alt=Wiring"></div>
7. In Qpython 3L choose Programs > projects > SDS011-Android-main > Run
8. Should look like this then: <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Screenshot_QPython%203L.jpg" width=20% alt="Screenshot WebApp"></div>
9. Three modes, mutually exclusive, all of them require a connected sensor:
    * **Messfahrt** -- GPS track: two kml-files plus a csv-file. No upload.
    * **Lokale Messung** -- measuring at one spot (for instance chalk dust in a
      climbing gym): csv only, no GPS needed, no upload. The place you type ends
      up in the file name, e.g. ``feinstaub_kletterhalle_20260914_22_47_27.csv``
    * **Stationär** -- the only mode that uploads to luftdaten.info. Switch it on
      only at the location agreed with luftdaten.
10. In the output directory you will find the files and a log-file
    * The csv file's format is ``timestamp;pm2.5;pm_10;lat;lon``, decimal comma,
      coordinates with six decimals
      (earlier revisions of this README named the two measurement columns in the
      wrong order -- the file has always started with pm2.5)
    * The kml-files contain a pm_10 and pm_2.5 "trajectory" that can be viewed in GoogleEarth (make sure to press the "Stop"-Button in the WebApp to get vaild kml files)
      <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Dust-trajectory.jpg" width=50% alt=Wiring"></div>
    * ``logfile.txt`` contains the log of the current run, ``logfile.1.txt``
      the one before it

## Entwicklung

Der Code laeuft unter **QPython 2 (Python 2.7)** und **QPython 3L (Python 3.x)**.
Damit das so bleibt, gelten ein paar Regeln:

* keine f-strings, kein Walrus, keine Annotationen, kein `pathlib`
* `"{0}".format(...)` statt `"{}".format(...)`
* Bytes immer als `bytearray` anfassen -- `bytearray[i]` liefert auf beiden
  Python-Generationen ein `int`, `str[i]` nicht
* Dateien mit `io.open(..., encoding='utf-8')` und `u"..."`-Literalen schreiben

### Ohne Handy entwickeln

Die Hardware liegt hinter zwei Schnittstellen (`transport.Transport`,
`gps.GpsSource`), zu denen es je eine Simulation gibt. Damit laeuft das
komplette Programm auf dem PC:

```
pip install -r requirements-dev.txt
SDS011_FAKE=1 python main.py        # Windows: set SDS011_FAKE=1
```

Danach `http://localhost:8080` im Browser oeffnen. Der simulierte Sensor
liefert plausible Messwerte, das simulierte GPS faehrt eine kleine Runde.
Ohne die Variable entscheidet die Plattform: auf dem Geraet
(`ANDROID_ROOT` gesetzt) echte Hardware, sonst Simulation.

### Echter Sensor am PC oder Laptop

Der SDS011 laesst sich auch vom Rechner aus auslesen -- ueber dasselbe
HC05/HC06-Modul, also per Bluetooth:

1. Das Modul einmal in den Bluetooth-Einstellungen des Betriebssystems
   koppeln. Windows verlangt fuer RFCOMM eine bestehende Kopplung.
2. `SDS011_FAKE=0 python main.py` starten.
3. Im Browser unter **Sensor** das Modul aus der Liste waehlen und auf
   **Verbinden** druecken.

Verbunden wird ueber die MAC-Adresse, genau wie auf dem Geraet -- keine
COM-Port-Nummer, kein `pyserial`, kein `PyBluez`. `socket.AF_BLUETOOTH`
steckt in der Standardbibliothek.

Falls die Verbindung nicht zustande kommt: HC05/HC06 bieten SPP
ueblicherweise auf RFCOMM-Kanal 1 an, und die Standardbibliothek kann
keine Dienstsuche. Notfalls `RFCOMM_CHANNEL` in `config.py` anpassen.

**GPS gibt es am Laptop nicht.** Fuer den stationaeren Modus ist das
egal, der braucht keine Position. Fuer die Kartierung braeuchte es eine
USB-GPS-Maus.

### Tests

`unittest` aus der Standardbibliothek -- laeuft unter Python 2.7 und 3.x,
ohne zusaetzliche Pakete:

```
python -m unittest discover -s tests -t .
```

Zwei Testgruppen ueberspringen sich selbst, wenn ihre Voraussetzungen
fehlen:

* **Python-2-Syntaxcheck** -- uebersetzt alle Module mit einem
  Python-2-Interpreter, sofern einer gefunden wird:

  ```
  PYTHON2=C:\Python27\python.exe python -m unittest tests.test_py2_compat
  ```

* **Browsertests** -- steuern die Oberflaeche mit einem echten Browser und
  pruefen, was statisch nicht sichtbar ist: ob ein gesperrter Button auch
  wirklich anders aussieht, ob ein Klick beim Server ankommt, ob die Seite
  fehlerfrei laedt.

  ```
  python -m unittest tests.test_frontend_browser
  ```

  Zwei Stolpersteine, falls das bei dir nicht laeuft: Playwrights
  **Sync-API stuerzt auf Python 3.14 ab** (sie haengt an greenlet), deshalb
  benutzt `tests/browsercheck.py` die Async-API. Und Playwrights eigenes
  Chromium ist oft nicht heruntergeladen, deshalb laeuft der Test ueber den
  System-Chrome (`channel='chrome'`). Entweder Chrome installiert haben
  oder einmal `python -m playwright install chromium` ausfuehren und den
  `channel`-Parameter entfernen.

Die Browsersteuerung liegt bewusst in `tests/browsercheck.py` und laeuft
als eigener Prozess -- deren `async`-Syntax wuerde die Testsuite unter
Python 2 schon beim Einsammeln zerlegen.

### Aufbau

| Modul | Inhalt | haengt ab von |
|---|---|---|
| `config.py` | Konstanten und Pfade | -- |
| `logging_util.py` | Logging | config |
| `state.py` | gemeinsamer Zustand (mit Lock) | -- |
| `protocol.py` | SDS011-Frames, reine Byte-Arithmetik | -- |
| `transport.py` | Schnittstelle, Android-Bluetooth, Simulation | config, protocol |
| `bluetooth_desktop.py` | Bluetooth am PC ueber RFCOMM | config, transport |
| `connection.py` | Wartezeiten zwischen Verbindungsversuchen | -- |
| `server.py` | stoppbarer, nebenlaeufiger Webserver | -- |
| `gps.py` | GPS-Quelle und -Thread | config, state |
| `sensor.py` | Sensor-Thread | protocol, state |
| `recorder.py` | Aufzeichnung und stationaerer Modus | config, kml, state |
| `kml.py` | KML-/CSV-Ausgabe | logging_util |
| `webapp.py` | Bottle-Routen | config, kml, state |
| `main.py` | verdrahtet alles | alle |
