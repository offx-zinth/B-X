#!/usr/bin/env bash
#
# Business X-Ray — start the stack.
#
#   ./start.sh            # start (docker if available, otherwise native)
#   ./start.sh --native   # force native (skip docker)
#   ./start.sh --docker   # force docker compose
#   ./start.sh --stop     # stop everything
#   ./start.sh --status   # show status
#   ./start.sh --logs     # tail service logs
#   ./start.sh --reset    # drop the database volume and start fresh
#
# Configuration comes from the environment (or a .env file you create):
#   GEMINI_API_KEY   -> enables the live LLM (optional; app works without it)
#   LLM_PROVIDER     -> gemini (default) | openai | none
#   LLM_MODEL        -> e.g. gemma-4-31b-it
#   DATABASE_URL     -> defaults to the local Postgres below
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="auto"
case "${1:-}" in
  --native) MODE="native" ;;
  --docker) MODE="docker" ;;
  --stop)   MODE="stop" ;;
  --status) MODE="status" ;;
  --logs)   MODE="logs" ;;
  --reset)  MODE="reset" ;;
esac

# ---------------------------------------------------------------- config ----
[ -f .env ] && set -a && . ./.env && set +a

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
PY="${PYTHON:-python3.11}"
LOG_DIR="${LOG_DIR:-$ROOT/.run}"
export DATABASE_URL="${DATABASE_URL:-postgresql://xray_app:xrayapp@localhost:5432/xray}"
export JWT_SECRET="${JWT_SECRET:-dev-secret-local-check}"
export LLM_PROVIDER="${LLM_PROVIDER:-gemini}"
export LLM_MODEL="${LLM_MODEL:-gemma-4-31b-it}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$API_PORT}"

mkdir -p "$LOG_DIR"

c_ok()   { printf "\033[32m%s\033[0m\n" "$*"; }
c_warn() { printf "\033[33m%s\033[0m\n" "$*"; }
c_err()  { printf "\033[31m%s\033[0m\n" "$*"; }
c_info() { printf "\033[36m%s\033[0m\n" "$*"; }

port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

wait_http() { # url, seconds, label
  local url=$1 secs=$2 label=$3 i=0
  while [ $i -lt $secs ]; do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      c_ok "  $label is up"; return 0
    fi
    sleep 1; i=$((i+1))
  done
  c_err "  $label did NOT come up (see $LOG_DIR)"; return 1
}

# ----------------------------------------------------------------- stop ----
stop_all() {
  c_info "Stopping services…"
  pkill -f "uvicorn app.main:app" 2>/dev/null && c_ok "  api stopped"
  pkill -f "next start" 2>/dev/null
  pkill -f "next-server" 2>/dev/null
  sleep 1
  if command -v docker >/dev/null 2>&1; then
    docker compose stop >/dev/null 2>&1 && c_ok "  docker services stopped"
  fi
  c_ok "Done."
}

show_status() {
  local api_pids web_pids
  api_pids=$(pgrep -f "uvicorn app.main:app" 2>/dev/null | wc -l | tr -d ' ')
  web_pids=$(pgrep -f "next-server|next start" 2>/dev/null | wc -l | tr -d ' ')
  c_info "Processes:"
  printf "  api  : %s\n" "${api_pids:-0}"
  printf "  web  : %s\n" "${web_pids:-0}"
  if command -v docker >/dev/null 2>&1; then
    c_info "Containers:"
    docker compose ps --format '  {{.Name}}  {{.Status}}' 2>/dev/null
  fi
  c_info "Health:"
  curl -fsS "http://localhost:$API_PORT/health" 2>/dev/null && echo || c_warn "  api not responding"
}

tail_logs() {
  tail -f "$LOG_DIR/api.log" "$LOG_DIR/web.log" 2>/dev/null
}

# --------------------------------------------------------------- postgres ----
# Creates the non-superuser app role that RLS depends on: the POSTGRES_USER is
# a superuser and would bypass Row Level Security entirely.
ensure_pg_role() {
  local pw
  pw=$(docker exec business-xray-postgres-1 psql -U xray -d xray -tAc \
        "SELECT 1 FROM pg_roles WHERE rolname='xray_app'" 2>/dev/null)
  if [ "$pw" != "1" ]; then
    docker exec business-xray-postgres-1 psql -U xray -d xray -q -c \
      "CREATE ROLE xray_app LOGIN PASSWORD 'xrayapp' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS" \
      >/dev/null 2>&1
    docker exec business-xray-postgres-1 psql -U xray -d xray -q \
      -c "GRANT CONNECT ON DATABASE xray TO xray_app" \
      -c "GRANT USAGE, CREATE ON SCHEMA public TO xray_app" \
      -c "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO xray_app" \
      >/dev/null 2>&1
    for t in xray_store tenants users data_sources nodes edges node_states \
             formulas graph_versions scenarios simulation_runs audit_log reports; do
      docker exec business-xray-postgres-1 psql -U xray -d xray -q \
        -c "ALTER TABLE $t OWNER TO xray_app" >/dev/null 2>&1
    done
    c_ok "  created xray_app role (RLS-enforcing, non-superuser)"
  fi
}

# ---------------------------------------------------------------- docker ----
start_docker() {
  c_info "Starting via Docker…"
  if ! docker info >/dev/null 2>&1; then
    c_err "  Docker daemon is not running."; return 1
  fi
  docker compose up -d postgres
  local i=0
  while [ $i -lt 40 ]; do
    docker exec business-xray-postgres-1 pg_isready -U xray -d xray >/dev/null 2>&1 && break
    sleep 2; i=$((i+2))
  done
  ensure_pg_role
  c_info "Building images (first run downloads dependencies and can be slow)…"
  docker compose up -d --build api web || return 1
  wait_http "http://localhost:$API_PORT/health" 90 "api"
  wait_http "http://localhost:$WEB_PORT" 90 "web"
}

# ---------------------------------------------------------------- native ----
start_native() {
  c_info "Starting natively (Postgres stays in Docker)…"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker compose up -d postgres
    local i=0
    while [ $i -lt 40 ]; do
      docker exec business-xray-postgres-1 pg_isready -U xray -d xray >/dev/null 2>&1 && break
      sleep 2; i=$((i+2))
    done
    ensure_pg_role
  else
    c_warn "  Docker unavailable — relying on an external DATABASE_URL"
  fi

  if [ ! -d "$ROOT/apps/web/node_modules" ]; then
    c_info "Installing web dependencies…"
    (cd "$ROOT/apps/web" && npm install)
  fi
  if [ ! -d "$ROOT/apps/web/.next" ]; then
    c_info "Building web…"
    (cd "$ROOT/apps/web" && npm run build)
  fi

  c_info "Starting API…"
  (cd "$ROOT/apps/api" && setsid nohup "$PY" -m uvicorn app.main:app \
      --host 0.0.0.0 --port "$API_PORT" > "$LOG_DIR/api.log" 2>&1 < /dev/null &)
  wait_http "http://localhost:$API_PORT/health" 60 "api" || {
    c_err "--- api log tail ---"; tail -n 25 "$LOG_DIR/api.log"; return 1; }

  c_info "Starting web…"
  (cd "$ROOT/apps/web" && setsid nohup npm run start > "$LOG_DIR/web.log" 2>&1 < /dev/null &)
  wait_http "http://localhost:$WEB_PORT" 60 "web" || {
    c_err "--- web log tail ---"; tail -n 25 "$LOG_DIR/web.log"; return 1; }
}

# ----------------------------------------------------------------- seed ----
seed_demo() {
  local tok
  tok=$(curl -s -X POST "http://localhost:$API_PORT/auth/login" \
        -H 'Content-Type: application/json' \
        -d '{"email":"demo@acme.co","password":"secret123"}' 2>/dev/null \
      | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('token',''))" 2>/dev/null)
  if [ -z "$tok" ]; then
    tok=$(curl -s -X POST "http://localhost:$API_PORT/auth/signup" \
          -H 'Content-Type: application/json' \
          -d '{"org":"Acme Manufacturing","email":"demo@acme.co","password":"secret123"}' \
        | "$PY" -c "import sys,json;print(json.load(sys.stdin)['token'])" 2>/dev/null)
    c_ok "  created demo tenant"
  else
    c_ok "  using existing demo tenant"
  fi
  [ -z "$tok" ] && { c_warn "  could not authenticate to seed"; return 0; }

  curl -s -X POST "http://localhost:$API_PORT/ingest/seed" -H "Authorization: Bearer $tok" >/dev/null
  curl -s -X POST "http://localhost:$API_PORT/simulations/run" \
       -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' \
       -d '{"name":"Supplier ABC capacity = 0","changes":[{"target":"Supplier.capacity","value":0}],"duration_days":14}' \
    >/dev/null
  c_ok "  seeded Acme Manufacturing + supplier-failure scenario"
}

summary() {
  local ai
  ai=$(curl -s "http://localhost:$API_PORT/ai/status" 2>/dev/null)
  echo
  c_info "─────────────────────────────────────────────"
  c_ok   "  Web        http://localhost:$WEB_PORT"
  c_ok   "  API docs   http://localhost:$API_PORT/docs"
  c_info "  Health     http://localhost:$API_PORT/health"
  c_info "─────────────────────────────────────────────"
  c_info "  Login      demo@acme.co / secret123"
  [ -n "${GEMINI_API_KEY:-}" ] && c_info "  AI         live (${LLM_PROVIDER}/${LLM_MODEL})" \
                              || c_warn "  AI         deterministic (no GEMINI_API_KEY set)"
  echo "$ai" | grep -q '"live":true' && c_ok "  Provider   verified live" \
                                         || c_warn "  Provider   not live — copilot uses the deterministic engine"
  c_info "  Logs       $LOG_DIR"
  c_info "  Stop       ./start.sh --stop"
  c_info "─────────────────────────────────────────────"
}

# ----------------------------------------------------------------- main ----
case "$MODE" in
  stop)   stop_all; exit 0 ;;
  status) show_status; exit 0 ;;
  logs)   tail_logs; exit 0 ;;
  reset)
    c_warn "Resetting database volume…"
    docker compose down -v >/dev/null 2>&1
    c_ok "Database dropped."
    MODE="auto"
    ;;
esac

if [ "$MODE" = "auto" ]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    MODE="native"   # docker is up; native is fast and keeps Postgres in docker
  else
    MODE="docker"
  fi
fi

c_info "Mode: $MODE"
if [ "$MODE" = "docker" ]; then start_docker || exit 1; else start_native || exit 1; fi

seed_demo
summary
