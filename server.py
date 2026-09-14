# -*- coding: utf-8 -*-
"""Ein WSGI-Server, der sich von aussen beenden laesst.

bottle.WSGIRefServer legt zwar self.srv an, bietet aber keine Methode
zum Stoppen -- deshalb ein eigener Adapter. Der haengt nur an
wsgiref/socketserver aus der Standardbibliothek und funktioniert
dadurch mit jeder bottle-Version, die auf dem Geraet installiert ist.
"""

from __future__ import absolute_import

import socket
import sys
import threading

try:                                  # Python 3
    from socketserver import ThreadingMixIn
except ImportError:                   # Python 2
    from SocketServer import ThreadingMixIn

from bottle import ServerAdapter

from logging_util import write_log

# Erstes Byte eines TLS-ClientHello. Ein Browser, der https://
# zu dieser Anwendung spricht, schickt genau das.
_TLS_HANDSHAKE = b'\x16'


class StoppableWSGIRefServer(ServerAdapter):
    """Wie bottles WSGIRefServer, aber mit stop().

    serve_forever(poll_interval) schaut regelmaessig nach, ob shutdown()
    gerufen wurde. shutdown() muss aus einem ANDEREN Thread kommen als
    dem, der serve_forever() ausfuehrt, sonst blockiert es sich selbst.
    """

    POLL_INTERVAL = 0.5

    def __init__(self, host='127.0.0.1', port=8080, **options):
        ServerAdapter.__init__(self, host, port, **options)
        self.srv = None
        self.started = threading.Event()
        self._stopped = False

    def run(self, app):
        from wsgiref.simple_server import (make_server, WSGIRequestHandler,
                                           WSGIServer)

        class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            """Jede Anfrage in einem eigenen Thread.

            wsgiref bringt einen einfaedrigen Server mit: er bearbeitet
            eine Anfrage nach der anderen. Ein Browser oeffnet aber
            mehrere Verbindungen gleichzeitig (Seite, Skripte, die
            Statusabfrage im Sekundentakt), und eine langsame Anfrage
            legt dann alle uebrigen still -- bis hin zu abgelehnten
            Verbindungen.

            daemon_threads, damit eine haengende Anfrage das Beenden
            nicht blockiert.
            """
            daemon_threads = True
            # Ab Python 3.7 wartet server_close() sonst auf alle
            # Request-Threads; mit daemon_threads wollen wir das nicht.
            block_on_close = False

        quiet = self.quiet
        server_host = 'localhost' if self.host in ('0.0.0.0', '') else self.host
        server_port = self.port

        class FixedHandler(WSGIRequestHandler):

            # Ohne Zeitlimit bleibt eine angefangene Verbindung, die nie
            # eine vollstaendige Anfrage schickt, fuer immer offen.
            timeout = 30

            def address_string(self):
                # Keine Rueckwaertsaufloesung -- auf dem Handy sonst
                # sekundenlange Haenger pro Request.
                return self.client_address[0]

            def log_request(self, *args, **kwargs):
                if not quiet:
                    return WSGIRequestHandler.log_request(self, *args, **kwargs)

            def handle(self):
                # Ein TLS-Handshake beginnt mit 0x16. Genau den schickt
                # ein Browser, der https:// zu dieser Anwendung spricht --
                # etwa weil Chrome die Adresse selbsttaetig hochstuft.
                # Ohne diesen Zweig wartet der Server auf eine
                # Anfragezeile, die nie kommt: der Browser meldet "hat
                # eine ungueltige Antwort gesendet", die Konsole bleibt
                # stumm, und niemand kommt darauf.
                try:
                    first = self.connection.recv(1, socket.MSG_PEEK)
                except Exception:
                    first = b''
                if first[:1] == _TLS_HANDSHAKE:
                    hint = (u'HTTPS-Versuch von %s abgewiesen. Diese Anwendung '
                            u'spricht nur HTTP -- bitte http://%s:%d/ aufrufen '
                            u'(mit http:// davor).'
                            % (self.client_address[0], server_host, server_port))
                    write_log(0, hint)
                    try:
                        sys.stderr.write(hint + u'\n')
                    except Exception:
                        pass
                    self.close_connection = True
                    return
                return WSGIRequestHandler.handle(self)

        self.srv = make_server(self.host, self.port, app,
                               ThreadingWSGIServer, FixedHandler)
        # Bei port=0 vergibt das Betriebssystem einen freien Port.
        self.port = self.srv.server_port
        self.started.set()
        try:
            self.srv.serve_forever(poll_interval=self.POLL_INTERVAL)
        finally:
            try:
                self.srv.server_close()
            except Exception as exc:
                write_log(0, 'server_close fehlgeschlagen: {0}'.format(exc))
            write_log(1, 'Webserver beendet')

    def stop(self, timeout=5.0):
        """Beendet serve_forever(). Darf nicht aus dem Server-Thread
        gerufen werden."""
        if self._stopped:
            return True
        # Falls stop() kommt, bevor der Server ueberhaupt lauscht.
        if not self.started.wait(timeout):
            write_log(0, 'Webserver war nicht gestartet, nichts zu stoppen')
            return False
        self._stopped = True
        try:
            self.srv.shutdown()
            return True
        except Exception as exc:
            write_log(0, 'Webserver-Shutdown fehlgeschlagen: {0}'.format(exc))
            return False
