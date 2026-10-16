"""Development server: the viewer app plus data bundles from one origin, with CORS and HTTP Range.

Layout served at http://host:port/
  /                      the viewer (packaged with the CLI); if the served folder is itself a built site
                         (has index.html) it is served as-is instead
  /datasets.json         the folder's own registry if present, else one generated from the bundles found
  /<bundle>/...          each bundle directory in the served folder (range requests supported)
  /assets/...            the viewer's static assets
"""
from __future__ import annotations

import contextlib
import json
import os
import posixpath
import re
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .registry import build_registry, find_bundles, packaged_app_dir

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeCORSHandler(SimpleHTTPRequestHandler):
    app_dir: Path | None = None
    data_dir: Path
    session: bool = False  # `spatialscape.show()`: answers /_api/ping and stores the viewer's lasso selections and regions
    _selections: dict[str, dict] = {}
    _regions: dict[str, dict] = {}
    _registry_cache: tuple[float, bytes] | None = None
    _registry_lock = threading.Lock()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges, ETag")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Timing-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter
        if os.environ.get("SSCAPE_SERVE_VERBOSE"):
            super().log_message(fmt, *args)

    # ---- routing: data folder first, then the packaged viewer
    def list_directory(self, path):
        """Only the root of a folder served without a viewer lists its bundles (there is nothing else to show
        there); inside bundles nothing is browsed, they are addressed through manifest.json."""
        if self.app_dir is None and Path(path).resolve() == self.data_dir.resolve():
            return super().list_directory(path)
        self.send_error(404, "no directory listings")
        return None

    def translate_path(self, path: str) -> str:
        rel = posixpath.normpath(path.split("?", 1)[0].split("#", 1)[0])
        data = Path(super().translate_path(rel))  # inside data_dir (SimpleHTTPRequestHandler blocks traversal)
        is_root = rel.strip("/") == ""
        if data.is_file() or (data.is_dir() and not is_root):
            return str(data)  # a bundle file, or a bundle folder listing
        if self.app_dir is not None:
            rel_clean = rel.lstrip("/") or "index.html"
            candidate = (self.app_dir / rel_clean).resolve()
            if candidate.is_relative_to(self.app_dir) and candidate.is_file():
                return str(candidate)  # the viewer at / and its assets
        return str(data)

    def do_GET(self):
        if self._is_registry_request():
            self._send_registry(head=False)
            return
        if self.session and self.path.startswith("/_api/"):
            self._api_get()
            return
        super().do_GET()

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        if not (self.session and route in ("/_api/selection", "/_api/regions")):
            self.send_error(405)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            doc = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(doc, dict):
                raise ValueError("body must be a JSON object")
            key = str(doc.get("dataset") or "")
        except (ValueError, TypeError):
            self.send_error(400)
            return
        if route == "/_api/selection":
            type(self)._selections[key] = {"version": doc.get("version", 0), "samples": doc.get("samples") or {}, "time": time.time()}
        else:
            type(self)._regions[key] = {"version": doc.get("version", 0), "groups": doc.get("groups") or [], "codes": doc.get("codes") or {}, "time": time.time()}
        self.send_response(204)
        self.end_headers()

    def _api_get(self) -> None:
        route, _, query = self.path.partition("?")
        if route == "/_api/ping":
            body = b'{"session": true}'
        elif route in ("/_api/selection", "/_api/regions"):
            key = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("d", "")
            if route == "/_api/selection":
                body = json.dumps(type(self)._selections.get(key) or {"version": 0, "samples": {}}).encode()
            else:
                body = json.dumps(type(self)._regions.get(key) or {"version": 0, "groups": [], "codes": {}}).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        if self._is_registry_request():
            self._send_registry(head=True)
            return
        super().do_HEAD()

    def _is_registry_request(self) -> bool:
        return self.path.split("?", 1)[0] == "/datasets.json" and not (self.data_dir / "datasets.json").exists()

    def _send_registry(self, *, head: bool) -> None:
        body = self._registry_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _registry_bytes(self) -> bytes:
        cls = type(self)
        with cls._registry_lock:
            now = time.time()
            if cls._registry_cache and now - cls._registry_cache[0] < 2.0:
                return cls._registry_cache[1]
            bundles = find_bundles(self.data_dir)
            doc = build_registry(
                bundles,
                url_for=lambda b, _id: b.name if b != self.data_dir else ".",
                title="spatialscape",
                intro=f"Bundles in {self.data_dir.name or self.data_dir}/ on this machine. Open any of them, or paste another bundle URL below.",
            )
            if self.session:
                doc["api"] = "/_api"  # the viewer posts lasso selections and regions here (spatialscape.show)
            body = json.dumps(doc).encode()
            cls._registry_cache = (now, body)
            return body

    # ---- byte ranges
    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        m = RANGE_RE.match(rng)
        if not m or "," in rng:  # multiple ranges: answer with the whole file (200), which every client accepts
            return super().send_head()
        size = os.path.getsize(path)
        start_s, end_s = m.groups()
        if start_s == "" and end_s == "":
            return super().send_head()
        if start_s == "":  # suffix range: last N bytes
            n = int(end_s)
            start, end = max(0, size - n), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
        if start >= size or end < start:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = open(path, "rb")  # noqa: SIM115 - streamed and closed by the handler
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return _LimitedFile(f, end - start + 1)


class _LimitedFile:
    def __init__(self, f, n):
        self.f, self.n = f, n

    def read(self, k=-1):
        if self.n <= 0:
            return b""
        k = self.n if k < 0 else min(k, self.n)
        data = self.f.read(k)
        self.n -= len(data)
        return data

    def close(self):
        self.f.close()


def make_server(directory: Path, port: int = 8787, host: str = "127.0.0.1", app_dir: Path | None = None, session: bool = False) -> ThreadingHTTPServer:
    """A ready-to-run server. `app_dir=None` means: use the packaged viewer unless `directory` is itself a built site.
    `session=True` adds the /_api routes `spatialscape.show()` uses to read lasso selections back."""
    directory = Path(directory).resolve()
    if (directory / "index.html").exists():
        app_dir = None  # a built site: serve it as-is
    elif app_dir is None:
        app_dir = packaged_app_dir()
    extensions = {**SimpleHTTPRequestHandler.extensions_map, ".json": "application/json", ".bw": "application/octet-stream", ".bed": "text/plain", "": "application/octet-stream"}
    handler = type("Handler", (RangeCORSHandler,), {"app_dir": app_dir, "data_dir": directory, "session": session, "_selections": {}, "_regions": {}, "extensions_map": extensions})
    factory = partial(handler, directory=str(directory))
    return ThreadingHTTPServer((host, port), factory)


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


def serve(directory: Path, port: int = 8787, host: str = "127.0.0.1", open_browser: bool = False, port_chosen: bool = False) -> None:
    """Start the server. With the default port, a busy port is skipped to the next free one; an explicit `--port` is honoured or refused."""
    if not _port_free(host, port):
        if port_chosen:
            raise OSError(f"port {port} is already in use; stop that server or pass another --port")
        wanted = port
        while not _port_free(host, port) and port < wanted + 20:
            port += 1
        if not _port_free(host, port):
            raise OSError(f"ports {wanted}-{port} are all in use; pass --port")
        print(f"port {wanted} is in use; using {port}", flush=True)
    httpd = make_server(directory, port=port, host=host)
    handler_cls = httpd.RequestHandlerClass.func  # type: ignore[attr-defined]
    url = f"http://{host}:{port}/"
    directory = Path(directory).resolve()
    n = len(find_bundles(directory))
    if handler_cls.app_dir is not None:
        print(f"viewer + {n} bundle(s) from {directory}\n  open {url}   (Ctrl-C stops the server)", flush=True)
    elif (directory / "index.html").exists():
        print(f"serving site {directory}\n  open {url}   (Ctrl-C stops the server)", flush=True)
    else:
        print(f"serving {n} bundle(s) from {directory} at {url} (no viewer in this install; open them in a hosted viewer with ?d=<url>)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
