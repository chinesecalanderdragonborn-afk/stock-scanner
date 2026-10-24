#!/usr/bin/env python3
"""Fetch (or compute) the digits of pi that the search site uses.

The digits are stored *after* the decimal point, one ASCII digit per byte, in
data/pi_digits.txt — so byte 0 is the 1st decimal digit ("1" of 3.1415...).

Usage:
    python3 get_digits.py                  # 1 billion digits (download, else compute)
    python3 get_digits.py --digits 10000000  # a smaller set, computed in seconds
    python3 get_digits.py --compute        # skip the download and compute locally

Downloading needs ~1 GB of disk. Computing 1 billion digits needs gmpy2
(`pip install gmpy2`), ~8 GB of free RAM and somewhere between 30 and 90 minutes.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT_PATH = os.path.join(DATA_DIR, "pi_digits.txt")
ONE_BILLION = 1_000_000_000

# Public mirrors of the first billion decimal digits ("3.1415...").
MIRRORS = [
    "https://stuff.mit.edu/afs/sipb/contrib/pi/pi-billion.txt",
]

# First 50 decimals, used to sanity-check every source.
CHECK = "14159265358979323846264338327950288419716939937510"


def progress(done: int, total: int, started: float, label: str) -> None:
    pct = done / total * 100 if total else 0
    rate = done / max(time.time() - started, 1e-9) / 1e6
    sys.stdout.write(f"\r  {label}: {done:,} / {total:,} ({pct:5.1f}%)  {rate:6.1f} M/s ")
    sys.stdout.flush()


def download(url: str, digits: int, tmp: str) -> bool:
    print(f"→ Downloading from {url}")
    try:
        resp = urllib.request.urlopen(url, timeout=30)
    except Exception as exc:  # network blocked, mirror down, ...
        print(f"  could not reach mirror: {exc}")
        return False
    started = time.time()
    written = 0
    head = b""
    with open(tmp, "wb") as out:
        while written < digits:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            if not head:  # strip the leading "3."
                chunk = chunk.lstrip()
                if chunk.startswith(b"3."):
                    chunk = chunk[2:]
                head = chunk[:50]
                if head.decode("ascii", "replace") != CHECK[: len(head)]:
                    print("  mirror returned something that isn't pi; skipping it")
                    return False
            if not chunk.isdigit():  # drop newlines/whitespace some mirrors include
                chunk = bytes(c for c in chunk if 48 <= c <= 57)
            chunk = chunk[: digits - written]
            out.write(chunk)
            written += len(chunk)
            progress(written, digits, started, "downloaded")
    print()
    if written < digits:
        print(f"  mirror only had {written:,} digits")
        return False
    return True


def compute(digits: int, tmp: str) -> None:
    """Chudnovsky series with binary splitting, on GMP integers via gmpy2."""
    try:
        import gmpy2
        from gmpy2 import mpz
    except ImportError:
        sys.exit("Computing needs gmpy2:  pip install gmpy2   (then re-run this script)")

    print(f"→ Computing {digits:,} digits of pi locally (Chudnovsky + binary splitting)")
    started = time.time()
    guard = 20
    n = digits + guard
    terms = int(n / 14.181647462725477) + 2
    C3_24 = mpz(640320) ** 3 // 24

    def split(a: int, b: int):
        if b - a == 1:
            if a == 0:
                p = q = mpz(1)
            else:
                p = mpz(6 * a - 5) * (2 * a - 1) * (6 * a - 1)
                q = mpz(a) * a * a * C3_24
            t = p * (13591409 + 545140134 * a)
            return p, q, (-t if a & 1 else t)
        m = (a + b) // 2
        p1, q1, t1 = split(a, m)
        p2, q2, t2 = split(m, b)
        return p1 * p2, q1 * q2, t1 * q2 + p1 * t2

    _, q, t = split(0, terms)
    print(f"  series summed ({terms:,} terms) in {time.time() - started:.0f}s")
    one = mpz(10) ** n
    sqrt_c = gmpy2.isqrt(10005 * one * one)
    pi = (q * 426880 * sqrt_c) // t
    del q, t, sqrt_c
    print(f"  division + square root done in {time.time() - started:.0f}s")
    text = pi.digits(10)
    del pi
    if not text.startswith("3" + CHECK[:20]):
        sys.exit("internal error: computed value is not pi")
    with open(tmp, "w") as out:
        out.write(text[1 : digits + 1])
    print(f"  finished in {time.time() - started:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digits", type=int, default=ONE_BILLION, help="how many decimal digits (default 1,000,000,000)")
    ap.add_argument("--compute", action="store_true", help="skip downloading and compute locally")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(OUT_PATH) and os.path.getsize(OUT_PATH) >= args.digits:
        print(f"✓ {OUT_PATH} already has {os.path.getsize(OUT_PATH):,} digits — nothing to do.")
        return

    tmp = OUT_PATH + ".part"
    ok = False
    if not args.compute and args.digits <= ONE_BILLION:
        ok = any(download(url, args.digits, tmp) for url in MIRRORS)
    if not ok:
        compute(args.digits, tmp)
    os.replace(tmp, OUT_PATH)
    print(f"✓ Saved {os.path.getsize(OUT_PATH):,} digits to {OUT_PATH}")


if __name__ == "__main__":
    main()
