#!/usr/bin/env python3
"""One-command launcher for Pi Search.

  1. gets the first billion digits of pi (first run only),
  2. starts the search server,
  3. opens the site in your browser.

Run it with:   python start.py       (Windows)
           or  python3 start.py      (Mac / Linux)

Environment overrides (optional):
  PI_DIGITS_COUNT=10000000   use fewer digits (much faster first run)
  PI_PORT=8314               change the port
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PI_PORT", "8314"))
URL = f"http://localhost:{PORT}"


def ensure_digits() -> None:
    path = os.path.join(HERE, "data", "pi_digits.txt")
    if os.path.exists(path):
        return
    count = os.environ.get("PI_DIGITS_COUNT", "1000000000")
    print("→ First run: fetching the digits of pi (about 1 GB, one time only)…\n")
    cmd = [sys.executable, os.path.join(HERE, "get_digits.py"), "--digits", count]
    if subprocess.call(cmd) == 0:
        return
    # Download failed and gmpy2 is missing: install it and compute instead.
    print("\n→ Installing gmpy2 so the digits can be computed locally…\n")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gmpy2"])
    subprocess.check_call(cmd + ["--compute"])


def open_browser_when_ready() -> None:
    time.sleep(1.5)
    print(f"\n★ Opening Pi Search at {URL}")
    print("  (If it doesn't open automatically, paste that address into your browser.)")
    print("  Press Ctrl+C in this window to stop.\n")
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def main() -> None:
    os.chdir(HERE)
    ensure_digits()
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    import server
    server.main(PORT)


if __name__ == "__main__":
    main()
