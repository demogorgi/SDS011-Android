# -*- coding: utf-8 -*-
"""Wachsende Wartezeiten zwischen Wiederholungsversuchen.

Genutzt von sensor.py (Bluetooth-Verbindung) und gps.py (Neuanmeldung
des GPS). Reine Rechnerei ohne Uhr und ohne Warten, damit sie ohne
echte Wartezeit testbar ist; das Warten selbst macht der Aufrufer.
"""

from __future__ import absolute_import


class Backoff(object):
    """Exponentiell wachsende Wartezeit: start, start*factor, ...,
    hoechstens maximum Sekunden.

    Nicht in festem Takt neu versuchen: Ist der Sensor aus oder hat das
    GPS keinen Empfang, kostet das auf dem Handy Akku und flutet das Log.
    """

    def __init__(self, start=1.0, factor=2.0, maximum=60.0):
        self.start = float(start)
        self.factor = float(factor)
        self.maximum = float(maximum)
        self.attempts = 0

    def next_delay(self):
        """Wartezeit fuer den naechsten Versuch und Zaehler hochsetzen."""
        delay = self.start * (self.factor ** self.attempts)
        self.attempts += 1
        return min(delay, self.maximum)

    def peek(self):
        """Wartezeit des naechsten Versuchs, ohne hochzuzaehlen."""
        return min(self.start * (self.factor ** self.attempts), self.maximum)

    def reset(self):
        """Nach einem Erfolg wieder mit start beginnen."""
        self.attempts = 0
