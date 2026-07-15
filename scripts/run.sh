#!/usr/bin/env sh
# Run the IdeaL server WITHOUT Docker and WITHOUT root — just Python + uvicorn in
# userspace. Use this when you can't install Docker (e.g. no sudo).
#
#   ./scripts/run.sh start     # set up deps (once) and start in the background
#   ./scripts/run.sh stop      # stop it
#   ./scripts/run.sh status    # is it running?
#   ./scripts/run.sh logs      # follow the log
#
# SQLite persists to ./data/ideal.sqlite; logs -> ./data/ideal.log; PID -> ./data/ideal.pid.
set -eu

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DATA_DIR="$ROOT/data"
PID_FILE="$DATA_DIR/ideal.pid"
LOG_FILE="$DATA_DIR/ideal.log"
VENV="$ROOT/.venv"

# --- helpers -----------------------------------------------------------------

load_env() {
  if [ ! -f "$ROOT/.env" ]; then
    echo "ERROR: .env not found. Run:  cp .env.example .env  and set IDEAL_TOKEN." >&2
    exit 1
  fi
  # Refuse to start with the placeholder token still in place.
  if grep -Eq '^IDEAL_TOKEN=(change-me-to-a-long-random-secret)?[[:space:]]*$' "$ROOT/.env"; then
    echo "ERROR: IDEAL_TOKEN is unset or still the placeholder in .env." >&2
    echo "  Set a long random secret, e.g.:  IDEAL_TOKEN=\$(openssl rand -hex 32)" >&2
    exit 1
  fi
  # Export each KEY=VALUE from .env, taking the value literally (docker env_file style).
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    case "$line" in *=*) : ;; *) continue ;; esac
    key=${line%%=*}
    val=${line#*=}
    export "$key=$val"
  done < "$ROOT/.env"
  : "${IDEAL_PORT:=8000}"
  # On the host (no container), keep SQLite inside the repo's data/ dir, not /data.
  IDEAL_DB_PATH="$DATA_DIR/ideal.sqlite"
  export IDEAL_PORT IDEAL_DB_PATH
}

pybin() {
  if [ -x "$VENV/bin/python" ]; then echo "$VENV/bin/python"; else echo "python3"; fi
}

ensure_deps() {
  if [ -x "$VENV/bin/python" ]; then return; fi
  echo "==> Setting up Python dependencies (first run only)..."
  if python3 -m venv "$VENV" 2>/dev/null; then
    "$VENV/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$VENV/bin/python" -m pip install -r "$ROOT/server/requirements.txt"
  else
    echo "WARN: 'python3 -m venv' failed (the python3-venv package may be missing," >&2
    echo "      which would need root). Falling back to 'pip install --user'." >&2
    rm -rf "$VENV"
    python3 -m pip install --user -r "$ROOT/server/requirements.txt"
  fi
}

running() {
  [ -f "$PID_FILE" ] || return 1
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null
}

# --- commands ----------------------------------------------------------------

start() {
  load_env
  mkdir -p "$DATA_DIR"
  if running; then
    echo "Already running (PID $(cat "$PID_FILE")) on port ${IDEAL_PORT}."
    exit 0
  fi
  ensure_deps
  PY="$(pybin)"
  echo "==> Starting IdeaL on 0.0.0.0:${IDEAL_PORT} (no Docker, no root)..."
  # uvicorn imports app.py from server/; IDEAL_DB_PATH is absolute so cwd is safe.
  cd "$ROOT/server"
  nohup "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$IDEAL_PORT" \
    >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  cd "$ROOT"

  sleep 1
  if running; then
    echo "Started (PID $(cat "$PID_FILE")). Logs: ./data/ideal.log"
    echo "Check:  curl -s http://127.0.0.1:${IDEAL_PORT}/health"
    echo "Reachable from elsewhere only if port ${IDEAL_PORT} is open in the VM firewall."
  else
    echo "ERROR: server exited immediately. Recent log:" >&2
    tail -n 25 "$LOG_FILE" >&2 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop() {
  if running; then
    pid=$(cat "$PID_FILE")
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Stopped (PID $pid)."
  else
    rm -f "$PID_FILE"
    echo "Not running."
  fi
}

status() {
  if running; then
    echo "running (PID $(cat "$PID_FILE"))"
  else
    echo "not running"
  fi
}

logs() {
  [ -f "$LOG_FILE" ] || { echo "No log yet at $LOG_FILE"; exit 0; }
  tail -n 50 -f "$LOG_FILE"
}

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  restart) stop; start ;;
  status) status ;;
  logs)   logs ;;
  *) echo "usage: $0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
esac
