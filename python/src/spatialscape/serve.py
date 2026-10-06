"""Dev server: static files with CORS and HTTP Range support (what zarr readers need)."""
from __future__ import annotations

import contextlib
import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeCORSHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
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

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        m = RANGE_RE.match(rng)
        if not m:
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
        if start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        end = min(end, size - 1)
        f = open(path, "rb")  # noqa: SIM115 - streamed and closed by the handler
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._range_len = end - start + 1
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


def serve(directory: Path, port: int = 8787, host: str = "127.0.0.1") -> None:
    handler = partial(RangeCORSHandler, directory=str(directory))
    handler.extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".json": "application/json", "": "application/octet-stream"}
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"serving {directory} at http://{host}:{port}/  (CORS + Range enabled)")
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
