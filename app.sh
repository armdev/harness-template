#!/usr/bin/env bash
# The application alone: the RAG system (web, gateway, content, search, notify, graph, chat, planner + postgres, kafka,
# neo4j),
# without the harness, the console or make. Needs only docker (compose v2) and curl.
#
#   ./app.sh [up]            build + start the application, wait until healthy, smoke-test it, print URLs
#   ./app.sh up --observability   ... and Prometheus on :9090;  --no-build: start the images you already have
#   ./app.sh up --llm        ... and a local model for Chat (Ollama; pulls CHAT_MODEL, several GB the first time)
#   ./app.sh pull [model]    (re)pull the Chat model into Ollama and wait until it is loaded (retries, progress)
#   ./app.sh status          service status and URLs
#   ./app.sh logs [service]  follow logs (all services, or one: ./app.sh logs search)
#   ./app.sh test            the API specification (contract suite) against the running application
#   ./app.sh seed [dataset]  load sample data through the API: general, bank, ibank (posts), planner (employees, tasks,
#                            meetings) or a .json file; repeatable
#   ./app.sh down            stop (data in DATA_DIR is kept)
#   ./app.sh export <dir>    copy the application, without the harness, into <dir> (a standalone project)
#   ./app.sh help            this text
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else B=; DIM=; G=; R=; C=; N=; fi
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$1"; }
fail() { printf '  %s✘%s %s\n' "$R" "$N" "$1"; }
die()  { fail "$1"; exit 1; }
run()  { printf '  %s$ %s%s\n' "$DIM" "$*" "$N"; "$@"; }

env_value() {   # env_value NAME DEFAULT → value from the environment, else .env, else DEFAULT
  local v="${!1:-}"
  if [ -z "$v" ] && [ -f .env ]; then
    v=$(sed -n "s/^[[:space:]]*$1=\([^#]*\).*/\1/p" .env | tail -1 | sed 's/[[:space:]]*$//')
  fi
  printf '%s' "${v:-$2}"
}
HOST=$(env_value PUBLIC_HOST localhost)
API="http://$HOST:$(env_value GATEWAY_PORT 8080)"
WEB="http://$HOST:$(env_value WEB_PORT 8081)"
PROMETHEUS="http://$HOST:$(env_value PROMETHEUS_PORT 9090)"
DC=(docker compose -f docker-compose.yml)   # only the application's compose file, never the harness overlay

# What a standalone copy of the application contains (`export`); everything else is the harness or its docs.
APP_PATHS=(services libs db infra contract tools docker-compose.yml .env.example .dockerignore app.sh)

preflight() {
  command -v docker >/dev/null || die "docker is not installed: https://docs.docker.com/engine/install/"
  docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable: start Docker, then re-run"
  docker compose version >/dev/null 2>&1 || die "docker compose v2 is missing: install the compose plugin"
}

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }      # bash built-in: no nc or lsof needed
running() { "${DC[@]}" --profile observability --profile local-llm ps --status running --services 2>/dev/null | grep -qx "$1"; }

# check_ports SERVICE:PORT:VARIABLE ... — a host port held by another program stops the start with what to change,
# instead of a half-started stack and docker's "address already in use".
check_ports() {
  local spec svc port var
  for spec in "$@"; do
    IFS=: read -r svc port var <<< "$spec"
    running "$svc" && continue                                     # our own container already holds it
    port_in_use "$port" && die "port $port (for $svc) is already used by another program: free it, or set $var in .env"
  done
  return 0
}

OLLAMA_URL_IN_STACK=http://ollama:11434/v1
# use_host_ollama PORT — an Ollama already runs on this machine (installed natively): Chat uses it, none is started.
use_host_ollama() {
  local current
  current=$(env_value CHAT_LLM_URL "$OLLAMA_URL_IN_STACK")
  if [ "$current" = "$OLLAMA_URL_IN_STACK" ]; then
    export CHAT_LLM_URL="http://host.docker.internal:$1/v1"
    ok "Ollama is already running on port $1: Chat uses it ($CHAT_LLM_URL); no second one is started"
  else
    ok "Ollama is already running on port $1: no second one is started; Chat keeps CHAT_LLM_URL=$current"
  fi
}

# host_ollama_reachable — from inside the stack; a native Ollama on Linux listens on 127.0.0.1 only by default.
host_ollama_reachable() {
  "${DC[@]}" exec -T chat python -c "import os, urllib.request; urllib.request.urlopen(os.environ['CHAT_LLM_URL'].removesuffix('/v1') + '/api/tags', timeout=3)" >/dev/null 2>&1
}

smoke() {
  printf '\n%sSmoke test%s (create → read → search → related, through the public API)\n' "$B" "$N"
  command -v curl >/dev/null || { fail "curl not found: skipped"; return 0; }
  local marker="app$(date +%s)" body id
  body=$(curl -fsS -X POST "$API/api/posts" -H 'content-type: application/json' \
         -d "{\"title\":\"Hello $marker\",\"body\":\"Created by app.sh\",\"author\":\"app-sh\",\"tags\":[\"$marker\"]}") \
    || { fail "POST /api/posts failed"; return 1; }
  id=$(printf '%s' "$body" | sed -n 's/.*"id":\([0-9]*\).*/\1/p')
  ok "created post $id"
  curl -fsS -o /dev/null "$API/api/posts/$id" && ok "read post $id" || { fail "GET /api/posts/$id failed"; return 1; }
  local searched=0 graphed=0
  for _ in $(seq 1 40); do
    [ $searched = 1 ] || { curl -fsS "$API/api/search?q=$marker" | grep -q "\"id\":$id" && searched=1; }
    [ $graphed = 1 ] || { curl -fsS -o /dev/null "$API/api/tags/$marker" 2>/dev/null && graphed=1; }
    [ $searched = 1 ] && [ $graphed = 1 ] && break
    sleep 0.5
  done
  [ $searched = 1 ] && ok "post $id found by search (indexed via Kafka)" || { fail "post $id not searchable after 20s: ./app.sh logs search"; return 1; }
  [ $graphed = 1 ] && ok "post $id in the knowledge graph (tag $marker)" || { fail "post $id not in the graph after 20s: ./app.sh logs graph"; return 1; }
  curl -fsS "$WEB/api/posts/$id" | grep -q "\"id\":$id" && ok "web portal serves post $id through the gateway" \
    || { fail "the web portal does not reach the gateway: ./app.sh logs web"; return 1; }
  local answer
  answer=$(curl -fsS -N --max-time 200 "$WEB/api/chat" -H 'content-type: application/json' \
           -d "{\"messages\":[{\"role\":\"user\",\"content\":\"What is $marker about?\"}]}")
  grep -q "\"id\": $id" <<< "$answer" \
    && ok "chat answers with post $id among its sources" || { fail "chat did not use post $id: ./app.sh logs chat"; return 1; }
  local team
  team=$(curl -fsS "$WEB/api/planner/employees") && grep -q '"employees"' <<< "$team" \
    && ok "planner answers through the portal" || { fail "the planner does not answer: ./app.sh logs planner"; return 1; }
}

urls() {
  printf '\n%sURLs%s\n' "$B" "$N"
  printf '  %-24s %s%s%s\n' "Web portal (rag-web)" "$C" "$WEB" "$N  analyze · search · graph · chat · plan · write"
  printf '  %-24s %s%s%s\n' "API docs (Swagger UI)" "$C" "$API/docs" "$N"
  printf '  %-24s %s%s%s\n' "OpenAPI schema" "$C" "$API/openapi.json" "$N"
  printf '  %-24s %s\n' "  posts" "POST $API/api/posts · GET $API/api/posts/{id} · GET $API/api/posts?author="
  printf '  %-24s %s\n' "  search (RAG retrieval)" "GET  $API/api/search?q=kafka"
  printf '  %-24s %s\n' "  knowledge graph" "GET  $API/api/posts/{id}/related · /api/tags/{tag}[/posts] · /api/graph/overview"
  printf '  %-24s %s\n' "  notifications" "GET  $API/api/notifications?author="
  printf '  %-24s %s\n' "  chat (RAG answer)" "POST $API/api/chat   (streamed; model: $(env_value CHAT_LLM_URL http://ollama:11434/v1))"
  printf '  %-24s %s\n' "  planner" "GET  $API/api/planner/employees · /tasks · /plan/{handle} · POST /plan/{handle}/ai"
  if "${DC[@]}" --profile observability ps --status running --services 2>/dev/null | grep -qx prometheus; then
    printf '  %-24s %s%s%s\n' "Prometheus" "$C" "$PROMETHEUS" "$N"
  fi
  printf '  %-24s %s\n' "Persistent data" "$(env_value DATA_DIR /var/tmp/air-harness)"
}

export_app() {
  local dest="${1:-}"
  [ -n "$dest" ] || die "usage: ./app.sh export <dir>"
  [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ] && die "$dest exists and is not empty"
  mkdir -p "$dest" || die "cannot create $dest"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files -z --cached --others --exclude-standard -- "${APP_PATHS[@]}" | tar --null -T - -cf - | tar -xf - -C "$dest"
  else
    tar -cf - "${APP_PATHS[@]}" | tar -xf - -C "$dest"
  fi || die "copy failed"
  cat > "$dest/README.md" <<'EOF'
# RAG application

Posts (content), full-text search (search), notifications (notify) and a knowledge graph (graph, Neo4j)
behind one public gateway, a planner of employees' tasks and meetings (planner, rules + a language model), and a web
portal (web) for all of it: http://localhost:8081. Services call each other with Ed25519-signed requests; posts flow to search,
notify and graph over Kafka (`content.post.created`).

    ./app.sh            build + start, smoke test, URLs   (needs docker with compose v2, and curl)
    ./app.sh seed bank  load 100 banking posts (loans, credit, debit, payments, risk); or: general
    ./app.sh seed planner   load a bank IT team: 11 employees, 61 Jira-style tasks, 57 meetings (Plan page)
    ./app.sh test       API specification (contract suite)
    ./app.sh down       stop; data stays in DATA_DIR (default /var/tmp/air-harness)

Configuration: copy `.env.example` to `.env` and change what you need. API docs: http://localhost:8080/docs
EOF
  ok "application exported to $dest (no harness): cd $dest && ./app.sh"
}

cmd="${1:-up}"; [ $# -gt 0 ] && shift
case "$cmd" in
  up)
    obs=0 llm=0 build=--build
    for arg in "$@"; do
      case "$arg" in
        --observability) obs=1 ;;
        --llm) llm=1 ;;
        --no-build) build=--no-build ;;
        *) die "unknown option: $arg (see ./app.sh help)" ;;
      esac
    done
    preflight
    check_ports "gateway:$(env_value GATEWAY_PORT 8080):GATEWAY_PORT" "web:$(env_value WEB_PORT 8081):WEB_PORT"
    [ $obs = 1 ] && check_ports "prometheus:$(env_value PROMETHEUS_PORT 9090):PROMETHEUS_PORT"
    host_ollama=0 ollama_port=$(env_value OLLAMA_PORT 11434)
    if [ $llm = 1 ] && ! running ollama && port_in_use "$ollama_port"; then
      curl -fsS -m 3 -o /dev/null "http://127.0.0.1:$ollama_port/api/tags" 2>/dev/null \
        || die "port $ollama_port is used by another program, not Ollama: free it, or set OLLAMA_PORT in .env"
      host_ollama=1
      use_host_ollama "$ollama_port"
    fi
    profile=()
    [ $obs = 1 ] && profile+=(--profile observability)
    [ $llm = 1 ] && [ $host_ollama = 0 ] && profile+=(--profile local-llm)
    printf '%sRAG application%s: building and starting (first run downloads images: a few minutes)\n' "$B" "$N"
    run "${DC[@]}" ${profile[@]+"${profile[@]}"} up -d "$build" --wait || die "the application did not become healthy: ./app.sh status; ./app.sh logs <service>"
    ok "all services healthy"
    status=0; smoke || status=1
    if [ $llm = 1 ]; then
      model=$(env_value CHAT_MODEL qwen3:8b)
      printf '\n%sLocal model for Chat%s (%s; the first pull downloads several GB)\n' "$B" "$N" "$model"
      where=container; [ $host_ollama = 1 ] && where=host
      tools/ollama-pull.sh "http://127.0.0.1:$ollama_port" "$model" "$where" \
        || { fail "no model: Chat answers with the retrieved posts until it is pulled (re-run ./app.sh up --llm)"; status=1; }
      if [ $host_ollama = 1 ]; then
        if ! host_ollama_reachable; then
          fail "the containers cannot reach your Ollama: it listens on 127.0.0.1 only (the default on Linux)"
          printf '    %s\n' "make it listen on all interfaces: sudo systemctl edit ollama  →  [Service] Environment=OLLAMA_HOST=0.0.0.0" \
            "then: sudo systemctl restart ollama && ./app.sh up --llm   (or stop it, and ./app.sh up --llm starts its own)"
          status=1
        fi
        grep -qE '^CHAT_LLM_URL=http://host.docker.internal' .env 2>/dev/null \
          || printf '    %s\n' "to keep Chat on it without --llm: echo 'CHAT_LLM_URL=$CHAT_LLM_URL' >> .env"
      fi
    fi
    urls
    [ $status = 0 ] && printf '\n%s✔ the application is up.%s Stop it with ./app.sh down\n' "$G" "$N"
    exit $status ;;
  pull)  preflight
         ollama_port=$(env_value OLLAMA_PORT 11434) where=host
         running ollama && where=container
         port_in_use "$ollama_port" || die "no Ollama on port $ollama_port: start one with ./app.sh up --llm"
         tools/ollama-pull.sh "http://127.0.0.1:$ollama_port" "${1:-$(env_value CHAT_MODEL qwen3:8b)}" "$where" ;;
  status|ps)
    preflight
    "${DC[@]}" --profile observability --profile local-llm ps -a --format 'table {{.Service}}\t{{.Status}}'
    urls ;;
  logs)  preflight; "${DC[@]}" logs -f --tail=200 "$@" ;;
  test)  preflight; run "${DC[@]}" --profile tools run --rm --build contract ;;
  seed)  case "${1:-}" in *.json) [ -f "$1" ] || die "no such file: $1 (give the path of a dataset .json, or a name: general, bank, ibank, planner)" ;; esac
         preflight
         if [ -f "${1:-}" ]; then          # a dataset file on this machine: hand it to the seed container
           file="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
           run "${DC[@]}" --profile tools run --rm --build -v "$file:/repo/custom.json:ro" seed /repo/custom.json
         else
           run "${DC[@]}" --profile tools run --rm --build seed "${1:-general}"
         fi ;;
  down|stop) preflight; run "${DC[@]}" --profile observability --profile local-llm down --remove-orphans && ok "stopped; data kept" ;;
  export) export_app "$@" ;;
  help|-h|--help) awk 'NR>1 && !/^#/{exit} NR>1' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command: $cmd (see ./app.sh help)" ;;
esac
