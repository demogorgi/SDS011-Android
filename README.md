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

**Messung bei ausgeschaltetem Bildschirm:** Die App hält selbst einen
Wake-Lock, Android kann QPython aber trotzdem in den Ruhezustand schicken.
Erfahrungsgemäß hilft es, im QPython-Terminal, in dem die App läuft, über
das Menü (drei Punkte) *Enable wakelock* einzuschalten und das Terminal
danach in den Hintergrund (*Background*) zu schicken. Dann bleibt QPython
aktiv, und die Bluetooth-Verbindung hält. *Enable wifi lock* hält das WLAN
wach; das braucht man höchstens im stationären Modus, wenn der Upload über
WLAN läuft.

## Bedienung

**Sensor:** Das Modul aus der Liste der gekoppelten Geräte wählen und
*Verbinden* drücken. Vorgewählt ist `SDS011_BLUETOOTH_DEVICE_ID` aus
`config.py`, sofern gekoppelt. Oben rechts steht der Zustand (*getrennt*,
*verbinde*, *verbunden*, *wartet* auf den nächsten Versuch).
Reißt die Verbindung ab, verbindet die App selbst neu, mit wachsenden
Abständen. Als abgerissen gilt sie auch, wenn `SENSOR_SILENCE_TIMEOUT`
Sekunden lang keine Daten kommen (Sensor aus, außer Reichweite); bei
absichtlich gesetztem SDS011-5-Minuten-Zyklus verlängert die App diese
Schwelle automatisch. *Trennen* setzt den SDS011 wieder auf Dauerbetrieb
und beendet das Neuverbinden, auch mitten in einer Wartezeit; ein gerade
laufender Verbindungsversuch wird noch zu Ende gebracht.

**Simulierter Sensor:** Ganz unten in der Geräteliste steht immer
*Simulierter Sensor*, auf dem Handy wie am PC. Er liefert verrauschte,
plausible Werte mit gelegentlichen Spitzen: zum Ausprobieren und Vorführen
ohne SDS011, ohne Neustart. Erfundene Werte sind überall kenntlich und
landen nie in fremden Daten:

* Oben rechts steht *simuliert* (hohler Punkt), am Sensor das Abzeichen
  *Simulation*.
* Dateien heißen `feinstaub_sim_…`, damit man sie nicht mit echten
  Messungen verwechselt.
* Der stationäre Modus ist gesperrt: simulierte Werte werden nie zu
  sensor.community hochgeladen. Auch der Recorder lädt dann nichts hoch.
* Während einer Messung lässt sich nicht zwischen echtem und simuliertem
  Sensor wechseln; eine Datei enthält nur das eine oder das andere.
* GPS: auf dem Handy das echte, eine Messfahrt zeigt also die echte
  Strecke. Am PC, wo es kein GPS gibt, fährt mit dem simulierten Sensor
  ein simuliertes GPS eine kleine Runde, damit eine KML-Spur entsteht.

**Messwerte:** PM2.5 und PM10 in µg/m³ mit Einstufung *gut*, *erhöht* oder
*hoch* (dieselben Stufen wie die Farben der KML: PM2.5 erhöht ab 25, PM10
ab 40, beide hoch ab 50), dazu das Alter des Werts. Ist er älter als
`MAX_MEASUREMENT_AGE`, steht dort *veraltet*. Die Seite fragt alle 2 s
den Zustand ab. *Was bedeuten die Stufen?* klappt darunter die Schwellen
auf, mit Herkunft (EU-Grenzwerte) und Link zum Umweltbundesamt.

**Darstellung:** Hell oder dunkel folgt der Systemeinstellung. Der runde
Schalter oben rechts wechselt zwischen *automatisch*, *hell* und *dunkel*;
die Wahl merkt sich der Browser, pro Gerät. Nützlich auf Android 7 und
älter, die keine systemweite Dunkel-Einstellung kennen, und draußen in der
Sonne.

**Links:** Das WebView von QPython öffnet keine neuen Fenster, ein Tippen
auf einen Link liefe ins Leere. Unter Android öffnet die App die Links
deshalb selbst im Browser des Systems (Route `/open/`, über
`droid.view()`); erlaubt sind nur die Adressen aus `LINKS` in `config.py`.
Der Link *Sensor auf der Karte ansehen* bleibt auf den festen, bei
sensor.community registrierten Sensorstandort zentriert. *Karte an meiner
Position ansehen* erscheint bei Messfahrt und lokaler Messung; mit
aktuellem GPS-Fix zentriert er auf die Handy-Position, sonst auf den
festen Sensorstandort. Am PC sind es gewöhnliche Links.

**Messintervall:** In der Karte *Messung* wählbar, von 1 s bis 15 min
(`RECORD_INT_CHOICES`). Bei 1 s bis 1 min bleibt der SDS011 im
Dauerbetrieb und liefert etwa einen Wert pro Sekunde. Bei 5 und 15 min
setzt die App den SDS011 auf seine 5-Minuten-Working-Period: etwa 30 s
messen, dann schlafen. Ein 15-min-Punkt mittelt dadurch typischerweise
drei kurze Messphasen. Beim Trennen und Beenden setzt die App den Sensor
wieder auf Dauerbetrieb; wirklich aus ist er erst über den
Hardwareschalter. Die App mittelt alle Werte eines Intervalls und
speichert den Mittelwert als einen Punkt: eine Zeile in der CSV, bei der
Messfahrt auch ein KML-Punkt. Eine Änderung gilt sofort, auch mitten in
einer Messung, und bleibt nach einem Neustart erhalten
(`einstellungen.json` im Speicherort).

**Verlauf:** Das Diagramm zeichnet der Server als SVG aus denselben
Mittelwerten, die in die Datei gehen. Er sammelt sie, sobald ein Sensor
verbunden ist, auch ohne laufende Messung (dann nur zur Ansicht). Grau
hinterlegt ist, was in einer Datei steht (*gespeichert*), gestrichelt die
Grenzen 25, 40 und 50. Zeitraum: 10 min, 1 h, 6 h oder *Alles* (die letzten
`HISTORY_SIZE` Punkte). Der Verlauf liegt nur im Speicher und beginnt nach
einem Neustart der App von vorn.

**Bildschirm aus:** Die Messung läuft in der App weiter, nur die Seite
fragt nichts ab. Nach dem Einschalten ist das Diagramm sofort vollständig,
auch für die Zeit, in der der Bildschirm aus war.

**GPS:**
* *GPS aktuell*: die Position ist höchstens `GPS_MAX_AGE` Sekunden alt
  und wird aufgezeichnet.
* *GPS: kein Signal seit 2 min*: es wird die letzte bekannte Position
  angezeigt, aber nicht aufgezeichnet.
* *GPS sucht Signal* bzw. *GPS auf diesem Gerät nicht vorhanden* (PC).

Bleibt das GPS länger stumm, meldet die App es bei Android neu an (siehe
`GPS_RESTART_AFTER`).

### Die drei Modi

Alle drei brauchen einen verbundenen Sensor und schließen sich gegenseitig
aus: Ein Modus startet erst, wenn der laufende beendet ist. Sonst lautet
die Antwort z. B. „Messfahrt nicht möglich: erst Stationärer Modus
beenden.“

| Modus | Schreibt (ein Punkt je Messintervall) | GPS | Upload |
|---|---|---|---|
| **Messfahrt** | zwei KML-Spuren (PM2.5, PM10) und eine CSV, optional mit Name im Dateinamen | ja, für die Spur | nein |
| **Lokale Messung** | CSV, Ortsname im Dateinamen | nicht nötig | nein |
| **Stationär** | CSV `feinstaub_stationaer_<Zeit>.csv` | nein | alle `STAT_INT` s der Mittelwert seit dem letzten Upload |

Während einer Messung zeigt die Karte *Messung* Laufzeit, Zahl der Punkte,
die Mittelwerte seit Start, den Dateinamen, bei Messfahrt und lokaler
Messung einen Link zur Karte an der aktuellen GPS-Position und im
stationären Modus den letzten und den nächsten Upload, dazu einen Link
zum eigenen Sensor auf der Karte von sensor.community. Nach dem Stoppen
bleibt eine
Zusammenfassung stehen. Beim Stoppen, beim Wechsel des Modus und beim
Beenden kommt das angefangene Intervall als letzte, kürzere Zeile in die
Datei.

* **Messfahrt:** Ohne aktuelle Position bleiben Breite und Länge in der CSV
  leer und die KML-Spur setzt aus. Danach beginnt sie neu, statt eine gerade
  Linie über die Lücke zu ziehen. Der optionale Name aus dem Eingabefeld
  landet in CSV- und KML-Dateinamen, etwa
  `feinstaub_von_essen_nach_duisburg_<Zeit>.csv`.
* **Lokale Messung:** z. B. Kreidestaub in der Kletterhalle. Der Ort
  aus dem Eingabefeld landet im Dateinamen, etwa
  `feinstaub_kletterhalle_duisburg_20261008_17_08_24.csv`. Ohne Ort heißt
  die Datei `feinstaub_lokal_<Zeit>.csv`.
* **Stationär:** Der einzige Modus, der Daten aus der Hand gibt. Er sendet
  öffentlich unter der Sensor-ID `XSENSOR`, also nur am mit luftdaten
  vereinbarten Standort einschalten. Liegt ein aktueller GPS-Fix vor,
  startet die App den Modus nur innerhalb von `STATIONARY_MAX_DISTANCE_M`
  Metern um den konfigurierten Sensorstandort; ohne GPS/Fix, etwa am
  Laptop, blockiert diese Prüfung nicht. Hochgeladen wird per HTTPS.
  Fehlt QPython das `ssl`-Modul oder scheitert HTTPS dauerhaft an
  Zertifikaten bzw. Protokoll, geht der Upload über HTTP. Ein Timeout
  zählt nicht als dauerhaft. Auch nach Aus- und Wiedereinschalten wird
  nie öfter als alle `STAT_INT` Sekunden gesendet.

**Kein aktueller Messwert:** Ist der letzte Wert vom Sensor älter als
`MAX_MEASUREMENT_AGE` (Verbindung weg), wird nichts hochgeladen, und ein
Intervall ganz ohne neue Werte wird nicht aufgezeichnet. Rot erscheint
dann „Kein aktueller Messwert vom Sensor - nichts aufgezeichnet“ bzw. im
stationären Modus „... - nichts aufgezeichnet, nichts hochgeladen“.
Sobald wieder Werte kommen, verschwindet der Hinweis und die Messung
läuft weiter. Kamen im Intervall noch Werte, wird ihr Mittelwert
aufgezeichnet, auch wenn der Sensor kurz vor dem Intervallende aussetzt.

**Speicherort:** Unter Android `Download/Feinstaub` (mit jedem Dateimanager
erreichbar). Am PC, oder wenn QPython dort nicht schreiben darf, `output/`
neben `main.py`. Das gültige Verzeichnis steht ganz unten in der Oberfläche
unter *Speicherort*.

## Dateiformate

**CSV:** eine Kopfzeile, dann eine Zeile pro Messintervall, getrennt durch
`;`, mit Dezimalkomma (für ein deutsches Excel). Jede Zeile enthält den
Mittelwert über das Intervall, das zur angegebenen Zeit endet, auf eine
Nachkommastelle:

```
Zeit;PM2.5;PM10;Breite;Laenge
2026-10-10 00:42:55;9,8;20,2;51,440100;6,788400
2026-10-10 00:43:00;10,3;23,0;;
```

Koordinaten mit sechs Nachkommastellen. Ohne aktuelle Position (älter als
`GPS_MAX_AGE`, oder kein GPS wie am PC) bleiben Breite und Länge leer.

**KML:** `feinstaub_25_line_<Zeit>.kml` und `feinstaub_10_line_<Zeit>.kml`
bzw. mit Messfahrtnamen `feinstaub_<name>_25_line_<Zeit>.kml`, z. B. in
Google Earth anzusehen. Jeder Punkt liegt so hoch wie sein
Messwert, die Linie ist von grün (0) über gelb (25) nach rot (ab 50)
gefärbt. Abgeschlossen werden die Dateien bei *Stop*, beim Moduswechsel
und beim regulären Beenden der App. Wird QPython hart beendet (Akku leer,
von Android geschlossen), fehlt der Abschluss zunächst; die App trägt ihn
beim nächsten Start nach. Zeichnet eine zweite, noch laufende Instanz in
eine solche Datei weiter auf, entfernt sie den Abschluss beim nächsten
Punkt wieder; die Datei bleibt also gültig. Nicht reparierbare Dateien
heißen danach `*.kml.defekt`.

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

**Simulation:** Am einfachsten *Simulierter Sensor* in der Geräteliste
wählen (siehe *Bedienung*). Für Entwicklung und Tests ersetzt
`SDS011_FAKE=1` zusätzlich die ganze Hardware, Sensor und GPS, ab dem Start
(Windows-cmd: `set SDS011_FAKE=1`, PowerShell: `$env:SDS011_FAKE="1"`).
Dann gilt alles als simuliert, mit denselben Folgen wie oben.

```
SDS011_FAKE=1 python main.py
```

**Mit echtem Sensor gibt es am PC kein GPS.** Lokale Messung und
stationärer Modus brauchen keins. Eine Messfahrt läuft, schreibt aber nur
CSV mit leeren Koordinaten und keine KML-Spur.

**Umgebungsvariablen:**

| Variable | Wirkung |
|---|---|
| `SDS011_FAKE=1` | nur simulierter Sensor und simuliertes GPS, ab dem Start |
| `SDS011_HOST` | Adresse des Webservers, Standard `127.0.0.1` |
| `SDS011_PORT` | Port des Webservers, Standard `8080` |
| `SDS011_OUTDIR` | Ausgabeverzeichnis für Messdateien, Log und `einstellungen.json`, statt `Download/Feinstaub` bzw. `output/` (etwa für Testläufe) |

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
| `RECORD_INT` | `5` | Messintervall in Sekunden, bis es in der Oberfläche umgestellt wird: so lange wird gemittelt, dann ein Punkt in CSV/KML und Diagramm |
| `RECORD_INT_CHOICES` | `(1, 5, 10, 30, 60, 300, 900)` | Messintervalle zur Auswahl in der Oberfläche |
| `HISTORY_SIZE` | `4320` | Punkte im Verlauf des Diagramms (6 h bei 5 s, 3 Tage bei 1 min) |
| `GPS_INT` | `5` | Sekunden zwischen zwei GPS-Abfragen |
| `GPS_RESTART_AFTER` | `60` | GPS so viele Sekunden stumm: bei Android neu anmelden (nur auf dem Handy) |
| `GPS_RESTART_MAX` | `600` | Obergrenze dieser Wartezeit, sie verdoppelt sich bis dahin |
| `GPS_MAX_AGE` | `15` | Position älter als so viele Sekunden: nicht aufzeichnen |
| `STATIONARY_MAX_DISTANCE_M` | `500` | Bei frischem GPS-Fix maximal erlaubte Entfernung vom konfigurierten Sensorstandort für den stationären Modus |
| `STAT_INT` | `240` | Sekunden zwischen zwei Uploads im stationären Modus; sensor.community erwartet etwa alle 2–5 min einen Wert, also nicht unter 150 |
| `MAX_MEASUREMENT_AGE` | `10` | Messwert älter als so viele Sekunden: nicht aufzeichnen, nicht hochladen |
| `SENSOR_SILENCE_TIMEOUT` | `15` | So viele Sekunden keine Daten: Verbindung gilt als abgerissen, neu verbinden; bei gesetzter SDS011-Working-Period automatisch länger |
| `SDS011_POWER_SAVE_MIN_INTERVAL` | `300` | Ab diesem Messintervall setzt die App den Sensor auf den Energiespar-Zyklus |
| `SDS011_POWER_SAVE_PERIOD` | `5` | SDS011-Working-Period in Minuten: etwa 30 s messen, dann bis zum nächsten Zyklus schlafen |
| `SDS011_POWER_SAVE_SILENCE_SLACK` | `30` | Zuschlag in Sekunden für den Stille-Wächter während der SDS011-Schlafphasen |
| `SSP_UUID` | SPP-Standard-UUID | Bluetooth-Dienst des HC-Moduls (Android) |
| `RFCOMM_CHANNEL` | `1` | RFCOMM-Kanal am PC |
| `SDS011_BLUETOOTH_DEVICE_ID` | `00:14:03:05:59:17` | MAC des eigenen Moduls, vorgewählt bzw. Rückfall, wenn keine Geräteliste kommt |
| `XSENSOR` | `raspi-…` | Sensor-ID bei luftdaten.info |
| `LUFTDATEN_URL` | `https://api.luftdaten.info/v1/push-sensor-data/` | Upload-Adresse |
| `SENSOR_MAP_URL`, `LINKS` | Karte sensor.community, Grenzwerte Umweltbundesamt | externe Seiten der Oberfläche; `SENSOR_MAP_URL` auf den eigenen Sensorstandort zentrieren |
| `HTTP_HOST` | `127.0.0.1` | Adresse des Webservers (überschreibbar per `SDS011_HOST`) |
| `HTTP_PORT` | `8080` | Port des Webservers (überschreibbar per `SDS011_PORT`) |
| `ANDROID_OUTDIR` | `/storage/emulated/0/Download/Feinstaub` | Ausgabeverzeichnis unter Android, `None` für `output/` (überschreibbar per `SDS011_OUTDIR`) |

Das in der Oberfläche gewählte Messintervall speichert die App in
`einstellungen.json` im Ausgabeverzeichnis (`SETTINGS_FILE`). Diese Datei
hat Vorrang vor `RECORD_INT`; wer sie löscht, bekommt wieder den Wert aus
`config.py`.

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
  unter Python 3.14 abstürzt. Der Testserver schreibt in ein temporäres
  Verzeichnis (`SDS011_OUTDIR`), nicht in `output/`.

### Ordner fürs Handy

`python tools/build_phone.py` baut aus dem letzten Commit den Ordner
`SDS011-Android-qpython2/SDS011-Android/` (nicht versioniert): alle
Programmdateien außer `bluetooth_desktop.py`, dazu `views/`, `static/`,
`bottle.py` und `LIESMICH.txt`. Diesen Ordner per USB aufs Handy kopieren,
sodass `main.py` unter `qpython/projects/SDS011-Android/` liegt.

Automatisch nach jedem Commit, Merge, Checkout und Rebase, sobald die Hooks
einmal eingeschaltet sind:

```
git config core.hooksPath .githooks
```

Der Ordner wird jedes Mal neu erzeugt; Änderungen darin gehen verloren.

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
| `transport.py` | Transport-Schnittstelle, Bluetooth unter Android, Simulation, Auswahl echt/simuliert | config, protocol, logging_util; bluetooth_desktop erst bei Bedarf |
| `bluetooth_desktop.py` | Bluetooth am PC über RFCOMM, Geräteliste | config, logging_util, transport |
| `sensor.py` | Sensor-Thread: verbinden, lesen, bei Abbruch oder Stille neu verbinden | config, state, connection, logging_util, protocol, transport |
| `gps.py` | GPS-Quellen (am PC simuliert mit simuliertem Sensor) und GPS-Thread | config, connection, logging_util, state |
| `recorder.py` | Aufzeichnungs-Thread: Mittelwert je Messintervall in Verlauf und CSV/KML, Upload | config, kml, logging_util |
| `kml.py` | KML- und CSV-Zeilen schreiben, offene KML beim Start abschließen, Ampelfarben und -stufen | logging_util |
| `settings.py` | Einstellungen aus der Oberfläche lesen und speichern (`einstellungen.json`) | config, logging_util |
| `chart.py` | Verlaufsdiagramm als SVG zeichnen | – |
| `webapp.py` | Routen der Oberfläche (bottle) | config, kml, settings, logging_util; chart erst in der Route `/chart.svg` |
| `server.py` | mehrfädiger, stoppbarer Webserver | logging_util |
| `main.py` | startet und verdrahtet alles, beendet sauber | config, gps, kml, sensor, settings, transport, webapp, logging_util, recorder, server, state |
| `views/index.html` | Oberfläche (Markup, bottle-Template) | – |
| `static/app.js`, `static/app.css` | Verhalten und Aussehen der Oberfläche, ES5 ohne Bibliotheken (altes Android-WebView) | – |
| `static/favicon.svg` | Bildzeichen für den Browser-Tab | – |
