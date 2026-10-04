#!/usr/bin/env bash
# air-harness — one command to run the whole product and see where everything is.
#
#   ./run.sh               build + start the stack (+ Prometheus), smoke-test it, print URLs and next steps
#   ./run.sh --check       ... then run the harness: selftest, fast loop, integration (unit + contract)
#   ./run.sh --full        ... --check plus the pipeline stage (eval, alert rules)
#   ./run.sh --llm         also start the local LLM (Ollama) and pull LLM_MODEL: review agent and rag-web Chat
#   ./run.sh --console     ... and start the web console (API playground, harness runs, agent tasks)
#   ./run.sh --urls        print URLs and service status of a running stack, start nothing
#   ./run.sh --down        stop the stack (data in DATA_DIR is kept)
#   ./run.sh --help        this text; ./help.sh for the full guide
#
# Options combine: ./run.sh --llm --full. Add --no-observability to skip Prometheus.
set -uo pipefail
cd "$(dirname "$0")"

# ------------------------------------------------------------------ output
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else B=; DIM=; G=; Y=; R=; C=; N=; fi
step=0
title() { step=$((step + 1)); printf '\n%s[%d] %s%s\n' "$B" "$step" "$1" "$N"; }
ok()    { printf '  %s✔%s %s\n' "$G" "$N" "$1"; }
warn()  { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
fail()  { printf '  %s✘%s %s\n' "$R" "$N" "$1"; }
die()   { fail "$1"; [ -n "${2:-}" ] && printf '    %s\n' "$2"; exit 1; }
run()   { printf '  %s$ %s%s\n' "$DIM" "$*" "$N"; "$@"; }

# ------------------------------------------------------------------ options
CHECK=0 FULL=0 LLM=0 OBS=1 CONSOLE=0 MODE=up HOST_OLLAMA=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --full) CHECK=1; FULL=1 ;;
    --llm) LLM=1 ;;
    --console) CONSOLE=1 ;;
    --no-observability) OBS=0 ;;
    --urls|--status) MODE=urls ;;
    --down|--stop) MODE=down ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $arg" "see ./run.sh --help" ;;
  esac
done

# ------------------------------------------------------------------ configuration (.env overrides defaults)
env_value() {   # env_value NAME DEFAULT → value from the environment, else .env, else DEFAULT
  local v="${!1:-}"
  if [ -z "$v" ] && [ -f .env ]; then
    v=$(sed -n "s/^[[:space:]]*$1=\([^#]*\).*/\1/p" .env | tail -1 | sed 's/[[:space:]]*$//')
  fi
  printf '%s' "${v:-$2}"
}
HOST=$(env_value PUBLIC_HOST localhost)
GATEWAY_PORT=$(env_value GATEWAY_PORT 8080)
WEB_PORT=$(env_value WEB_PORT 8081)
PROMETHEUS_PORT=$(env_value PROMETHEUS_PORT 9090)
OLLAMA_PORT=$(env_value OLLAMA_PORT 11434)
CONSOLE_PORT=$(env_value CONSOLE_PORT 8090)
CONSOLE_URL="http://127.0.0.1:$CONSOLE_PORT"
LLM_MODEL=$(env_value LLM_MODEL qwen3:8b)
DATA_DIR=$(env_value DATA_DIR /var/tmp/air-harness)
API="http://$HOST:$GATEWAY_PORT"

running() { docker compose --profile observability --profile local-llm ps --status running --services 2>/dev/null | grep -qx "$1"; }

# ------------------------------------------------------------------ URLs + next steps
print_urls() {
  printf '\n%sAccessible URLs%s\n' "$B" "$N"
  if running gateway; then
    printf '  %-26s %s%s%s\n' "Web portal (rag-web)" "$C" "http://$HOST:$WEB_PORT" "$N  analyze · search · graph · chat · write"
    printf '  %-26s %s%s%s\n' "Public API" "$C" "$API" "$N  (opens the docs)"
    printf '  %-26s %s%s%s\n' "API docs (Swagger UI)" "$C" "$API/docs" "$N"
    printf '  %-26s %s%s%s\n' "API docs (ReDoc)" "$C" "$API/redoc" "$N"
    printf '  %-26s %s%s%s\n' "OpenAPI schema" "$C" "$API/openapi.json" "$N"
    printf '  %-26s %s%s%s\n' "Gateway health" "$C" "$API/healthz" "$N"
    printf '  %-26s %s%s%s\n' "Gateway metrics" "$C" "$API/metrics" "$N"
    printf '  %-26s %s\n' "  create a post" "POST $API/api/posts"
    printf '  %-26s %s\n' "  read a post" "GET  $API/api/posts/{id}"
    printf '  %-26s %s\n' "  search" "GET  $API/api/search?q=hello"
  else
    warn "gateway is not running — start the stack with ./run.sh"
  fi
  if running prometheus; then
    printf '  %-26s %s%s%s\n' "Prometheus" "$C" "http://$HOST:$PROMETHEUS_PORT" "$N"
    printf '  %-26s %s%s%s\n' "  scrape targets" "$C" "http://$HOST:$PROMETHEUS_PORT/targets" "$N"
    printf '  %-26s %s%s%s\n' "  alert rules" "$C" "http://$HOST:$PROMETHEUS_PORT/alerts" "$N"
  else
    printf '  %-26s %s\n' "Prometheus" "${DIM}not running (./run.sh starts it unless --no-observability)${N}"
  fi
  if running ollama; then
    printf '  %-26s %s%s%s\n' "Local LLM (OpenAI API)" "$C" "http://$HOST:$OLLAMA_PORT/v1" "$N"
  else
    printf '  %-26s %s\n' "Local LLM" "${DIM}not running (./run.sh --llm)${N}"
  fi

  if curl -fsS -o /dev/null "$CONSOLE_URL/api/files" 2>/dev/null; then
    printf '  %-26s %s%s%s\n' "Console (web UI)" "$C" "$CONSOLE_URL" "$N  API playground · harness runs · agent tasks"
  else
    printf '  %-26s %s\n' "Console (web UI)" "${DIM}not running (./run.sh --console or make console)${N}"
  fi

  printf '\n%sInternal only%s %s(no host port by design — reach them through the stack)%s\n' "$B" "$N" "$DIM" "$N"
  printf '  %-26s %s\n' "content, search" "http://content:8000, http://search:8000 — signed calls only (TRUSTED_CALLERS)"
  printf '  %-26s %s\n' "PostgreSQL" "docker compose exec postgres psql -U postgres -d air_harness"
  printf '  %-26s %s\n' "Kafka" "docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list"
  printf '  %-26s %s\n' "Logs" "make logs s=content"

  printf '\n%sReports and data%s\n' "$B" "$N"
  printf '  %-26s %s\n' "Harness report" ".harness/report.md$( [ -f .harness/report.md ] && printf ' (%s)' "$(head -1 .harness/report.md | sed 's/.*: //')")"
  printf '  %-26s %s\n' "Search eval report" ".harness/eval-report.md"
  printf '  %-26s %s\n' "Persistent data" "$DATA_DIR"
}

print_next() {
  printf '\n%sNext steps%s\n' "$B" "$N"
  printf '  1. Open the console:                  %s%s%s  (or the API docs: %s/docs)\n' "$C" "$CONSOLE_URL" "$N" "$API"
  printf '  2. Learn the loop:                    %s./help.sh%s  (or ./help.sh harness)\n' "$C" "$N"
  printf '  3. Check the repo like an agent will: %smake harness-fast%s → .harness/report.md\n' "$C" "$N"
  printf '  4. Give a coding agent its first task: %s./help.sh prompts%s, then e.g.\n' "$C" "$N"
  printf '       %sclaude "$(./help.sh prompt 01)"%s        (or paste the text into any agent)\n' "$C" "$N"
  printf '  5. Stop everything:                   %s./run.sh --down%s\n' "$C" "$N"
}

start_console() {
  python3 -c 'import yaml' 2>/dev/null || { warn "the console needs python3 with PyYAML: pip install pyyaml"; return 1; }
  stop_console
  mkdir -p .harness
  nohup python3 harness/console/server.py > .harness/console.log 2>&1 &
  echo $! > .harness/console.pid
  for _ in $(seq 1 20); do curl -fsS -o /dev/null "$CONSOLE_URL/api/files" 2>/dev/null && { ok "console on $CONSOLE_URL (log: .harness/console.log)"; return 0; }; sleep 0.25; done
  warn "the console did not start — see .harness/console.log"; return 1
}
stop_console() {
  [ -f .harness/console.pid ] && kill "$(cat .harness/console.pid)" 2>/dev/null; rm -f .harness/console.pid; return 0
}

# ------------------------------------------------------------------ preflight
preflight() {
  title "Preflight"
  command -v docker >/dev/null || die "docker is not installed" "https://docs.docker.com/engine/install/"
  docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable" "start Docker Desktop / 'sudo systemctl start docker', then re-run"
  local v; v=$(docker compose version --short 2>/dev/null) || die "docker compose v2 is missing" "install the compose plugin"
  ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), compose $v"
  command -v make >/dev/null || die "make is not installed" "apt install make / xcode-select --install"
  ok "make"
  if [ -f .env ]; then ok ".env found (overrides defaults)"; else ok "no .env — using defaults (cp .env.example .env to change them)"; fi
  if ! running gateway && command -v nc >/dev/null; then
    for p in "$GATEWAY_PORT" "$WEB_PORT" $( [ $OBS = 1 ] && echo "$PROMETHEUS_PORT"); do
      nc -z "$HOST" "$p" 2>/dev/null && die "port $p is already in use" "set GATEWAY_PORT / WEB_PORT / PROMETHEUS_PORT in .env"
    done
    ok "ports $GATEWAY_PORT, $WEB_PORT$( [ $OBS = 1 ] && echo ", $PROMETHEUS_PORT") free"
  fi
  if [ $LLM = 1 ] && ! running ollama && (exec 3<>"/dev/tcp/127.0.0.1/$OLLAMA_PORT") 2>/dev/null; then
    curl -fsS -m 3 -o /dev/null "http://127.0.0.1:$OLLAMA_PORT/api/tags" 2>/dev/null \
      || die "port $OLLAMA_PORT is used by another program, not Ollama" "free it, or set OLLAMA_PORT in .env"
    HOST_OLLAMA=1                    # an Ollama installed on this machine: use it instead of starting a second one
    [ "$(env_value CHAT_LLM_URL http://ollama:11434/v1)" = http://ollama:11434/v1 ] \
      && export CHAT_LLM_URL="http://host.docker.internal:$OLLAMA_PORT/v1"
    ok "Ollama is already running on port $OLLAMA_PORT: the review agent and Chat use it (no second one is started)"
  fi
  mkdir -p .harness
}

smoke_test() {
  title "Smoke test (create → read → search through the public API)"
  if ! command -v curl >/dev/null; then warn "curl not found — skipped"; return 0; fi
  local marker="smoke$(date +%s)" body id
  body=$(curl -fsS -X POST "$API/api/posts" -H 'content-type: application/json' \
         -d "{\"title\":\"Welcome to air-harness $marker\",\"body\":\"Created by run.sh\",\"author\":\"run-sh\"}") \
    || { fail "POST /api/posts failed"; return 1; }
  id=$(printf '%s' "$body" | sed -n 's/.*"id":\([0-9]*\).*/\1/p')
  ok "created post $id"
  curl -fsS "$API/api/posts/$id" >/dev/null && ok "read post $id" || { fail "GET /api/posts/$id failed"; return 1; }
  for _ in $(seq 1 40); do
    if curl -fsS "$API/api/search?q=$marker" | grep -q "\"id\":$id"; then ok "post $id found by search (indexed via Kafka)"; return 0; fi
    sleep 0.5
  done
  fail "post $id not searchable after 20s — check: make logs s=search"; return 1
}

harness_checks() {
  local rc=0
  title "Harness: seeded defects (every sensor can still fire)"
  run make -s harness-selftest | grep -vE '^\s*Container' || rc=1
  if python3 -c 'import yaml' 2>/dev/null; then
    run make -s harness-selftest-host || rc=1
  fi
  title "Harness: fast loop (what an agent runs after every change)"
  run make -s harness-fast | grep -E '^\[|report' || true
  head -1 .harness/report.md | grep -q GREEN && ok "pre-commit stage GREEN" || { fail "pre-commit stage RED — read .harness/report.md"; rc=1; }
  if python3 -c 'import yaml' 2>/dev/null; then
    title "Harness: integration (unit + contract against the running stack)"
    run make -s harness-integration | grep -E '^\[|report' || true
    head -1 .harness/report.md | grep -q GREEN && ok "integration stage GREEN" || { fail "integration stage RED — read .harness/report.md"; rc=1; }
    if [ $FULL = 1 ]; then
      title "Harness: pipeline (everything CI runs: + eval, alert rules)"
      run make -s harness-pipeline | grep -E '^\[|report' || true
      head -1 .harness/report.md | grep -q GREEN && ok "pipeline stage GREEN" || { fail "pipeline stage RED — read .harness/report.md"; rc=1; }
    fi
  else
    warn "host-plane stages need python3 + PyYAML (pip install pyyaml); running the contract suite directly"
    run make -s contract | tail -1 || rc=1
  fi
  return $rc
}

# ------------------------------------------------------------------ main
case "$MODE" in
  down)
    title "Stopping air-harness"
    stop_console
    run make -s down
    ok "stopped; data kept in $DATA_DIR (make purge deletes it)"
    exit 0 ;;
  urls)
    docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable"
    printf '%sair-harness%s\n' "$B" "$N"
    docker compose --profile observability --profile local-llm ps --format 'table {{.Service}}\t{{.Status}}' 2>/dev/null | sed 's/^/  /'
    print_urls; print_next; exit 0 ;;
esac

printf '%sair-harness%s — agent harness + reference system %s(./help.sh for the guide)%s\n' "$B" "$N" "$DIM" "$N"
preflight

title "Building and starting the stack (first run downloads images: a few minutes)"
start=$(date +%s)
if [ $OBS = 1 ]; then run make -s up-observability; else run make -s up; fi \
  || die "the stack did not become healthy" "see: docker compose ps -a; make logs s=<service>"
ok "all services healthy in $(( $(date +%s) - start ))s"
docker compose --profile observability ps --format 'table {{.Service}}\t{{.Status}}' | sed 's/^/    /'

status=0
smoke_test || status=1

if [ $LLM = 1 ]; then
  title "Local LLM for the review agent and Chat ($LLM_MODEL)"
  export LLM_BASE_URL="${LLM_BASE_URL:-$(env_value LLM_BASE_URL http://host.docker.internal:$OLLAMA_PORT/v1)}"
  if [ $HOST_OLLAMA = 1 ]; then
    tools/ollama-pull.sh "http://127.0.0.1:$OLLAMA_PORT" "$LLM_MODEL" host \
      && ok "your Ollama serves $LLM_MODEL (LLM_BASE_URL=$LLM_BASE_URL)" \
      || warn "no model yet: the review agent reports BLIND and Chat lists the sources until it is pulled"
    docker compose exec -T chat python -c "import urllib.request; urllib.request.urlopen('http://host.docker.internal:$OLLAMA_PORT/api/tags', timeout=3)" >/dev/null 2>&1 \
      || warn "the containers cannot reach your Ollama (it listens on 127.0.0.1 only, the Linux default): sudo systemctl edit ollama → Environment=OLLAMA_HOST=0.0.0.0, then restart it"
  else
    run make -s llm LLM_MODEL="$LLM_MODEL" && ok "model ready on http://$HOST:$OLLAMA_PORT/v1; this run reviews with it (LLM_BASE_URL=$LLM_BASE_URL)" \
      || warn "could not start or pull the model — the review agent will report BLIND (advisory, not blocking)"
  fi
  grep -qE '^LLM_BASE_URL=[^ #]' .env 2>/dev/null || warn "to keep the review agent on in later runs: echo 'LLM_BASE_URL=$LLM_BASE_URL' >> .env"
fi

if [ $CHECK = 1 ]; then harness_checks || status=1; fi
if [ $CONSOLE = 1 ]; then title "Web console"; start_console || status=1; fi

print_urls
print_next
if [ $status = 0 ]; then printf '\n%s✔ air-harness is up.%s\n' "$G" "$N"; else printf '\n%s✘ air-harness is up, but some checks failed (see above).%s\n' "$R" "$N"; fi
exit $status
