# -*- coding: utf-8 -*-
"""Wartezeiten zwischen Verbindungsversuchen.

Reine Rechnerei ohne Uhr und ohne Threads, damit sie ohne echte
Wartezeit testbar ist.
"""

from __future__ import absolute_import


class Backoff(object):
    """Wachsende Wartezeit zwischen Fehlversuchen.

    Frueher versuchte read() jede Sekunde neu zu verbinden, endlos. Auf
    dem Handy kostet das Akku und flutet das Log -- ausgerechnet dann,
    wenn der Sensor aus ist.
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
        self.attempts = 0
