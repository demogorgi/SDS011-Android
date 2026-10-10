# -*- coding: utf-8 -*-
"""Logging. Importiert nur config, damit hier nie ein Zirkelimport
entstehen kann (kml.py und main.py haengen beide dran).

Wichtig: write_log() hat keine Nebenwirkung auf die Fehleranzeige im
Frontend mehr. Fehler, die der Benutzer sehen soll, laufen ueber
AppState.report_error().
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
    """Ziel und Schwelle umstellen -- benutzt von den Tests."""
    global _logfile, _level
    if logfile is not None:
        _logfile = logfile
    if level is not None:
        _level = level


def get_level():
    return _level


def to_text(value):
    """Macht aus beliebigem Input Text. Unter Python 2 ist str == bytes,
    deshalb der Umweg ueber decode()."""
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
    """Hebt das Log des letzten Laufs auf, statt es wegzuwerfen.

    Frueher wurde beim Start geloescht -- wer nach einer Messfahrt in
    der App nachsehen wollte, was schiefgelaufen war, hatte das Log
    durch den Neustart bereits vernichtet. Eine Generation reicht und
    laesst den Speicher des Geraets in Ruhe.
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
    """Schreibt eine Logzeile, wenn level <= LOG_LEVEL.

    Darf niemals eine Exception nach aussen geben -- ein kaputtes Log
    soll die Messung nicht anhalten.
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
