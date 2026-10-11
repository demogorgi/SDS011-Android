# -*- coding: utf-8 -*-
"""Einstellungen aus der Oberflaeche, die einen Neustart ueberleben.

Derzeit nur das Messintervall, als JSON in config.SETTINGS_FILE, etwa
{"record_interval": 30}. main.py liest die Datei beim Start, webapp.py
schreibt sie, wenn das Intervall umgestellt wird. Eine fehlende oder
kaputte Datei verhindert den Start nicht: dann gelten die Werte aus
config.py.
"""

from __future__ import absolute_import

import io
import json
import os

import config
from logging_util import to_text, write_log


def _path(path):
    # Erst beim Aufruf nachsehen, nicht als Standardwert der Funktion:
    # so koennen Tests config.SETTINGS_FILE umbiegen.
    return config.SETTINGS_FILE if path is None else path


def load(path=None):
    """Gespeicherte Einstellungen als dict; {} ohne oder bei kaputter
    Datei (dann mit Logeintrag)."""
    path = _path(path)
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        write_log(0, u'Einstellungen nicht lesbar ({0}): {1}'.format(
            to_text(path), to_text(exc)))
        return {}
    if not isinstance(data, dict):
        write_log(0, u'Einstellungen ohne gueltigen Inhalt: {0}'.format(to_text(path)))
        return {}
    return data


def _replace(source, target):
    """source in target umbenennen und ein vorhandenes target ersetzen.

    os.replace() gibt es erst ab Python 3.3, und os.rename() scheitert
    unter Windows, wenn das Ziel existiert. Dann das Ziel vorher
    entfernen; im kurzen Moment dazwischen fehlt die Datei, load()
    liefert dann eben die Standardwerte.
    """
    replace = getattr(os, 'replace', None)
    if replace is not None:
        replace(source, target)
        return
    if os.name == 'nt' and os.path.exists(target):
        os.remove(target)
    os.rename(source, target)


def save(data, path=None):
    """Schreibt data als JSON. Erst in eine Hilfsdatei, dann umbenannt:
    bricht das Schreiben ab (Akku leer), bleibt die alte Datei heil.
    Liefert True oder bei einem Fehler False (mit Logeintrag)."""
    path = _path(path)
    temp = path + '.tmp'
    try:
        text = json.dumps(data, sort_keys=True)
        # Python 2 liefert hier bytes; io.open will Text.
        if not isinstance(text, type(u'')):
            text = text.decode('utf-8')
        with io.open(temp, 'w', encoding='utf-8', newline='') as handle:
            handle.write(text)
            handle.write(u'\n')
        _replace(temp, path)
        return True
    except (IOError, OSError, TypeError, ValueError) as exc:
        write_log(0, u'Einstellungen nicht gespeichert ({0}): {1}'.format(
            to_text(path), to_text(exc)))
        try:
            os.remove(temp)
        except OSError:
            pass
        return False
