# -*- coding: utf-8 -*-
"""Logdatei und Textumwandlung fuer alle Module der App.

Importiert nur config, weil fast jedes Modul hier importiert und sonst
Zirkelimporte entstehen. write_log() schreibt nur in die Datei; Fehler,
die der Benutzer sehen soll, laufen ueber AppState.report_error().
"""

from __future__ import absolute_import

import datetime
import io
import os
import threading

import config

try:                          # Python 2
    _TEXT = unicode
except NameError:             # Python 3
    _TEXT = str

_lock = threading.Lock()
_logfile = config.LOGFILE
_level = config.LOG_LEVEL


def configure(logfile=None, level=None):
    """Stellt Logdatei und Schwelle um -- fuer die Tests."""
    global _logfile, _level
    if logfile is not None:
        _logfile = logfile
    if level is not None:
        _level = level


def get_level():
    return _level


def to_text(value):
    """Macht aus beliebigem Wert Text (unicode bzw. str).

    Unter Python 2 ist str gleich bytes: unicode(exc) scheitert dort an
    Exceptions, deren Text Umlaute als Bytes enthaelt. Dafuer der Umweg
    ueber str(...).decode().
    """
    if isinstance(value, _TEXT):
        return value
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    try:
        return _TEXT(value)
    except Exception:
        try:
            return str(value).decode('utf-8', 'replace')
        except Exception:
            return _TEXT(repr(value))


def previous_logfile(path=None):
    """Pfad des Vorgaenger-Logs: output/logfile.txt -> output/logfile.1.txt"""
    base, ext = os.path.splitext(path if path is not None else _logfile)
    return base + '.1' + ext


def rotate_logfile():
    """Benennt das Log des letzten Laufs um (siehe previous_logfile),
    damit es nach einem Neustart noch lesbar ist. Wird von main.py beim
    Start aufgerufen.

    Eine Generation reicht und schont den Speicher des Geraets.
    """
    config.ensure_outdir()
    if not os.path.exists(_logfile):
        return
    previous = previous_logfile()
    try:
        # os.replace() gibt es erst ab Python 3.3, und os.rename()
        # scheitert unter Windows, wenn das Ziel existiert.
        if os.path.exists(previous):
            os.remove(previous)
        os.rename(_logfile, previous)
    except OSError:
        # Wenn das Rotieren scheitert, lieber leeren als mit dem alten
        # Log weiterschreiben.
        try:
            os.remove(_logfile)
        except OSError:
            pass


def write_log(level, msg):
    """Schreibt eine Logzeile, wenn level <= LOG_LEVEL (0 = Fehler,
    hoeher = ausfuehrlicher).

    Thread-sicher. Gibt nie eine Exception weiter: ein kaputtes Log darf
    die Messung nicht anhalten.
    """
    if level > _level:
        return
    try:
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = u'{0} [{1}] {2}'.format(stamp, level, to_text(msg))
        with _lock:
            with io.open(_logfile, 'a', encoding='utf-8', newline='') as handle:
                handle.write(line)
                handle.write(u'\n')
    except Exception:
        pass
