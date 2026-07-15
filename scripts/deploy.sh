#!/usr/bin/env sh
# Deploy the IdeaL server on THIS machine (your existing VM). No SSH/remote logic —
# run it on the VM after cloning the repo. Builds and starts the container via
# docker compose, with SQLite persisted to ./data.
set -eu

# Move to the repo root (this script lives in scripts/).
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and set IDEAL_TOKEN:" >&2
  echo "  cp .env.example .env && \${EDITOR:-nano} .env" >&2
  exit 1
fi

# Refuse to deploy with the placeholder token still in place.
if grep -Eq '^IDEAL_TOKEN=(change-me-to-a-long-random-secret)?[[:space:]]*$' .env; then
  echo "ERROR: IDEAL_TOKEN is unset or still the placeholder in .env." >&2
  echo "  Set a long random secret, e.g.:  IDEAL_TOKEN=\$(openssl rand -hex 32)" >&2
  exit 1
fi

# Pick the compose command (v2 plugin preferred, v1 fallback).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "ERROR: docker compose (or docker-compose) not found." >&2
  exit 1
fi

mkdir -p data

echo "==> Building and starting IdeaL..."
# --env-file .env makes \${IDEAL_PORT} in the compose file resolve from .env.
$COMPOSE --env-file .env -f deploy/docker-compose.yml up -d --build

echo "==> Up. Check health with:  ./scripts/smoke-test.sh"
