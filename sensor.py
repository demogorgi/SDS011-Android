# -*- coding: utf-8 -*-
"""Thread, der den SDS011 ausliest und die Messwerte in den AppState schreibt.

Zugleich die Verbindungsaufsicht: Der Benutzer aeussert nur den Wunsch
(die Weboberflaeche setzt state.connection_wanted). Aufbau und
Wiederverbinden nach einem Abbruch erledigt der Reader selbst -- nach
Fehlschlaegen mit wachsender Wartezeit (Backoff), damit ein
ausgeschalteter Sensor nicht Akku und Log belastet.
Die Hardware steckt hinter dem uebergebenen Transport.
"""

from __future__ import absolute_import

import threading

import config
import state as state_module
from state import monotonic
from connection import Backoff
from logging_util import to_text, write_log
import protocol
from protocol import FrameDecoder
from transport import TransportError


class SensorReader(threading.Thread):
    """Daemon-Thread: Verbindung halten, Bytes lesen, Pakete dekodieren."""

    # So viel wird pro Runde maximal angefordert. Der Sensor sendet
    # etwa ein 10-Byte-Paket pro Sekunde.
    READ_SIZE = 64

    def __init__(self, state, transport, idle_wait=0.2, backoff=None,
                 silence_timeout=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._state = state
        self._transport = transport
        self._decoder = FrameDecoder()
        self._idle_wait = idle_wait
        self._backoff = backoff if backoff is not None else Backoff()
        self._silence_timeout = (config.SENSOR_SILENCE_TIMEOUT
                                 if silence_timeout is None else silence_timeout)
        # Zeitpunkt (monotonic) der letzten Bytes bzw. des Verbindens.
        self._last_data = None
        self._working_period = None
        self._running = True
        self.frames_seen = 0
        self._first_frame_at = None
        self._power_save_active = False
        self._power_save_cycle_started_at = None
        self._power_save_next_wake_at = None
        self._sleeping = None

    # -- Verbindung ---------------------------------------------------
    def _awake_seconds(self):
        return (config.SDS011_POWER_SAVE_SETTLE
                + config.SDS011_POWER_SAVE_SAMPLE_WINDOW)

    def _cycle_seconds(self):
        return max(float(self._state.record_interval()), self._awake_seconds())

    def _usable_sample(self, now):
        """True, wenn ein Rohwert in Mittelwerte einfliessen darf."""
        if not self._power_save_active:
            return True
        if self._power_save_cycle_started_at is None:
            self._power_save_cycle_started_at = now
        return (now - self._power_save_cycle_started_at
                >= config.SDS011_POWER_SAVE_SETTLE)

    def _silence_limit(self):
        """Wie lange Stille normal ist.

        Im manuellen Energiesparmodus schlaeft der Sensor zwischen den
        Wachphasen. Diese geplante Pause darf nicht als
        Verbindungsabbruch gelten. Beim Wecken setzt _set_sleeping(False)
        _last_data neu, damit der Sensor ein paar Sekunden fuer den ersten
        Frame hat.
        """
        if self._sleeping:
            return max(self._silence_timeout,
                       self._cycle_seconds() + config.SDS011_POWER_SAVE_SILENCE_SLACK)
        return self._silence_timeout

    def _set_working_period(self, minutes, reason):
        """Setzt die Working Period des SDS011 und merkt den Zustand."""
        command = protocol.build_work_period_command(minutes)
        self._transport.write(command)
        self._working_period = minutes
        label = (u'Dauerbetrieb' if minutes == 0
                 else u'{0}-Minuten-Zyklus'.format(minutes))
        write_log(1, u'SDS011: {0} ({1})'.format(label, reason))

    def _set_sleeping(self, sleeping, reason):
        """Schlaeft oder weckt den Sensor per manuellem Sleep-Kommando."""
        if self._sleeping is sleeping:
            return
        command = protocol.build_sleep_command(sleeping)
        self._transport.write(command)
        self._sleeping = sleeping
        label = u'Schlaf' if sleeping else u'wach'
        write_log(1, u'SDS011: {0} ({1})'.format(label, reason))
        if not sleeping:
            # Nach einer geplanten Schlafphase ist _last_data alt. Ab dem
            # Wake-Kommando soll der normale Stille-Waechter wieder gelten.
            self._last_data = monotonic()

    def _reset_power_save(self):
        self._power_save_active = False
        self._power_save_cycle_started_at = None
        self._power_save_next_wake_at = None
        self._first_frame_at = None

    def _ensure_continuous_awake(self, reason):
        """Dauerbetrieb und wach: Grundlage fuer echte 1-Hz-Rohwerte."""
        if self._working_period != 0:
            self._set_working_period(0, reason)
        self._set_sleeping(False, reason)

    def _apply_power_save(self):
        interval = self._state.record_interval()
        reason = u'Messintervall {0} s'.format(interval)
        if interval < config.SDS011_POWER_SAVE_MIN_INTERVAL:
            self._reset_power_save()
            self._ensure_continuous_awake(reason)
            return

        if not self._power_save_active:
            self._reset_power_save()
            self._power_save_active = True
        if self._working_period != 0:
            self._set_working_period(0, reason)

        now = monotonic()
        if self._sleeping:
            if self._power_save_cycle_started_at is not None:
                self._power_save_next_wake_at = (
                    self._power_save_cycle_started_at + self._cycle_seconds())
            if self._power_save_next_wake_at is not None and now >= self._power_save_next_wake_at:
                self._set_sleeping(False, u'geplante Wachphase')
                self._power_save_cycle_started_at = None
                self._power_save_next_wake_at = None
                self._first_frame_at = None
            return
        if self._sleeping is None:
            self._set_sleeping(False, reason)

        if self._first_frame_at is None:
            return
        if self._power_save_cycle_started_at is None:
            self._power_save_cycle_started_at = self._first_frame_at
        if now - self._power_save_cycle_started_at >= self._awake_seconds():
            self._power_save_next_wake_at = (
                self._power_save_cycle_started_at + self._cycle_seconds())
            self._first_frame_at = None
            self._set_sleeping(True, reason)

    def _restore_continuous(self, reason):
        """Beim Trennen/Beenden den persistenten Working-Period-Wert
        zurueck auf Dauerbetrieb setzen. Fehler verhindern das Trennen
        nicht.
        """
        if self._working_period is None and not self._transport.is_connected():
            self._working_period = None
            return
        try:
            self._set_sleeping(False, reason)
            self._set_working_period(0, reason)
        except Exception as exc:
            write_log(0, u'SDS011-Dauerbetrieb konnte nicht gesetzt werden: {0}'.format(
                to_text(exc)))
        self._working_period = None
        self._sleeping = None
        self._reset_power_save()

    def _drop(self, message):
        """Verbindung trennen, Decoder zuruecksetzen und den Grund anzeigen.

        Halb empfangene Pakete gehoeren zur alten Verbindung, deshalb ein
        neuer Decoder.
        """
        try:
            self._transport.disconnect()
        except Exception as exc:
            write_log(0, u'disconnect fehlgeschlagen: {0}'.format(to_text(exc)))
        self._working_period = None
        self._sleeping = None
        self._reset_power_save()
        self._decoder = FrameDecoder()
        if self._state.connection_wanted:
            self._state.set_connection(state_module.CONN_RETRYING, message)
        else:
            self._state.set_connection(state_module.CONN_DISCONNECTED, message)

    def _drop_and_wait(self, message):
        """Nach einem Abbruch die Backoff-Zeit abwarten, bevor neu verbunden
        wird -- wie nach einem gescheiterten Versuch. Sonst verbindet ein
        Sensor, der die Verbindung annimmt und gleich wieder verliert oder
        schweigt, ohne Pause immer wieder."""
        self._drop(message)
        self._wait_retry(self._backoff.next_delay(), self._state.device()[0])

    def _wait_retry(self, delay, device_id):
        """Wartet bis zum naechsten Verbindungsversuch, endet aber sofort,
        wenn der Benutzer trennt, ein anderes Geraet waehlt oder die App
        beendet wird. Sonst reagierte die Oberflaeche nach einigen
        Fehlversuchen bis zu einer Minute lang nicht."""
        deadline = monotonic() + delay
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return
            if self._state.wait(min(self._idle_wait, remaining)):
                return
            if not self._state.connection_wanted:
                return
            if self._state.device()[0] != device_id:
                # Neues Geraet: gleich versuchen, ohne alte Wartezeit.
                self._backoff.reset()
                return

    def _try_connect(self):
        """Ein Verbindungsversuch. Liefert True bei Erfolg.

        Bei einem Fehler wartet die Methode selbst die Backoff-Zeit ab
        (state.wait, endet sofort beim Beenden) und liefert dann False.
        """
        device_id, _ = self._state.device()
        self._state.set_connection(state_module.CONN_CONNECTING, u'')
        try:
            self._transport.connect(device_id)
            self._working_period = None
            self._sleeping = None
            self._reset_power_save()
            self._ensure_continuous_awake(u'Verbinden')
        except TransportError as exc:
            try:
                self._transport.disconnect()
            except Exception:
                pass
            self._working_period = None
            delay = self._backoff.next_delay()
            write_log(1, u'Verbindung fehlgeschlagen ({0}), naechster Versuch in {1:.0f}s'
                      .format(to_text(exc), delay))
            self._state.set_connection(state_module.CONN_RETRYING, to_text(exc))
            self._wait_retry(delay, device_id)
            return False
        except Exception as exc:
            try:
                self._transport.disconnect()
            except Exception:
                pass
            self._working_period = None
            # Unerwartetes protokollieren und anzeigen, aber den Thread
            # nicht beenden.
            delay = self._backoff.next_delay()
            write_log(0, u'Unerwarteter Fehler beim Verbinden: {0}'.format(to_text(exc)))
            self._state.set_connection(state_module.CONN_RETRYING,
                                       u'Unerwarteter Fehler: {0}'.format(to_text(exc)))
            self._wait_retry(delay, device_id)
            return False

        self._decoder = FrameDecoder()
        self._last_data = monotonic()
        self._state.set_connection(state_module.CONN_CONNECTED, u'')
        return True

    # -- Hauptschleife ------------------------------------------------
    def run(self):
        while self._running and self._state.sensing:
            # 1. Der Benutzer will keine Verbindung.
            if not self._state.connection_wanted:
                if self._transport.is_connected():
                    self._restore_continuous(u'Trennen')
                    self._transport.disconnect()
                    write_log(1, 'Verbindung auf Wunsch getrennt')
                if self._state.connection()[0] != state_module.CONN_DISCONNECTED:
                    self._state.set_connection(state_module.CONN_DISCONNECTED, u'')
                self._backoff.reset()
                if self._state.wait(self._idle_wait):
                    break
                continue

            # 2. Verbindung gewuenscht, aber nicht da.
            if not self._transport.is_connected():
                self._try_connect()
                continue

            # 3. Verbunden -- lesen.
            try:
                self._apply_power_save()
                chunk = self._transport.read(self.READ_SIZE)
            except TransportError as exc:
                write_log(0, u'Lesefehler: {0}'.format(to_text(exc)))
                self._drop_and_wait(to_text(exc))
                continue
            except Exception as exc:
                write_log(0, u'Unerwarteter Lesefehler: {0}'.format(to_text(exc)))
                self._drop_and_wait(u'Unerwarteter Lesefehler: {0}'.format(to_text(exc)))
                continue

            if not chunk:
                # Lange nichts: Verbindung als abgerissen behandeln. Unter
                # Android meldet bluetoothReadReady nach einem Abbruch nur
                # "keine Daten" und nie einen Fehler.
                silent = monotonic() - self._last_data
                if silent < 0:
                    # Uhr zurueckgestellt (Python 2: monotonic = time.time).
                    self._last_data = monotonic()
                limit = self._silence_limit()
                if silent > limit:
                    write_log(1, u'Seit {0:.0f}s keine Daten vom Sensor, verbinde neu'
                              .format(limit))
                    self._drop_and_wait(
                        u'Keine Daten vom Sensor. Eingeschaltet?')
                    continue
                # Nichts da: kurz warten, sonst dreht die Schleife leer.
                if self._state.wait(self._idle_wait):
                    break
                continue

            self._last_data = monotonic()
            # Erst echte Daten beweisen, dass die Verbindung steht.
            self._backoff.reset()

            for reading in self._decoder.feed(chunk):
                self.frames_seen += 1
                read_at = monotonic()
                if self._first_frame_at is None:
                    self._first_frame_at = read_at
                self._state.set_measurement(reading.pm_25, reading.pm_10,
                                            at=read_at,
                                            usable=self._usable_sample(read_at))
                write_log(3, u'pm_25={0}, pm_10={1}'.format(
                    reading.pm_25, reading.pm_10))

    def stop(self):
        """Schleife beenden und den Transport schliessen."""
        self._running = False
        self._restore_continuous(u'Beenden')
        self._transport.close()
