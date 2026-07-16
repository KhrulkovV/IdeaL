#!/usr/bin/env sh
# Run the IdeaL server WITHOUT Docker and WITHOUT root, inside your ACTIVE conda
# env (or any active Python env). No virtualenv is created — dependencies install
# into the currently-active interpreter. Activate your env first, e.g.:
#
#   conda activate <your-env>
#   ./scripts/run.sh start
#
# Commands:  start (default) | stop | restart | status | logs
# Override the interpreter with IDEAL_PYTHON=/path/to/python if you'd rather not
# activate (e.g. IDEAL_PYTHON=$(conda run -n myenv which python)).
#
# SQLite -> ./data/ideal.sqlite ; logs -> ./data/ideal.log ; PID -> ./data/ideal.pid.
set -eu

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DATA_DIR="$ROOT/data"
PID_FILE="$DATA_DIR/ideal.pid"
LOG_FILE="$DATA_DIR/ideal.log"
PY="${IDEAL_PYTHON:-python3}"

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
  : "${IDEAL_HOST:=0.0.0.0}"
  # On the host (no container), keep SQLite inside the repo's data/ dir, not /data.
  IDEAL_DB_PATH="$DATA_DIR/ideal.sqlite"
  export IDEAL_PORT IDEAL_HOST IDEAL_DB_PATH
}

# Is server-side semantic search enabled? Mirrors config.py's _as_bool over the
# IDEAL_RAG_ENABLED value exported by load_env (default true).
rag_enabled() {
  case "$(printf '%s' "${IDEAL_RAG_ENABLED:-true}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) echo 1 ;;
    *) echo 0 ;;
  esac
}

ensure_deps() {
  if ! command -v "$PY" >/dev/null 2>&1 && [ ! -x "$PY" ]; then
    echo "ERROR: Python interpreter '$PY' not found. Activate your conda env, or set IDEAL_PYTHON." >&2
    exit 1
  fi
  PREFIX=$("$PY" -c 'import sys; print(sys.prefix)' 2>/dev/null || echo "?")
  if [ -z "${CONDA_PREFIX:-}" ] && [ "$PY" = "python3" ]; then
    echo "NOTE: no conda env appears active; using system python3 ($PREFIX)." >&2
    echo "      Activate your env first, or set IDEAL_PYTHON, if that's not intended." >&2
  fi

  if [ "$(rag_enabled)" = 1 ]; then
    # Web + semantic-search deps.
    if "$PY" -c 'import fastapi, uvicorn, sentence_transformers, numpy' >/dev/null 2>&1; then
      echo "==> Using Python env: $PREFIX (deps present)"
      return
    fi
    # Install torch FIRST so the huge default (CUDA) wheel isn't pulled in
    # transitively by sentence-transformers. Default = CPU wheel; override with
    # IDEAL_TORCH_INDEX_URL (empty string = pip's default/GPU index), or just
    # pre-install torch via conda (e.g. `conda install pytorch cpuonly -c pytorch`)
    # and this step is skipped.
    if ! "$PY" -c 'import torch' >/dev/null 2>&1; then
      idx="${IDEAL_TORCH_INDEX_URL-https://download.pytorch.org/whl/cpu}"
      if [ -n "$idx" ]; then
        echo "==> Installing CPU torch ($idx) into: $PREFIX"
        "$PY" -m pip install torch --index-url "$idx"
      else
        echo "==> Installing torch (pip default index) into: $PREFIX"
        "$PY" -m pip install torch
      fi
    fi
    echo "==> Installing dependencies (incl. sentence-transformers) into: $PREFIX"
    "$PY" -m pip install -r "$ROOT/server/requirements.txt"
  else
    # Web deps only — no heavy ML stack when IDEAL_RAG_ENABLED is false. numpy is
    # still required: app.py imports rag_engine (which imports numpy) unconditionally.
    if "$PY" -c 'import fastapi, uvicorn, numpy' >/dev/null 2>&1; then
      echo "==> Using Python env: $PREFIX (deps present)"
      return
    fi
    echo "==> Installing core dependencies into: $PREFIX"
    "$PY" -m pip install fastapi "uvicorn[standard]" numpy
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
  echo "==> Starting IdeaL on ${IDEAL_HOST}:${IDEAL_PORT} (no Docker, no root)..."
  # uvicorn imports app.py from server/; IDEAL_DB_PATH is absolute so cwd is safe.
  cd "$ROOT/server"
  nohup "$PY" -m uvicorn app:app --host "$IDEAL_HOST" --port "$IDEAL_PORT" \
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
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
  logs)    logs ;;
  *) echo "usage: $0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
esac
