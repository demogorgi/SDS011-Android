# -*- coding: utf-8 -*-
"""Baut den Ordner fuers Handy aus dem letzten Commit.

Ergebnis: SDS011-Android-qpython2/SDS011-Android/ -- diesen Ordner so aufs
Handy kopieren, dass main.py unter qpython/projects/SDS011-Android/ liegt
(QPython 3L: projects3). Enthalten sind alle Programmdateien ausser
bluetooth_desktop.py (nur PC), views/, static/, bottle.py aus der
installierten bottle-Version und tools/LIESMICH.txt.

Gebaut wird aus HEAD, nicht aus dem Arbeitsverzeichnis: der Ordner passt
also immer zu einem Commit. Die Git-Hooks in .githooks/ rufen das Skript
nach jedem Commit, Merge, Checkout und Rebase auf (einmalig einschalten:
git config core.hooksPath .githooks).

Der Ordner wird jedes Mal neu erzeugt -- Aenderungen darin gehen verloren.

Aufruf: python tools/build_phone.py [--quiet]
"""

from __future__ import print_function

import io
import os
import shutil
import subprocess
import sys
import tarfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_ROOT = os.path.join(REPO, 'SDS011-Android-qpython2')
TARGET = os.path.join(TARGET_ROOT, 'SDS011-Android')
# Laeuft nur am PC; auf dem Handy uebernimmt transport.py.
EXCLUDE = {'bluetooth_desktop.py'}


def _git(*args):
    return subprocess.check_output(('git', '-C', REPO) + args)


def _runtime_paths():
    """Alle versionierten Dateien, die auf dem Handy gebraucht werden."""
    paths = []
    for line in _git('ls-tree', '-r', '--name-only', 'HEAD').decode('utf-8').splitlines():
        top_level_py = '/' not in line and line.endswith('.py')
        if (top_level_py and line not in EXCLUDE) or line.startswith(('views/', 'static/')):
            paths.append(line)
    return paths


def build(quiet=False):
    paths = _runtime_paths()
    archive = _git('archive', '--format=tar', 'HEAD', *paths)

    # Nur den erzeugten Unterordner loeschen, nie etwas anderes.
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    os.makedirs(TARGET)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(TARGET)

    shutil.copy(os.path.join(REPO, 'tools', 'LIESMICH.txt'), TARGET)
    try:
        import bottle
        shutil.copy(bottle.__file__.replace('.pyc', '.py'), TARGET)
        bottle_note = 'bottle ' + bottle.__version__
    except ImportError:
        bottle_note = 'OHNE bottle.py (pip install bottle)'

    if not quiet:
        head = _git('log', '-1', '--format=%h %s').decode('utf-8').strip()
        print('Handy-Ordner gebaut: {0}'.format(os.path.relpath(TARGET, REPO)))
        print('  Stand {0}, {1} Dateien, {2}'.format(head, len(paths), bottle_note))


if __name__ == '__main__':
    build(quiet='--quiet' in sys.argv)
