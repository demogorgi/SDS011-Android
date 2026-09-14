# -*- coding: utf-8 -*-
"""Prueft, ob sich alle Module unter Python 2 uebersetzen lassen.

Wird uebersprungen, wenn kein Python-2-Interpreter gefunden wird. Auf
einer Maschine mit Python 2 im PATH (oder per PYTHON2=... gesetzt)
laeuft der Test echt durch und faengt py3-only-Syntax ab.

Achtung: das prueft nur die Syntax, nicht die Semantik. Die typische
py2-Falle in diesem Projekt ist str/bytes -- deshalb arbeitet
protocol.py durchgaengig mit bytearray, dessen Indizierung auf beiden
Python-Generationen int liefert.
"""

from __future__ import absolute_import

import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULES = [
    'config.py', 'logging_util.py', 'state.py', 'protocol.py',
    'transport.py', 'gps.py', 'sensor.py', 'recorder.py', 'webapp.py',
    'kml.py', 'main.py',
]


def find_python2():
    candidates = []
    if os.environ.get('PYTHON2'):
        candidates.append(os.environ['PYTHON2'])
    candidates += ['python2', 'python2.7',
                   r'C:\Python27\python.exe', '/usr/bin/python2']
    for candidate in candidates:
        try:
            proc = subprocess.Popen([candidate, '-c', 'import sys; print(sys.version_info[0])'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = proc.communicate()
            if proc.returncode == 0 and out.strip() == b'2':
                return candidate
        except (OSError, IOError):
            continue
    return None


class Python2SyntaxTest(unittest.TestCase):

    def test_all_modules_compile_under_python2(self):
        python2 = find_python2()
        if python2 is None:
            raise unittest.SkipTest(
                'kein Python 2 gefunden -- mit PYTHON2=<pfad> erzwingbar')

        for name in MODULES:
            path = os.path.join(REPO, name)
            proc = subprocess.Popen(
                [python2, '-c',
                 'import py_compile, sys; py_compile.compile(sys.argv[1], doraise=True)',
                 path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate()
            self.assertEqual(
                proc.returncode, 0,
                '%s laesst sich unter Python 2 nicht uebersetzen:\n%s'
                % (name, err.decode('utf-8', 'replace')))


if __name__ == '__main__':
    unittest.main()
