"""Kleiner HTTP-Server (nur Standardbibliothek) fuer Oberflaeche + Handy.

- Liefert die Web-Oberflaeche aus dem Ordner web/.
- JSON-API unter /api/... – jede Anfrage braucht den geheimen Code (Token),
  damit niemand anderes im WLAN deine Maus steuern kann.
- Standard: nur 127.0.0.1. Mit Handy-Fernbedienung: 0.0.0.0 (ganzes WLAN).
"""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 64 * 1024
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Unter Windows wuerde SO_REUSEADDR erlauben, dass zwei Instanzen denselben Port belegen
    allow_reuse_address = os.name != "nt"


def _is_loopback(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_loopback
    except ValueError:
        return False


class WebServer:
    def __init__(self, app, web_dir: str, port: int):
        self.app = app
        self.web_dir = os.path.realpath(web_dir)
        self.port = port
        self.host = "127.0.0.1"
        self._httpd: _HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ─── Start / Stopp ───────────────────────────────────
    def start(self, host: str = "127.0.0.1", try_ports: int = 10) -> None:
        last_err = None
        candidates = [self.port + i for i in range(try_ports)] + [0]
        for port in candidates:
            try:
                self._bind(host, port)
                return
            except OSError as e:
                last_err = e
        raise OSError(f"Kein freier Port gefunden: {last_err}")

    def _bind(self, host: str, port: int) -> None:
        httpd = _HTTPServer((host, port), self._handler_class())
        self._httpd = httpd
        self.host = host
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.25},
                                        name="http", daemon=True)
        self._thread.start()

    def rebind(self, host: str) -> str | None:
        """Wechselt zwischen nur-lokal und WLAN – gleicher Port. -> Fehlertext oder None."""
        with self._lock:
            if host == self.host:
                return None
            old_host, port = self.host, self.port
            self.stop()
            try:
                self._bind(host, port)
                return None
            except OSError as e:
                try:
                    self._bind(old_host, port)
                except OSError:
                    self.start(old_host)
                return str(e)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ─── Request-Handler ─────────────────────────────────
    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AutoClicker"
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # Konsole sauber halten
                pass

            # Helfer
            def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, obj, code: int = 200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _authorized(self, query) -> bool:
                token = self.headers.get("X-Token") or (query.get("t") or [""])[0]
                expected = server.app.token
                return bool(token) and secrets.compare_digest(token.encode(), expected.encode())

            @property
            def is_remote(self) -> bool:
                return not _is_loopback(self.client_address[0])

            # GET
            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.startswith("/api/"):
                    if url.path == "/api/ping":
                        return self._json(server.app.ping())
                    if not self._authorized(query):
                        return self._json({"error": "Falscher oder fehlender Code"}, 403)
                    if url.path == "/api/state":
                        since = (query.get("since") or ["-1"])[0]
                        client = (query.get("client") or [""])[0]
                        return self._json(server.app.state(self.is_remote, since, client))
                    if url.path == "/api/qr.svg":
                        svg = server.app.remote_qr_svg()
                        return self._send(200, svg.encode("utf-8"), "image/svg+xml")
                    return self._json({"error": "Unbekannt"}, 404)
                return self._static(url.path)

            do_HEAD = do_GET

            # POST
            def do_POST(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self.close_connection = True
                    return self._json({"error": "Zu groß"}, 413)
                raw = self.rfile.read(length) if length else b""
                if not url.path.startswith("/api/"):
                    return self._json({"error": "Unbekannt"}, 404)
                if not self._authorized(query):
                    return self._json({"error": "Falscher oder fehlender Code"}, 403)
                try:
                    body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                except ValueError:
                    return self._json({"error": "Ungültiges JSON"}, 400)
                if not isinstance(body, dict):
                    return self._json({"error": "Ungültige Daten"}, 400)
                name = url.path[len("/api/"):]
                try:
                    result = server.app.handle(name, body, remote=self.is_remote,
                                               client=(query.get("client") or [""])[0])
                except Exception as e:  # nie den Server abstuerzen lassen
                    return self._json({"error": f"Interner Fehler: {e}"}, 500)
                if result is None:
                    return self._json({"error": "Unbekannt"}, 404)
                code = 400 if isinstance(result, dict) and result.get("error") else 200
                return self._json(result, code)

            # Statische Dateien
            def _static(self, path: str):
                rel = "index.html" if path in ("", "/") else path.lstrip("/")
                full = os.path.realpath(os.path.join(server.web_dir, rel))
                ext = os.path.splitext(full)[1].lower()
                inside = full.startswith(server.web_dir + os.sep)
                if not inside or ext not in STATIC_TYPES or not os.path.isfile(full):
                    return self._send(404, b"Nicht gefunden", "text/plain; charset=utf-8")
                with open(full, "rb") as f:
                    data = f.read()
                cache = "max-age=86400" if ext in (".woff2", ".png") else "no-cache"
                ctype = STATIC_TYPES.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
                self._send(200, data, ctype, cache)

        return Handler
