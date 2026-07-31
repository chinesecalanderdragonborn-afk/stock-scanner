#!/usr/bin/env python3
"""One-command launcher for the Stock Scanner dashboard.

Does everything for you:
  1. installs any missing Python packages,
  2. starts the server,
  3. opens the dashboard in your browser.

Run it with:   python start.py       (Windows)
           or  python3 start.py      (Mac / Linux)

Environment overrides (optional):
  SCANNER_PROVIDER=simulated   force the offline demo (no internet needed)
  SCANNER_PORT=8000            change the port
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser

PORT = int(os.environ.get("SCANNER_PORT", "8000"))
URL = f"http://localhost:{PORT}"


def ensure_dependencies() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import yfinance  # noqa: F401
        return
    except ImportError:
        pass
    print("→ Installing required packages (first run only)…\n")
    req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req])
    print("\n→ Packages installed.\n")


def open_browser_when_ready() -> None:
    # Give the server a moment to bind, then open the browser once.
    time.sleep(2.5)
    print(f"\n★ Opening the dashboard at {URL}")
    print("  (If it doesn't open automatically, paste that address into your browser.)")
    print("  Press Ctrl+C in this window to stop.\n")
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ensure_dependencies()

    provider = os.environ.get("SCANNER_PROVIDER", "auto")
    print("=" * 60)
    print("  STOCK SCANNER — Trade Ideas Dashboard")
    print(f"  data source : {provider}  (live Yahoo, falls back to simulator)")
    print(f"  address     : {URL}")
    print("=" * 60)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=PORT,
                access_log=False, log_level="info")


if __name__ == "__main__":
    main()
