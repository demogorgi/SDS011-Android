/* Oberflaeche der Feinstaub-App.
 *
 * Strikt ES5 ohne Bibliotheken: das Android-WebView in QPython ist alt.
 * Also kein let/const, keine Pfeilfunktionen, keine Template-Strings,
 * kein fetch, keine Promises -- Anfragen per XMLHttpRequest.
 *
 * Der Server ist die Quelle der Wahrheit. Knoepfe, Modus und Anzeige
 * richten sich nach /status/ (jede Sekunde), nicht nach dem letzten Klick;
 * so stimmt alles auch nach einem Reload oder mit einem zweiten Geraet.
 * Das Diagramm zeichnet der Server als SVG (/chart.svg) aus demselben
 * Verlauf, aus dem die CSV entsteht.
 */
(function () {
  'use strict';

  // Leer = relative URLs. So passt die Seite zu jeder Adresse und jedem
  // Port des Servers (SDS011_HOST, SDS011_PORT).
  var SCRIPT_ROOT = '';

  var POLL_MS = 1000;
  var REQUEST_TIMEOUT_MS = 10000;
  // Spaetestens so oft neu zeichnen, damit die Zeitachse weiterlaeuft.
  var CHART_MAX_AGE_MS = 60000;
  // Nach einem Fehler beim Diagramm nicht bei jeder Abfrage neu bitten.
  var CHART_RETRY_MS = 10000;
  var TOAST_MS = 3000;
  // "Alles": direkt nach dem Start fuellt der kurze Verlauf so die ganze
  // Breite, statt als schmaler Streifen am rechten Rand zu kleben.
  var DEFAULT_RANGE = 0;
  var RANGES = [600, 3600, 21600, 0];
  // Rueckfall, falls der Server keine Einstufung liefert: so alt darf
  // ein Messwert sein, um als "live" zu gelten (config.MAX_MEASUREMENT_AGE).
  var LIVE_MAX_AGE = 10;
  var POWER_SAVE_MIN_INTERVAL = 300;
  var POWER_SAVE_SLEEP_SLACK = 30;

  // Die drei Modi und ihre bestehenden Routen.
  // card: die Moduskarte (label mit Radio) im Template.
  var MODES = {
    trip: {start: '/start/', stop: '/stopp/', flag: 'recording', card: 'modeTrip',
           name: 'Messfahrt', action: 'Messfahrt starten'},
    local: {start: '/localon/', stop: '/localoff/', flag: 'local', card: 'modeLocal',
            name: 'Lokale Messung', action: 'Lokale Messung starten'},
    stat: {start: '/staton/', stop: '/statoff/', flag: 'stationary', card: 'modeStat',
           name: 'Stationäre Messung', action: 'Stationär starten'}
  };
  var MODE_KEYS = ['trip', 'local', 'stat'];
  // session.mode aus /status/ -> Schluessel oben
  var SESSION_MODES = {messfahrt: 'trip', lokal: 'local', stationaer: 'stat'};

  var LEVEL_TEXT = {good: 'gut', elevated: 'erhöht', high: 'hoch', none: 'kein Wert'};
  // Schwellen wie kml.color_selection_rgb -- nur fuer den Rueckfall.
  var LEVEL_LIMITS = {pm_25: [25, 50], pm_10: [40, 50]};

  var STORE_RANGE = 'feinstaub.range';
  var STORE_CHART_SERIES = 'feinstaub.chart_series';
  var STORE_MODE = 'feinstaub.mode';
  var STORE_PLACE = 'feinstaub.place';
  var STORE_TRIP_NAME = 'feinstaub.trip_name';
  // Gleicher Schluessel wie das kleine Skript im <head> von index.html.
  var STORE_THEME = 'feinstaub.theme';

  // Darstellung: Reihenfolge beim Tippen auf den Schalter.
  var THEMES = ['auto', 'light', 'dark'];
  var THEME_TEXT = {auto: 'automatisch', light: 'hell', dark: 'dunkel'};
  // Farbe der Android-Statusleiste, wie --bg in app.css.
  var THEME_BAR = {light: '#f4f4f2', dark: '#0d0d0d'};

  // -- Zustand ---------------------------------------------------------
  var last = null;             // letzte Antwort von /status/
  var lastAt = 0;              // wann sie kam (Date.now())
  var offline = false;
  var pollTimer = null;
  var pollBusy = false;
  var pollAgain = false;
  var pollSeq = 0;             // Nummer der zuletzt gesendeten Statusabfrage
  var appliedSeq = 0;          // Nummer der zuletzt angezeigten
  // Knopf-id -> erste Abfragenummer, die den Befehl sicher schon sieht.
  // Bis dahin bleibt der Knopf gesperrt (siehe command()).
  var pending = {};
  // Ob die Moduswahl schon feststeht (gemerkt, angeklickt oder laufend).
  // Sonst wird nach dem Laden der Modus der letzten Messung vorgewaehlt.
  var modeSettled = false;
  var stationaryIntervalPending = false;
  var toastTimer = null;
  var resizeTimer = null;
  var chart = {
    range: DEFAULT_RANGE,
    series: 'mean',
    key: null,                 // Parameter des angezeigten Bilds
    loadedAt: 0,
    failedAt: 0,
    busy: false,
    again: false,
    shown: false
  };

  // -- Hilfen ----------------------------------------------------------
  function byId(id) {
    return document.getElementById(id);
  }

  // Nur schreiben, wenn sich etwas aendert: spart DOM-Arbeit und haelt
  // aria-live-Bereiche ruhig.
  function setText(node, text) {
    text = (text === null || text === undefined) ? '' : String(text);
    if (node && node.textContent !== text) {
      node.textContent = text;
    }
  }

  // Ueber das Attribut, nicht node.hidden: aeltere WebViews kennen die
  // Eigenschaft nicht, die CSS-Regel [hidden] greift aber immer.
  function show(node, visible) {
    if (!node) {
      return;
    }
    if (visible) {
      if (node.hasAttribute('hidden')) {
        node.removeAttribute('hidden');
      }
    } else if (!node.hasAttribute('hidden')) {
      node.setAttribute('hidden', '');
    }
  }

  function setClass(node, name, on) {
    if (!node) {
      return;
    }
    if (on) {
      node.classList.add(name);
    } else {
      node.classList.remove(name);
    }
  }

  function setAttr(node, name, value) {
    if (node && node.getAttribute(name) !== value) {
      node.setAttribute(name, value);
    }
  }

  function setDisabled(node, disabled) {
    if (node && node.disabled !== !!disabled) {
      node.disabled = !!disabled;
    }
  }

  function isNumber(value) {
    return typeof value === 'number' && !isNaN(value);
  }

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  // 3725 -> "01:02:05"
  function fmtClock(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    return pad2(h) + ':' + pad2(m) + ':' + pad2(seconds % 60);
  }

  // 192 -> "03:12", ab einer Stunde "1:03:12"
  function fmtCountdown(seconds) {
    seconds = Math.max(0, Math.ceil(seconds));
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    return (h ? h + ':' + pad2(m) : pad2(m)) + ':' + pad2(s);
  }

  // Alter wie bisher: bis 2 min in Sekunden, danach in Minuten
  function fmtAge(seconds) {
    return seconds < 120 ? seconds + ' s' : Math.floor(seconds / 60) + ' min';
  }

  // 5 -> "5 s", 300 -> "5 min" (wie die Knoepfe im Template)
  function fmtInterval(seconds) {
    if (seconds >= 60 && seconds % 60 === 0) {
      return (seconds / 60) + ' min';
    }
    return seconds + ' s';
  }

  // Messwerte mit Dezimalkomma, wie in der CSV
  function fmtValue(value) {
    var n = parseFloat(value);
    if (isNaN(n)) {
      return '–';
    }
    return n.toFixed(1).replace('.', ',');
  }

  // Epoch-Sekunden -> "14:32" (Ortszeit des Geraets)
  function fmtTime(epoch) {
    var d = new Date(epoch * 1000);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function fmtMapCoord(value) {
    var n = parseFloat(value);
    return isNaN(n) ? null : n.toFixed(5);
  }

  // Dauer einer Messung: "45 s", "2:19 min", "1:05 h"
  function fmtDuration(seconds) {
    seconds = Math.max(0, Math.round(seconds));
    if (seconds < 60) {
      return seconds + ' s';
    }
    if (seconds < 3600) {
      return Math.floor(seconds / 60) + ':' + pad2(seconds % 60) + ' min';
    }
    return Math.floor(seconds / 3600) + ':' + pad2(Math.floor((seconds % 3600) / 60)) + ' h';
  }

  // Zeitspanne "14:32–15:10", nicht von heute mit Datum davor
  function fmtSpan(started, ended) {
    var text = fmtTime(started);
    if (isNumber(ended)) {
      text += '–' + fmtTime(ended);
    }
    var day = new Date(started * 1000);
    var today = new Date();
    if (day.toDateString() !== today.toDateString()) {
      text = day.getDate() + '.' + (day.getMonth() + 1) + '. ' + text;
    }
    return text;
  }

  // Sekunden seit der letzten Statusantwort -- damit Laufzeit und
  // Countdowns zwischen zwei Abfragen weiterzaehlen.
  function sinceStatus() {
    return lastAt ? (Date.now() - lastAt) / 1000 : 0;
  }

  // localStorage kann fehlen oder werfen (privater Modus, altes WebView).
  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      // egal: dann merkt sich die Seite die Auswahl eben nicht
    }
  }

  // Sucht vom Klickziel aufwaerts den Knopf innerhalb von container
  // (Element.closest gibt es im alten WebView nicht).
  function buttonFrom(target, container) {
    while (target && target !== container) {
      if (target.tagName === 'BUTTON') {
        return target;
      }
      target = target.parentNode;
    }
    return null;
  }

  function pageHidden() {
    return !!(document.hidden || document.webkitHidden);
  }

  // -- Anfragen --------------------------------------------------------
  // GET auf den eigenen Server. ok(data) mit geparstem JSON (oder Text
  // bei raw), fail() bei Netzfehler, Timeout, HTTP-Fehler oder kaputtem
  // JSON.
  function request(path, ok, fail, raw) {
    var xhr = new XMLHttpRequest();
    var finished = false;
    xhr.open('GET', SCRIPT_ROOT + path, true);
    try {
      xhr.timeout = REQUEST_TIMEOUT_MS;
    } catch (e) {
      // altes WebView: dann eben ohne Zeitgrenze
    }
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4 || finished) {
        return;
      }
      finished = true;
      if (xhr.status < 200 || xhr.status >= 300) {
        if (fail) {
          fail(xhr);
        }
        return;
      }
      var data = xhr.responseText;
      if (!raw) {
        try {
          data = JSON.parse(data);
        } catch (e) {
          if (fail) {
            fail(xhr);
          }
          return;
        }
      }
      if (ok) {
        ok(data);
      }
    };
    xhr.send(null);
    return xhr;
  }

  // -- Statusabfrage ---------------------------------------------------
  // Eine einzige Kette aus setTimeout: poll() bricht den geplanten
  // Durchlauf ab und fragt sofort. Laeuft gerade eine Anfrage, wird
  // danach noch einmal gefragt -- nie zwei Ketten nebeneinander.
  function poll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (pollBusy) {
      pollAgain = true;
      return;
    }
    pollBusy = true;
    var seq = ++pollSeq;
    request('/status/', function (data) {
      pollBusy = false;
      setOffline(false);
      try {
        applyStatus(data, seq);
      } finally {
        schedule();
      }
    }, function () {
      pollBusy = false;
      setOffline(true);
      schedule();
    });
  }

  function schedule() {
    if (pollAgain) {
      pollAgain = false;
      poll();
      return;
    }
    // Bei ausgeschaltetem Bildschirm nicht fragen -- die Messung laeuft
    // auf dem Server weiter; beim Einschalten holt visibilitychange auf.
    if (pageHidden()) {
      return;
    }
    pollTimer = setTimeout(poll, POLL_MS);
  }

  function setOffline(on) {
    if (offline !== on) {
      offline = on;
      renderBanner();
    }
  }

  function applyStatus(data, seq) {
    appliedSeq = seq;
    last = data;
    lastAt = Date.now();
    renderBanner();
    applyConnection(data);
    applyLive(data);
    applyGps(data);
    applyInterval(data);
    applyModes(data);
    applySession(data);
    applyInfo(data);
    tick();
    updateChart(false);
  }

  // -- Banner ----------------------------------------------------------
  function renderBanner() {
    var banner = byId('errorBanner');
    var text = '';
    if (offline) {
      text = 'Keine Verbindung zur Messanwendung.';
    } else if (last && last.error_msg) {
      text = last.error_msg;
    }
    setText(byId('errorText'), text);
    setClass(banner, 'is-offline', offline);
    show(banner, !!text);
    // Auch oben sichtbar, falls weiter unten gescrollt ist. Die naechste
    // Statusantwort setzt die Pille wieder auf den Sensorzustand.
    if (offline) {
      setAttr(byId('connStatus'), 'data-state', 'off');
      setText(byId('connText'), 'offline');
    }
  }

  // -- Sensorverbindung ------------------------------------------------
  function connState(data) {
    if (data.connection === 'verbunden') {
      return data.connection_wanted ? 'on' : 'closing';
    }
    return data.connection_wanted ? 'wait' : 'off';
  }

  function applyConnection(data) {
    var state = connState(data);
    var name = data.device_name || data.device || 'Sensor';
    var retrying = data.connection === 'wartet auf nächsten Versuch';
    // Simulierter Sensor gewaehlt: ueberall kenntlich machen.
    var simulated = !!data.simulated && state !== 'off';

    // Statuspille oben
    var pill = byId('connStatus');
    var pillState = state === 'closing' ? 'on' : state;
    setAttr(pill, 'data-state', pillState);
    setText(byId('connText'), state === 'off' ? 'getrennt'
            : state === 'wait' ? (retrying ? 'wartet' : 'verbinde …')
            : (simulated ? 'simuliert' : 'verbunden'));
    setClass(pill, 'is-sim', simulated);
    setAttr(pill, 'title', 'Sensor: ' + data.connection);

    // Karte: getrennt = Auswahl, sonst eine Zeile
    var card = byId('sensorCard');
    setAttr(card, 'data-state', state === 'closing' ? 'on' : state);
    show(byId('sensorSetup'), state === 'off');
    show(byId('sensorLink'), state !== 'off');

    // Name oben, Zustand darunter; der Grund eines Fehlschlags bekommt
    // eine eigene Zeile ueber die volle Breite.
    var sub;
    var error = '';
    if (state === 'wait') {
      sub = retrying ? 'Neuer Versuch gleich …' : 'Verbinde …';
      error = data.connection_error || (retrying ? 'Sensor eingeschaltet und in Reichweite?' : '');
    } else {
      sub = state === 'closing' ? 'wird getrennt …'
          : (simulated ? 'verbunden – Werte sind erfunden' : 'verbunden');
    }
    show(byId('simBadge'), simulated);
    setText(byId('sensorName'), name);
    setText(byId('sensorSub'), sub);
    setText(byId('sensorError'), error);
    show(byId('sensorError'), !!error);
    // Die Adresse nur als Tooltip -- im Alltag zaehlt der Name.
    setAttr(byId('sensorLink'), 'title', data.device || '');

    var disconnectBtn = byId('disconnectBtn');
    setText(disconnectBtn, state === 'wait' ? 'Abbrechen' : 'Trennen');
    // Verbinden nur ohne Verbindungswunsch, Trennen nur mit -- auch
    // mitten in einer Wartezeit (wie bisher).
    setButton(byId('connectBtn'), !data.connection_wanted);
    setButton(disconnectBtn, !!data.connection_wanted);

    // Solange verbunden wird, soll die Auswahl nicht wandern.
    if (data.connection_wanted && data.device) {
      byId('deviceSelect').value = data.device;
    }
  }

  function loadDevices() {
    var select = byId('deviceSelect');
    var button = byId('reloadDevices');
    setClass(button, 'is-busy', true);
    request('/devices/', function (data) {
      setClass(button, 'is-busy', false);
      var keep = select.value;
      var list = data.devices || [];
      var i, option;
      select.innerHTML = '';
      if (!list.length) {
        option = document.createElement('option');
        option.value = '';
        option.textContent = 'kein Gerät gefunden';
        select.appendChild(option);
        return;
      }
      for (i = 0; i < list.length; i++) {
        option = document.createElement('option');
        option.value = list[i].id;
        option.textContent = list[i].name || list[i].id;
        select.appendChild(option);
      }
      // Laufender Verbindungswunsch > bisherige Auswahl > Vorschlag
      if (last && last.connection_wanted && last.device) {
        select.value = last.device;
      } else if (keep) {
        select.value = keep;
      }
      if (!select.value && data.selected) {
        select.value = data.selected;
      }
    }, function () {
      setClass(button, 'is-busy', false);
      toast('Geräteliste nicht abrufbar.', 'error');
    });
  }

  // -- Live-Werte ------------------------------------------------------
  // Einstufung vom Server; fehlt sie (alter Server), selbst rechnen.
  function levelOf(data, field) {
    var level = data[field + '_level'];
    if (level) {
      return level;
    }
    var age = data.measurement_age;
    if (data.connection !== 'verbunden' || (isNumber(age) && age > LIVE_MAX_AGE)) {
      return 'none';
    }
    var value = parseFloat(data[field]);
    var limits = LEVEL_LIMITS[field];
    if (isNaN(value)) {
      return 'none';
    }
    return value >= limits[1] ? 'high' : value >= limits[0] ? 'elevated' : 'good';
  }

  function applyTile(tileId, valueId, levelId, data, field) {
    var level = levelOf(data, field);
    var age = data.measurement_age;
    // Noch nie ein Messwert: Strich statt 0,0 -- 0 sieht aus wie echte
    // saubere Luft.
    var never = age === null || (age === undefined && data.connection !== 'verbunden');
    setText(byId(valueId), never ? '–' : fmtValue(data[field]));
    setClass(byId(tileId), 'is-stale', level === 'none');
    var levelNode = byId(levelId);
    setAttr(levelNode, 'data-level', level);
    // Steht noch ein alter Wert da, sagt "veraltet" mehr als "kein Wert".
    setText(levelNode, level === 'none' && !never ? 'veraltet'
            : LEVEL_TEXT[level] || LEVEL_TEXT.none);
  }

  function applyLive(data) {
    applyTile('tile25', 'pm25Value', 'pm25Level', data, 'pm_25');
    applyTile('tile10', 'pm10Value', 'pm10Level', data, 'pm_10');

    var age = data.measurement_age;
    var connected = data.connection === 'verbunden';
    var fresh;
    if (data.pm_25_level !== undefined) {
      fresh = data.pm_25_level !== 'none';
    } else {
      fresh = connected && (!isNumber(age) || age <= LIVE_MAX_AGE);
    }
    var text;
    if (fresh) {
      if (!isNumber(age)) {
        text = 'live';
      } else if (age <= 0) {
        text = 'live · gerade eben';
      } else if (age > LIVE_MAX_AGE) {
        text = 'Sensorzyklus · letzter Wert vor ' + fmtAge(age);
      } else {
        text = 'live · vor ' + age + ' s';
      }
    } else if (!connected) {
      text = isNumber(age) ? 'kein Sensor · letzter Wert vor ' + fmtAge(age) : 'kein Sensor';
    } else if (isNumber(age)) {
      text = 'kein aktueller Wert · letzter vor ' + fmtAge(age);
    } else {
      text = 'warte auf den ersten Messwert …';
    }
    setText(byId('liveAge'), text);
    setClass(byId('liveDot'), 'is-live', fresh);
  }

  // Zeigt, ob die GPS-Position aktuell ist oder wie alt sie ist. Die
  // Schwelle gps_max_age kommt vom Server (config.GPS_MAX_AGE).
  function applyGps(data) {
    var age = data.gps_age;
    var state;
    var text;
    var coords = '';
    if (!data.gps_available) {
      state = 'none';
      text = 'GPS auf diesem Gerät nicht vorhanden';
    } else if (age === null || age === undefined) {
      state = 'warn';
      text = 'GPS sucht Signal …';
    } else {
      if (age <= (data.gps_max_age || 15)) {
        state = 'ok';
        text = 'GPS aktuell';
      } else {
        state = 'warn';
        text = 'GPS: kein Signal seit ' + fmtAge(age);
      }
      coords = data.lat + ', ' + data.lon;
    }
    setAttr(byId('gpsRow'), 'data-state', state);
    setText(byId('gpsStatus'), text);
    setText(byId('gpsCoords'), coords);
    show(byId('gpsCoords'), !!coords);
    applyPositionMapLinks(data);
  }

  function hasFreshGps(data) {
    var age = data.gps_age;
    var lat = parseFloat(data.lat);
    var lon = parseFloat(data.lon);
    return !!data.gps_available && isNumber(age) && age <= (data.gps_max_age || 15)
      && !isNaN(lat) && !isNaN(lon)
      && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
      && (lat !== 0 || lon !== 0);
  }

  function mapUrlAt(anchor, lat, lon) {
    var fallback = anchor.getAttribute('data-map-fallback') || anchor.getAttribute('href') || '';
    var match = fallback.match(/^(.*#)([^\/]+)\/[^\/]+\/[^\/]+$/);
    if (!match) {
      return fallback;
    }
    return match[1] + match[2] + '/' + lat + '/' + lon;
  }

  function applyPositionMapLinks(data) {
    var links = document.querySelectorAll('a[data-link="karte_position"]');
    var fresh = hasFreshGps(data);
    var lat = fmtMapCoord(data.lat);
    var lon = fmtMapCoord(data.lon);
    var i, link, fallback;
    for (i = 0; i < links.length; i++) {
      link = links[i];
      fallback = link.getAttribute('data-map-fallback');
      if (!fallback) {
        fallback = link.getAttribute('href') || '';
        link.setAttribute('data-map-fallback', fallback);
      }
      setAttr(link, 'href', fresh ? mapUrlAt(link, lat, lon) : fallback);
      setAttr(link, 'title', fresh ? 'Karte an aktueller GPS-Position'
              : 'Karte am festen Sensorstandort');
    }
  }

  // -- Messintervall ---------------------------------------------------
  function buildIntervalButtons(group, choices) {
    var i, button;
    while (group.firstChild) {
      group.removeChild(group.firstChild);
    }
    for (i = 0; i < choices.length; i++) {
      button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('data-seconds', String(choices[i]));
      button.setAttribute('aria-pressed', 'false');
      button.textContent = fmtInterval(choices[i]);
      group.appendChild(button);
    }
  }

  function listContains(list, value) {
    var i;
    for (i = 0; list && i < list.length; i++) {
      if (list[i] === value) {
        return true;
      }
    }
    return false;
  }

  function sameIntervalButtons(buttons, choices) {
    var i;
    if (buttons.length !== choices.length) {
      return false;
    }
    for (i = 0; i < choices.length; i++) {
      if (parseInt(buttons[i].getAttribute('data-seconds'), 10) !== choices[i]) {
        return false;
      }
    }
    return true;
  }

  function stationaryIntervalMode(data) {
    return selectedMode() === 'stat' || activeMode(data) === 'stat';
  }

  function intervalChoices(data) {
    if (stationaryIntervalMode(data) && data.stationary_intervals
        && data.stationary_intervals.length) {
      return data.stationary_intervals;
    }
    return data.intervals || [];
  }

  function ensureStationaryInterval(data, choices) {
    if (!stationaryIntervalMode(data) || !choices.length
        || listContains(choices, data.interval) || stationaryIntervalPending) {
      return;
    }
    stationaryIntervalPending = true;
    request('/interval/?seconds=' + encodeURIComponent(choices[0]),
            function () {
              stationaryIntervalPending = false;
              poll();
            }, function () {
              stationaryIntervalPending = false;
              toast('Messintervall konnte nicht gesetzt werden.', 'error');
            });
  }

  function updateChartCaption(interval) {
    var text;
    if (chart.series === 'raw') {
      text = 'Rohwerte vom Sensor';
    } else {
      text = isNumber(interval) ? 'Mittelwerte je ' + fmtInterval(interval) : 'Mittelwerte';
    }
    setText(byId('chartCaption'), text);
  }

  function applyInterval(data) {
    var group = byId('intervalSelect');
    var buttons = group.getElementsByTagName('button');
    var choices = intervalChoices(data);
    if (!sameIntervalButtons(buttons, choices)) {
      buildIntervalButtons(group, choices);
      buttons = group.getElementsByTagName('button');
    }
    var current = data.interval;
    var i;
    for (i = 0; i < buttons.length; i++) {
      setAttr(buttons[i], 'aria-pressed',
              parseInt(buttons[i].getAttribute('data-seconds'), 10) === current ? 'true' : 'false');
      setClass(buttons[i], 'is-busy', false);
    }
    show(byId('intervalField'), buttons.length > 0 && isNumber(current));
    updateChartCaption(current);
    ensureStationaryInterval(data, choices);
  }

  function onIntervalClick(event) {
    var button = buttonFrom(event.target, byId('intervalSelect'));
    if (!button || button.getAttribute('aria-pressed') === 'true') {
      return;
    }
    setClass(button, 'is-busy', true);
    request('/interval/?seconds=' + encodeURIComponent(button.getAttribute('data-seconds')),
            function (data) {
              toast(data.value, data.refused ? 'warn' : '');
              poll();
            }, function () {
              setClass(button, 'is-busy', false);
              toast('Messintervall konnte nicht gesetzt werden.', 'error');
            });
  }

  // -- Modus und Start/Stopp -------------------------------------------
  function activeMode(data) {
    var i;
    for (i = 0; i < MODE_KEYS.length; i++) {
      if (data[MODES[MODE_KEYS[i]].flag]) {
        return MODE_KEYS[i];
      }
    }
    return null;
  }

  // Das Radio in der Moduskarte
  function modeRadio(mode) {
    return byId(MODES[mode].card).getElementsByTagName('input')[0];
  }

  function selectedMode() {
    var i;
    for (i = 0; i < MODE_KEYS.length; i++) {
      if (modeRadio(MODE_KEYS[i]).checked) {
        return MODE_KEYS[i];
      }
    }
    return 'trip';
  }

  function selectMode(mode) {
    modeRadio(mode).checked = true;
    renderModeDetails();
  }

  // Zusatzbereich direkt unter dem gewaehlten Modus.
  function renderModeDetails() {
    var mode = selectedMode();
    var i;
    for (i = 0; i < MODE_KEYS.length; i++) {
      setClass(byId(MODES[MODE_KEYS[i]].card), 'is-selected', MODE_KEYS[i] === mode);
    }
    show(byId('tripDetails'), mode === 'trip');
    show(byId('placeField'), mode === 'local');
    show(byId('statWarn'), mode === 'stat');
    setText(byId('startText'), MODES[mode].action);
  }

  function applyModes(data) {
    var active = activeMode(data);
    var connected = data.connection === 'verbunden';

    show(byId('setupPanel'), !active);
    show(byId('sessionPanel'), !!active);
    show(byId('startBtn'), !active);
    show(byId('stopBtn'), !!active);

    // Starten nur mit verbundenem Sensor, sonst entstehen Dateien voller
    // Nullen, die wie echte Messwerte aussehen. Die Modi schliessen sich
    // aus: laeuft einer, ist Start gesperrt. Der Server prueft beides
    // zusaetzlich. Stoppen geht immer, auch ohne Sensor.
    // Simulierte Werte nie oeffentlich hochladen: stationaer gesperrt.
    var statBlocked = !!data.simulated && selectedMode() === 'stat';
    var positionBlocked = data.stationary_position_ok === false && selectedMode() === 'stat';
    setButton(byId('startBtn'), connected && !active && !statBlocked && !positionBlocked);
    setButton(byId('stopBtn'), !!active);
    setText(byId('startHint'), !connected ? 'Zuerst oben den Sensor verbinden.'
            : statBlocked ? 'Mit dem simulierten Sensor wird nichts hochgeladen. '
                            + 'Für den stationären Modus einen echten Sensor verbinden.'
            : positionBlocked ? 'Stationär nur am konfigurierten Standort starten: '
                                + 'aktuell ca. ' + data.stationary_distance_m + ' m entfernt, '
                                + 'erlaubt sind ' + data.stationary_max_distance_m + ' m.'
            : '');
    show(byId('startHint'), (!connected || statBlocked || positionBlocked) && !active);

    // Laufenden Modus vorwaehlen -- nach dem Stoppen steht er dann noch da.
    if (active) {
      if (selectedMode() !== active) {
        selectMode(active);
      }
      modeSettled = true;
    } else if (!modeSettled) {
      // Frisch geladen ohne gemerkte Wahl: den Modus der letzten Messung.
      // Stationaer nie von selbst -- der Upload ist oeffentlich.
      var previous = data.session ? SESSION_MODES[data.session.mode] : null;
      if (previous && previous !== 'stat') {
        selectMode(previous);
      }
      if (data.session && data.session.place) {
        if (previous === 'local' && !byId('placeInput').value) {
          byId('placeInput').value = data.session.place;
        } else if (previous === 'trip' && !byId('tripNameInput').value) {
          byId('tripNameInput').value = data.session.place;
        }
      }
      modeSettled = true;
    }

    // Ortsangabe nicht ueberschreiben, waehrend getippt wird.
    var place = byId('placeInput');
    if (data.local && document.activeElement !== place && data.place !== undefined) {
      place.value = data.place;
    }
    var tripName = byId('tripNameInput');
    if (data.recording && document.activeElement !== tripName && data.place !== undefined) {
      tripName.value = data.place;
    }
  }

  function onStart() {
    var mode = selectedMode();
    var path = MODES[mode].start;
    if (mode === 'local') {
      var place = byId('placeInput').value || '';
      storageSet(STORE_PLACE, place);
      path += '?place=' + encodeURIComponent(place);
    } else if (mode === 'trip') {
      var name = byId('tripNameInput').value || '';
      storageSet(STORE_TRIP_NAME, name);
      path += '?name=' + encodeURIComponent(name);
    }
    command(path, byId('startBtn'), MODES[mode].name + ' konnte nicht gestartet werden.');
  }

  function onStop() {
    var active = last ? activeMode(last) : null;
    if (!active) {
      return;
    }
    command(MODES[active].stop, byId('stopBtn'), 'Stoppen konnte nicht gesendet werden.');
  }

  // Schickt einen Befehl und liest danach den Zustand neu. Der Knopf
  // bleibt gesperrt, bis eine Statusabfrage zurueck ist, die erst nach
  // der Antwort auf den Befehl gesendet wurde. Eine Abfrage, die schon
  // vorher unterwegs war, kennt den Befehl noch nicht und gaebe den
  // Knopf sonst fuer einen zweiten Klick frei.
  function command(path, button, failText) {
    if (button) {
      pending[button.id] = Infinity;
      button.disabled = true;
      setClass(button, 'is-busy', true);
    }
    var done = function () {
      if (button) {
        pending[button.id] = pollSeq + 1;
      }
      poll();
    };
    request(path, function (data) {
      toast(data.value, data.refused ? 'warn' : '');
      done();
    }, function () {
      toast(failText || 'Befehl konnte nicht gesendet werden.', 'error');
      done();
    });
  }

  function isPending(button) {
    var need = pending[button.id];
    if (need === undefined) {
      return false;
    }
    if (appliedSeq >= need) {
      delete pending[button.id];
      return false;
    }
    return true;
  }

  // Knopf nach Serverzustand freigeben -- ausser ein Befehl ist unterwegs.
  function setButton(button, allowed) {
    var busy = isPending(button);
    setDisabled(button, !allowed || busy);
    setClass(button, 'is-busy', busy);
  }

  // -- Laufende und letzte Messung -------------------------------------
  function sessionElapsed(session) {
    if (!session) {
      return null;
    }
    if (isNumber(session.elapsed)) {
      return session.elapsed;
    }
    if (isNumber(session.started)) {
      var end = isNumber(session.ended) ? session.ended : Date.now() / 1000;
      return Math.max(0, end - session.started);
    }
    return null;
  }

  // Die laufende Sitzung -- direkt nach dem Start steht in session noch
  // kurz die vorige (active=False), bis der Recorder die neue anlegt.
  function runningSession(data) {
    var session = data.session;
    return session && session.active ? session : null;
  }

  function sensorActivityText(data) {
    var age = data.measurement_age;
    if (data.connection !== 'verbunden') {
      return 'Sensor getrennt';
    }
    if (!isNumber(age)) {
      return 'wartet auf ersten Messwert';
    }
    if (isNumber(data.interval) && data.interval >= POWER_SAVE_MIN_INTERVAL
        && data.measurement_usable === false && age <= LIVE_MAX_AGE) {
      return 'Sensor stabilisiert';
    }
    if (age <= LIVE_MAX_AGE) {
      return 'Sensor wach';
    }
    if (isNumber(data.interval) && data.interval >= POWER_SAVE_MIN_INTERVAL
        && age <= data.interval + POWER_SAVE_SLEEP_SLACK) {
      return 'Sensor schläft';
    }
    return 'kein aktueller Sensorwert';
  }

  function applySession(data) {
    var active = activeMode(data);
    var session = data.session || null;
    show(byId('positionMapRun'), active === 'trip' || active === 'local');

    if (active) {
      var running = runningSession(data);
      var place = (active === 'local' || active === 'trip') && data.place
        ? ' · ' + data.place : '';
      setText(byId('sessionMode'), MODES[active].name + ' aktiv' + place
              + ' · ' + sensorActivityText(data));
      setText(byId('sessionPoints'), running && isNumber(running.points) ? running.points : '–');
      setText(byId('sessionAvg25'), running ? fmtValue(running.avg_pm25) : '–');
      setText(byId('sessionAvg10'), running ? fmtValue(running.avg_pm10) : '–');
      setText(byId('sessionFile'), (running && running.file) || '–');
      show(byId('uploadInfo'), active === 'stat');
      if (active === 'stat') {
        applyUpload(data);
      }
    }

    // Zusammenfassung der letzten Messung, solange keine laeuft
    var showLast = !active && !!session && session.active === false;
    show(byId('lastSession'), showLast);
    if (showLast) {
      var mode = SESSION_MODES[session.mode];
      var elapsed = sessionElapsed(session);
      setText(byId('lastWhen'), isNumber(session.started) ? fmtSpan(session.started, session.ended) : '');
      setText(byId('lastMode'), (mode ? MODES[mode].name : 'Messung')
              + (session.place ? ' · ' + session.place : ''));
      setText(byId('lastDuration'), isNumber(elapsed) ? fmtDuration(elapsed) : '–');
      setText(byId('lastPoints'), isNumber(session.points) ? session.points : '–');
      setText(byId('lastAvg25'), fmtValue(session.avg_pm25));
      setText(byId('lastAvg10'), fmtValue(session.avg_pm10));
      setText(byId('lastFile'), session.file || 'keine Datei – kein Punkt aufgezeichnet');
    }
  }

  function applyUpload(data) {
    var box = byId('uploadInfo');
    var upload = data && data.upload;
    var state = 'none';
    var text = 'Noch kein Upload';
    if (upload && upload.last_at) {
      state = upload.last_ok ? 'ok' : 'fail';
      text = 'Letzter Upload ' + fmtTime(upload.last_at) + ' · '
        + (upload.last_ok ? 'erfolgreich' : 'fehlgeschlagen');
      if (upload.last_ok && isNumber(upload.last_pm25) && isNumber(upload.last_pm10)) {
        text += ': PM2.5 ' + fmtValue(upload.last_pm25)
          + ' · PM10 ' + fmtValue(upload.last_pm10) + ' µg/m³';
      }
      if (!upload.last_ok && upload.last_message) {
        text += ': ' + upload.last_message;
      }
    } else {
      text = 'Upload wartet auf ersten Mittelwert';
    }
    setAttr(box, 'data-state', state);
    setText(byId('uploadLast'), text);
  }

  // Jede Sekunde: Laufzeit und Countdowns zwischen zwei Abfragen
  // weiterzaehlen. Ein einziges setInterval, beim Start angelegt.
  function tick() {
    if (!last) {
      return;
    }
    var active = activeMode(last);
    var head = byId('headMode');
    show(head, !!active);
    // Laeuft eine Messung, wird die Verbindungspille schmal (nur Punkt),
    // damit beide Pillen auch auf kleinen Handys in die Kopfzeile passen.
    setClass(byId('appbarStatus'), 'is-running', !!active);
    if (!active) {
      return;
    }
    var since = sinceStatus();
    var base = sessionElapsed(runningSession(last));
    var clock = fmtClock(isNumber(base) ? base + since : 0);
    setText(byId('sessionElapsed'), clock);
    setText(byId('headModeText'), clock);
    setAttr(head, 'aria-label', MODES[active].name + ' aktiv seit ' + clock);
    setAttr(head, 'title', MODES[active].name);

    // Bis 99 s in Sekunden, darueber mm:ss (Intervalle bis 15 min)
    var next = isNumber(last.next_point_in)
      ? Math.max(0, Math.ceil(last.next_point_in - since)) : null;
    setText(byId('nextPoint'), next === null ? '–'
            : next < 100 ? 'in ' + next + ' s' : 'in ' + fmtCountdown(next));

    if (active === 'stat') {
      var upload = last.upload;
      var nextUpload = isNumber(last.next_point_in)
        ? last.next_point_in - since
        : (upload && isNumber(upload.next_in) ? upload.next_in - since : null);
      setText(byId('uploadNext'), nextUpload === null ? ''
              : nextUpload <= 0 ? 'Upload mit nächstem Mittelwert gleich'
              : 'Upload mit nächstem Mittelwert in ' + fmtCountdown(nextUpload));
    }
  }

  // -- Info ------------------------------------------------------------
  // Den Statustext des Servers (data.value) zeigt die Seite nicht mehr
  // eigens an: Modus, Mittelwerte, Upload und Fehler stehen jeweils an
  // ihrem Platz. Er bleibt als Tooltip am Kopf der Messung.
  function applyInfo(data) {
    setAttr(byId('measureTitle'), 'title', data.value || '');
    if (data.outdir) {
      setText(byId('outdirText'), data.outdir);
    }
  }

  // -- Diagramm --------------------------------------------------------
  // Pixelgenau zur echten Breite: der Server zeichnet in dieser Groesse,
  // die Schrift wird also nicht skaliert.
  function chartSize() {
    var box = byId('chart');
    var width = Math.floor(box.clientWidth);
    var height = Math.round(width * 0.6);
    return {w: width, h: Math.max(200, Math.min(340, height))};
  }

  // Neu laden nur, wenn sich Verlauf, Zeitraum, Groesse, Intervall oder
  // die Verbindung geaendert haben -- und spaetestens jede Minute fuer
  // die Zeitachse. Die Verbindung zaehlt nur als ja/nein: davon haengt
  // die Meldung im leeren Diagramm ab ("Kein Sensor verbunden"), die
  // Zwischenzustaende wie "verbinde" aendern daran nichts.
  function updateChart(force) {
    var size = chartSize();
    if (size.w <= 0) {
      return;
    }
    var status = last || {};
    var key = [chart.series, chart.range, size.w, size.h,
               chart.series === 'raw' ? status.raw_history_rev : status.history_rev,
               status.interval,
               status.connection === 'verbunden' ? 1 : 0].join('|');
    var now = Date.now();
    if (!force) {
      if (key === chart.key && now - chart.loadedAt < CHART_MAX_AGE_MS) {
        return;
      }
      if (chart.failedAt && now - chart.failedAt < CHART_RETRY_MS) {
        return;
      }
    }
    if (chart.busy) {
      chart.again = true;
      return;
    }
    chart.busy = true;
    var box = byId('chart');
    setAttr(box, 'aria-busy', 'true');
    if (!chart.shown) {
      placeholder('Diagramm wird geladen …', size.h);
    }
    request('/chart.svg?range=' + chart.range + '&w=' + size.w + '&h=' + size.h
            + '&series=' + encodeURIComponent(chart.series),
            function (text) {
              chart.busy = false;
              chart.key = key;
              chart.loadedAt = Date.now();
              chart.failedAt = 0;
              renderSvg(text);
              chartDone();
            }, function () {
              chart.busy = false;
              chart.failedAt = Date.now();
              if (!chart.shown) {
                placeholder('Diagramm nicht verfügbar.', size.h);
              }
              chartDone();
            }, true);
  }

  function chartDone() {
    setAttr(byId('chart'), 'aria-busy', 'false');
    if (chart.again) {
      chart.again = false;
      updateChart(false);
    }
  }

  // Das SVG kommt als Text und wird direkt eingesetzt (nicht als <img>):
  // nur so greifen die --pmc-*-Farben der Seite.
  function renderSvg(text) {
    var markup = String(text)
      .replace(/^\s*<\?xml[^>]*\?>/, '')
      .replace(/<!DOCTYPE[^>]*>/i, '');
    byId('chart').innerHTML = markup;
    chart.shown = true;
  }

  function placeholder(text, height) {
    var box = byId('chart');
    var div = document.createElement('div');
    div.className = 'chart-empty';
    div.style.height = height + 'px';
    div.textContent = text;
    box.innerHTML = '';
    box.appendChild(div);
  }

  function setRange(range) {
    chart.range = range;
    var buttons = byId('rangeSelect').getElementsByTagName('button');
    var i;
    for (i = 0; i < buttons.length; i++) {
      setAttr(buttons[i], 'aria-pressed',
              parseInt(buttons[i].getAttribute('data-range'), 10) === range ? 'true' : 'false');
    }
  }

  function setChartSeries(series) {
    chart.series = series === 'raw' ? 'raw' : 'mean';
    var buttons = byId('chartSeriesSelect').getElementsByTagName('button');
    var i;
    for (i = 0; i < buttons.length; i++) {
      setAttr(buttons[i], 'aria-pressed',
              buttons[i].getAttribute('data-series') === chart.series ? 'true' : 'false');
    }
    updateChartCaption(last && last.interval);
  }

  function onChartSeriesClick(event) {
    var button = buttonFrom(event.target, byId('chartSeriesSelect'));
    if (!button) {
      return;
    }
    var series = button.getAttribute('data-series');
    if (series === chart.series) {
      return;
    }
    setChartSeries(series);
    storageSet(STORE_CHART_SERIES, chart.series);
    updateChart(true);
  }

  function onRangeClick(event) {
    var button = buttonFrom(event.target, byId('rangeSelect'));
    if (!button) {
      return;
    }
    var range = parseInt(button.getAttribute('data-range'), 10);
    if (range === chart.range) {
      return;
    }
    setRange(range);
    storageSet(STORE_RANGE, String(range));
    updateChart(true);
  }

  // -- Meldung unten ---------------------------------------------------
  function toast(text, kind) {
    if (!text) {
      return;
    }
    var box = byId('toast');
    setText(byId('toastMsg'), text);
    box.className = 'toast is-shown' + (kind ? ' is-' + kind : '');
    if (toastTimer) {
      clearTimeout(toastTimer);
    }
    toastTimer = setTimeout(function () {
      box.className = 'toast';
      toastTimer = null;
    }, TOAST_MS);
  }

  // -- Externe Links ---------------------------------------------------
  // Das WebView von QPython oeffnet keine neuen Fenster: ein Klick auf
  // einen Link mit target="_blank" verpufft dort. Unter Android oeffnet
  // deshalb der Server den Link per Intent im Browser des Systems
  // (/open/). Am PC bleibt es ein gewoehnlicher Link.
  function linkFrom(node) {
    while (node && node !== document) {
      if (node.nodeName === 'A' && node.getAttribute('data-link')) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function onLinkClick(event) {
    if (document.body.getAttribute('data-open-external') !== '1') {
      return;
    }
    var link = linkFrom(event.target);
    if (!link) {
      return;
    }
    event.preventDefault();
    request('/open/?link=' + encodeURIComponent(link.getAttribute('data-link')),
            function (data) {
              if (data.opened) {
                toast(data.value || 'Im Browser geöffnet.', '');
              } else {
                toast(data.value || 'Link konnte nicht geöffnet werden.', 'error');
              }
            }, function () {
              toast('Link konnte nicht geöffnet werden.', 'error');
            });
  }

  // -- Darstellung -----------------------------------------------------
  // "auto" folgt der Systemeinstellung (prefers-color-scheme). Android 7
  // kennt keine systemweite Dunkel-Einstellung, deshalb laesst sich hell
  // oder dunkel auch fest waehlen -- gemerkt pro Geraet im Browser.
  function systemTheme() {
    try {
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        return 'light';
      }
    } catch (e) {
      // altes WebView ohne matchMedia: der dunkle Standard
    }
    return 'dark';
  }

  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === 'light' || mode === 'dark') {
      root.setAttribute('data-theme', mode);
    } else {
      mode = 'auto';
      root.removeAttribute('data-theme');
    }
    var button = byId('themeBtn');
    var label = 'Darstellung: ' + THEME_TEXT[mode];
    setAttr(button, 'data-mode', mode);
    setAttr(button, 'aria-label', label);
    setAttr(button, 'title', label);
    setAttr(byId('themeColor'), 'content', THEME_BAR[mode === 'auto' ? systemTheme() : mode]);
    return mode;
  }

  function onThemeClick() {
    var current = byId('themeBtn').getAttribute('data-mode');
    var next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
    next = applyTheme(next);
    storageSet(STORE_THEME, next);
    toast('Darstellung: ' + THEME_TEXT[next]
          + (next === 'auto' ? ' (wie das System)' : ''), '');
  }

  // -- Start -----------------------------------------------------------
  function restore() {
    applyTheme(storageGet(STORE_THEME));
    var range = parseInt(storageGet(STORE_RANGE), 10);
    setRange(RANGES.indexOf(range) >= 0 ? range : DEFAULT_RANGE);
    setChartSeries(storageGet(STORE_CHART_SERIES));

    var mode = storageGet(STORE_MODE);
    if (mode && MODES.hasOwnProperty(mode)) {
      selectMode(mode);
      modeSettled = true;
    } else {
      renderModeDetails();
    }

    var place = storageGet(STORE_PLACE);
    if (place) {
      byId('placeInput').value = place;
    }
    var tripName = storageGet(STORE_TRIP_NAME);
    if (tripName) {
      byId('tripNameInput').value = tripName;
    }
  }

  function wire() {
    byId('connectBtn').addEventListener('click', function () {
      var device = byId('deviceSelect').value || '';
      command('/connect/?device=' + encodeURIComponent(device), this,
              'Verbinden konnte nicht angestoßen werden.');
    });
    byId('disconnectBtn').addEventListener('click', function () {
      command('/disconnect/', this, 'Trennen konnte nicht gesendet werden.');
    });
    byId('reloadDevices').addEventListener('click', loadDevices);
    document.addEventListener('click', onLinkClick);
    byId('themeBtn').addEventListener('click', onThemeClick);

    byId('startBtn').addEventListener('click', onStart);
    byId('stopBtn').addEventListener('click', onStop);

    var i;
    for (i = 0; i < MODE_KEYS.length; i++) {
      modeRadio(MODE_KEYS[i]).addEventListener('change', function () {
        modeSettled = true;
        storageSet(STORE_MODE, selectedMode());
        renderModeDetails();
        // Startknopf und Hinweis haengen am gewaehlten Modus (stationaer
        // ist mit simuliertem Sensor gesperrt).
        if (last) {
          applyInterval(last);
          applyModes(last);
        }
      });
    }

    // Enter in Name/Ort startet die gewaehlte Messung
    byId('tripNameInput').addEventListener('keydown', function (event) {
      if ((event.key === 'Enter' || event.keyCode === 13) && !byId('startBtn').disabled) {
        event.preventDefault();
        onStart();
      }
    });
    byId('placeInput').addEventListener('keydown', function (event) {
      if ((event.key === 'Enter' || event.keyCode === 13) && !byId('startBtn').disabled) {
        event.preventDefault();
        onStart();
      }
    });

    byId('intervalSelect').addEventListener('click', onIntervalClick);
    byId('chartSeriesSelect').addEventListener('click', onChartSeriesClick);
    byId('rangeSelect').addEventListener('click', onRangeClick);

    window.addEventListener('resize', function () {
      if (resizeTimer) {
        clearTimeout(resizeTimer);
      }
      resizeTimer = setTimeout(function () {
        updateChart(false);
      }, 250);
    });

    // Bildschirm wieder an: sofort Zustand und Diagramm holen. Das
    // Diagramm ist dann vollstaendig -- der Server hat weitergezeichnet.
    var onVisibility = function () {
      if (!pageHidden()) {
        chart.key = null;
        chart.failedAt = 0;
        poll();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    document.addEventListener('webkitvisibilitychange', onVisibility);
  }

  restore();
  wire();
  loadDevices();
  poll();
  setInterval(tick, 1000);
}());
