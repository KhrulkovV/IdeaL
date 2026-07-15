#!/usr/bin/env sh
# Pull the latest code and restart the running IdeaL server, in place.
# For the no-Docker / conda deployment (scripts/run.sh). Run it ON the VM,
# from the repo, with your env activated:
#
#   conda activate <your-env>
#   ./scripts/update.sh
#
# Data in ./data (SQLite) is untouched — this only swaps code and restarts.
set -eu

cd "$(dirname "$0")/.."

echo "==> Fetching latest code..."
if [ -d .git ]; then
  git pull --ff-only
else
  echo "NOTE: not a git checkout; skipping pull (restarting current code)." >&2
fi

echo "==> Restarting server..."
./scripts/run.sh restart

echo "==> Done. Health:"
PORT=$(grep -E '^IDEAL_PORT=' .env 2>/dev/null | tail -n1 | cut -d= -f2)
PORT="${PORT:-8000}"
# Give uvicorn a moment, then report health (curl is optional).
if command -v curl >/dev/null 2>&1; then
  curl -sS "http://127.0.0.1:${PORT}/health" || true
  echo
fi
