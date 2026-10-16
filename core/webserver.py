"""Tiny LAN file server so Apple TV apps (UHF, OneTV...) can load the playlist by URL."""
from __future__ import annotations

import functools
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class FileServer:
    def __init__(self):
        self._httpd = None
        self._thread = None
        self.port = None
        self.directory = None

    @property
    def running(self):
        return self._httpd is not None

    def start(self, directory, port=8765):
        self.stop()
        handler = functools.partial(_QuietHandler, directory=str(directory))
        self._httpd = ThreadingHTTPServer(("0.0.0.0", int(port)), handler)
        self.port = self._httpd.server_address[1]
        self.directory = str(directory)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None

    def base_url(self):
        return f"http://{lan_ip()}:{self.port}"
