#!/usr/bin/env python3
"""Pi Search server — finds any string of digits inside the first billion digits of pi.

Standard library only. The digit file is memory-mapped, so searching a billion
digits never loads them all into RAM and a typical lookup takes well under a second.

Positions are decimal places: position 1 is the "1" in 3.1415..., and position 0
is the leading "3" (so a search for "314159" is found at position 0).
"""
from __future__ import annotations

import json
import mmap
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITS_PATH = os.environ.get("PI_DIGITS", os.path.join(HERE, "data", "pi_digits.txt"))
STATS_PATH = DIGITS_PATH + ".stats.json"
INDEX_PATH = os.path.join(HERE, "index.html")

MAX_QUERY = 100
MAX_SLICE = 20_000
CONTEXT = 40
CHUNK = 1 << 24  # 16 MB


class Pi:
    def __init__(self, path: str) -> None:
        self._file = open(path, "rb")
        self.data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self.size = len(self.data)
        self._counts: dict[str, int] = {}
        self._count_lock = threading.Lock()
        self.stats: dict | None = None

    # --- digits ------------------------------------------------------------
    def slice(self, start: int, length: int) -> str:
        """Digits at positions start .. start+length-1 (position 0 is the "3")."""
        start = max(0, start)
        end = min(self.size, start + length - 1)
        if start == 0:
            return "3" + self.data[0:end].decode()
        return self.data[start - 1 : end].decode()

    # --- search ------------------------------------------------------------
    def find(self, q: str, after: int = -1) -> int | None:
        """First position > after where q begins, or None."""
        if after < 0 and q[0] == "3" and self.data[: len(q) - 1] == q[1:].encode():
            return 0
        idx = self.data.find(q.encode(), max(after, 0))
        return None if idx < 0 else idx + 1

    def find_before(self, q: str, before: int) -> int | None:
        """Last position < before where q begins, or None."""
        if before <= 1:
            return None
        idx = self.data.rfind(q.encode(), 0, before - 1 + len(q) - 1)
        if idx >= 0:
            return idx + 1
        return 0 if self.find(q) == 0 else None

    def count(self, q: str) -> int:
        with self._count_lock:
            if q in self._counts:
                return self._counts[q]
        needle = q.encode()
        n = len(needle)
        borders = any(needle[:k] == needle[-k:] for k in range(1, n))
        total = 0
        if borders:
            # Self-overlapping pattern (e.g. "1212"): bytes.count would skip
            # overlapping matches, so walk them one by one.
            i = self.data.find(needle)
            while i >= 0:
                total += 1
                i = self.data.find(needle, i + 1)
        else:
            for s in range(0, self.size, CHUNK):
                # Window extends n-1 bytes past the chunk so every match that
                # *starts* inside the chunk is counted exactly once.
                total += self.data[s : s + CHUNK + n - 1].count(needle)
        if self.find(q) == 0:
            total += 1  # match beginning on the leading "3"
        with self._count_lock:
            self._counts[q] = total
        return total

    # --- whole-file statistics ----------------------------------------------
    def load_stats(self) -> None:
        try:
            with open(STATS_PATH) as fh:
                cached = json.load(fh)
            if cached.get("size") == self.size:
                self.stats = cached
                return
        except (OSError, ValueError):
            pass
        freq = [0] * 10
        for s in range(0, self.size, CHUNK):
            block = self.data[s : s + CHUNK]
            for d in range(10):
                freq[d] += block.count(b"0123456789"[d : d + 1])
        self.stats = {"size": self.size, "frequency": freq}
        try:
            with open(STATS_PATH, "w") as fh:
                json.dump(self.stats, fh)
        except OSError:
            pass


PI: Pi | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "PiSearch/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                with open(INDEX_PATH, "rb") as fh:
                    body = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/info":
                self.send_json({"digits": PI.size, "stats": PI.stats})
            elif url.path == "/api/search":
                self.search(params)
            elif url.path == "/api/count":
                q = self.query(params)
                if q is None:
                    return
                t = time.perf_counter()
                n = PI.count(q)
                self.send_json({"query": q, "count": n, "ms": round((time.perf_counter() - t) * 1000, 1)})
            elif url.path == "/api/digits":
                start = int(params.get("start", 0))
                length = min(int(params.get("len", 1000)), MAX_SLICE)
                if start < 0 or start > PI.size or length < 1:
                    return self.send_json({"error": "position out of range"}, 400)
                self.send_json({"start": start, "digits": PI.slice(start, length)})
            else:
                self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError:
            self.send_json({"error": "bad number in request"}, 400)

    def query(self, params: dict) -> str | None:
        q = "".join(c for c in params.get("q", "") if c.isdigit())
        if not q:
            self.send_json({"error": "type some digits to search for"}, 400)
            return None
        if len(q) > MAX_QUERY:
            self.send_json({"error": f"searches are limited to {MAX_QUERY} digits"}, 400)
            return None
        return q

    def search(self, params: dict) -> None:
        q = self.query(params)
        if q is None:
            return
        t = time.perf_counter()
        if "before" in params:
            pos = PI.find_before(q, int(params["before"]))
        else:
            pos = PI.find(q, int(params.get("after", -1)))
        ms = round((time.perf_counter() - t) * 1000, 1)
        payload = {"query": q, "position": pos, "ms": ms, "searched": PI.size}
        if pos is not None:
            start = max(0, pos - CONTEXT)
            payload["context"] = {"start": start, "digits": PI.slice(start, pos - start + len(q) + CONTEXT)}
        self.send_json(payload)


def main(port: int | None = None, host: str = "127.0.0.1") -> None:
    global PI
    if not os.path.exists(DIGITS_PATH):
        raise SystemExit("No digits yet — run:  python3 get_digits.py")
    PI = Pi(DIGITS_PATH)
    threading.Thread(target=PI.load_stats, daemon=True).start()
    port = port or int(os.environ.get("PI_PORT", "8314"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"  π  serving {PI.size:,} digits at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main(host=os.environ.get("PI_HOST", "127.0.0.1"))
