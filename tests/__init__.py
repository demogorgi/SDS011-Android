# -*- coding: utf-8 -*-
"""Testpaket.

Leitet das Logging beim Import auf eine temporaere Datei um, damit
Testlaeufe nicht in output/logfile.txt schreiben.
"""

from __future__ import absolute_import

import os
import tempfile

import logging_util

_handle, _path = tempfile.mkstemp(prefix='sds011-tests-', suffix='.log')
os.close(_handle)
logging_util.configure(logfile=_path, level=3)
