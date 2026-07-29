#!/usr/bin/env bash
# Launch the stock scanner / trade-ideas dashboard.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${SCANNER_PORT:-8000}"
HOST="${SCANNER_HOST:-0.0.0.0}"

echo "→ Stock Scanner starting on http://localhost:${PORT}"
echo "  provider: ${SCANNER_PROVIDER:-auto} (set SCANNER_PROVIDER=simulated to force offline demo)"

exec python3 -m uvicorn backend.main:app --host "$HOST" --port "$PORT" "$@"
