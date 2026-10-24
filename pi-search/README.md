# π Pi Search — find any number in the first billion digits of pi

Type any string of digits (a birthday, a phone number, `123456789`…) and the site
tells you **exactly which decimal place it starts at** in the first
1,000,000,000 digits of pi, shows the digits around it, counts how many times it
appears, and lets you step through every occurrence.

Also on the page:

- **Digit explorer**: jump to any decimal place and browse pi 1,000 digits at a time.
- **Digit frequency chart**: how often each digit 0–9 shows up across all billion digits.
- **Shareable links**: `http://localhost:8314/#8675309` opens straight to that search.

## Run it

Double-click **`Start-Mac.command`** (macOS) or **`Start-Windows.bat`** (Windows),
or from a terminal:

```bash
python3 start.py
```

It opens http://localhost:8314. Only Python 3.9+ is needed; there's nothing else to install.

**First run only:** the launcher gets the billion digits (~1 GB) and saves them to
`data/pi_digits.txt`. It downloads them from MIT's public mirror. If that fails, it
installs `gmpy2` and computes them on your machine (Chudnovsky formula). Computing
needs about 8 GB of free RAM and 30–90 minutes. For a quick try with fewer digits:

```bash
PI_DIGITS_COUNT=10000000 python3 start.py      # 10 million digits, ready in ~10 s
```

## How positions are counted

Position **1** is the first digit after the decimal point, the `1` in 3.**1**415….
Position **0** is the leading `3`, so searching `314159` gives position 0.

On average a *k*-digit string first appears around position 10^*k*. That means
nearly every string of 8 digits or fewer is in the first billion, while many
10+-digit strings aren't.

## How it works

| File | Role |
|---|---|
| `get_digits.py` | Downloads or computes the digits, checks them against known pi, and writes `data/pi_digits.txt` |
| `server.py` | Small HTTP server using only the standard library. It memory-maps the digit file, so a search scans the billion digits at C speed without loading them into RAM |
| `index.html` | The website (a single file) |
| `start.py` | One-command launcher |

API: `/api/search?q=…[&after=pos|&before=pos]`, `/api/count?q=…`,
`/api/digits?start=…&len=…`, `/api/info`.
