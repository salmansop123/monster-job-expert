#!/usr/bin/env bash
# Start backend (FastAPI) and frontend (Vite) together. Ctrl+C stops both.
#
# Run from the repo root:
#   ./scripts/start-dev.sh

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Non-interactive shells often lack nvm/fnm PATH; load if present so `npm` is found.
if ! command -v npm >/dev/null 2>&1; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh"
  fi
  if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env)"
  fi
fi

BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"

cleanup() {
  local p
  for p in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
    if [[ -n "${p:-}" ]] && kill -0 "$p" 2>/dev/null; then
      kill "$p" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing backend virtualenv at $BACKEND_DIR/.venv" >&2
  echo "  cd \"$BACKEND_DIR\" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
  echo "Node.js/npm not found on PATH." >&2
  echo "" >&2
  echo "Install Node.js 20+ (includes npm), then re-run ./scripts/start-dev.sh:" >&2
  echo "  • Ubuntu:  sudo apt update && sudo apt install -y nodejs npm" >&2
  echo "  • Or:      https://nodejs.org" >&2
  echo "" >&2
  echo "Backend only (no UI for now):  cd backend && source .venv/bin/activate && python run_dev.py" >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies missing. Installing..." >&2
  (cd "$FRONTEND_DIR" && npm install)
fi

echo "Starting Chrome with CDP (if not already running) ..."
(
  cd "$BACKEND_DIR"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -c "
import asyncio

async def main() -> None:
    from app.config import settings
    from app.scraper.chrome_launcher import launch_chrome

    r = await launch_chrome(settings.chrome_cdp_url, settings.chrome_user_data_dir)
    print('Chrome CDP bootstrap:', r)

asyncio.run(main())
"
) || echo "Chrome bootstrap failed or was skipped — use Launch Chrome in the dashboard." >&2

echo "Starting API at http://127.0.0.1:${PORT:-8000} ..."
(
  cd "$BACKEND_DIR"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  exec python run_dev.py
) &
BACKEND_PID=$!

echo "Starting UI at http://localhost:5173 ..."
(
  cd "$FRONTEND_DIR"
  exec npm run dev
) &
FRONTEND_PID=$!

echo ""
echo "  API: ${PORT:-8000}  •  Docs: http://127.0.0.1:${PORT:-8000}/docs"
echo "  UI:  http://localhost:5173"
echo "  Press Ctrl+C to stop both."
echo ""

wait
