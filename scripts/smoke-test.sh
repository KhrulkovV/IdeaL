#!/usr/bin/env sh
# End-to-end smoke test against a running IdeaL server (defaults to localhost).
# Reads IDEAL_PORT / IDEAL_TOKEN from .env, then does a health check and a real
# add -> export round-trip through the stdlib client. NOTE: it adds one idea named
# "Smoke test idea" to the store; run it against a fresh/dev store.
set -eu

cd "$(dirname "$0")/.."

[ -f .env ] || { echo "ERROR: .env not found (run ./scripts/deploy.sh first)." >&2; exit 1; }

PORT=$(grep -E '^IDEAL_PORT=' .env | head -n1 | cut -d= -f2- | tr -d '[:space:]')
TOKEN=$(grep -E '^IDEAL_TOKEN=' .env | head -n1 | cut -d= -f2-)
[ -n "${TOKEN:-}" ] || { echo "ERROR: IDEAL_TOKEN not set in .env." >&2; exit 1; }

IDEAL_URL="http://127.0.0.1:${PORT:-8000}"
export IDEAL_URL
export IDEAL_TOKEN="$TOKEN"
export IDEAL_AUTHOR="smoke-test"

HELPER="skills/ideal/scripts/ideal.py"

echo "==> health"
python3 "$HELPER" health

echo "==> add"
ID=$(printf '%s' \
  '{"title":"Smoke test idea","body":"Round-trip check written by smoke-test.sh."}' \
  | python3 "$HELPER" add)
echo "created: $ID"

echo "==> export contains the new idea"
if python3 "$HELPER" export | grep -q "$ID"; then
  echo "PASS: round-trip OK ($ID present in export)"
else
  echo "FAIL: $ID not found in export" >&2
  exit 1
fi
