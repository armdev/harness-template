#!/usr/bin/env bash
# air-harness — the guide in your terminal.
#
#   ./help.sh                     what air-harness is and how to start
#   ./help.sh <topic>             run · app · commands · urls · harness · agent · prompts · config · troubleshoot
#   ./help.sh prompt <n|name>     print one next-step prompt, ready to paste: claude "$(./help.sh prompt 02)"
#   ./help.sh prompt task "..."   the generic task prompt with your task filled in
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; C=$'\033[36m'; Y=$'\033[33m'; N=$'\033[0m'
else B=; DIM=; C=; Y=; N=; fi
h()  { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
kv() { printf '  %s%-34s%s %s\n' "$C" "$1" "$N" "$2"; }
p()  { printf '  %s\n' "$1"; }

PROMPTS=harness/prompts/next-steps

overview() {
  printf '%sair-harness%s — an agent harness as a product, with a reference system to run it on.\n' "$B" "$N"
  p ""
  p "Guides steer a coding agent before it acts (AGENTS.md, skills, rubric, prompts)."
  p "Sensors tell it what went wrong after (topology, migrations, lint, semgrep, review, contract, eval)."
  p "Everything runs in docker compose; the harness writes one report the agent reads: .harness/report.md"
  h "Start in three commands"
  kv "./run.sh" "build + start everything, smoke-test it, print all URLs and next steps"
  kv "./run.sh --check" "… and prove the harness works (selftest, fast loop, contract suite)"
  kv "./run.sh --console" "… and open the web console: http://127.0.0.1:8090 (API, harness, agent)"
  kv "./app.sh" "only the application (the RAG services), without the harness: ./help.sh app"
  kv "claude \"\$(./help.sh prompt 01)\"" "hand a coding agent its first prompt (or paste it into any agent)"
  h "The loop (what you and the agent do on every change)"
  p "1. edit   →  2. make harness-fast  →  3. read .harness/report.md  →  4. fix blocking failures first"
  p "5. before \"done\": make up && make harness-integration   (unit + contract suite)"
  h "More help"
  kv "./help.sh run" "run.sh options"
  kv "./help.sh commands" "every make target"
  kv "./help.sh urls" "what is reachable where (live, from the running stack)"
  kv "./help.sh harness" "stages, sensors, the report, the steering loop"
  kv "./help.sh agent" "using it with Claude Code, other agents, git hooks and CI"
  kv "./help.sh prompts" "guided next-step prompts (explore → first feature → … → ship)"
  kv "./help.sh config" "configuration (.env)"
  kv "./help.sh troubleshoot" "when something does not start"
  p ""
  p "${DIM}Docs: docs/README.md (EN + RU: concepts, usage, use cases, architecture, components, LLD),${N}"
  p "${DIM}      README.md (product), AGENTS.md (for agents), harness/HARNESS.md (design), harness/CHANGELOG.md${N}"
}

topic_run() {
  h "./run.sh — run the whole product"
  sed -n '3,12p' run.sh | sed 's/^# \{0,1\}/  /'
  h "What it does"
  p "preflight (docker, compose, make, free ports) → build + start the stack and wait until healthy →"
  p "smoke test through the public API (create, read, search) → optional harness checks → URLs → next steps."
  p "Exit code 0 only when everything it ran passed."
}

topic_app() {
  h "./app.sh — the application alone, without the harness"
  sed -n '2,12p' app.sh | sed 's/^# \{0,1\}/  /'
}

topic_commands() {
  h "make targets"
  make -s help 2>/dev/null || grep -hE '^[a-z-]+:.*## ' Makefile harness.mk | awk -F':.*## ' '{printf "  %-22s %s\n", $1, $2}'
}

topic_urls() { ./run.sh --urls; }

topic_harness() {
  h "Stages — keep quality left"
  kv "pre-commit   make harness-fast" "topology, migrations, ruff, semgrep (blocking) + review agent (advisory). < 1 min, no network"
  kv "integration  make harness-integration" "unit + contract suite against the running stack"
  kv "pipeline     make harness-pipeline" "all of the above + search eval + alert-rule check (what CI runs)"
  kv "continuous   make harness-continuous" "nightly: dead code, vulnerable dependencies"
  h "The report: .harness/report.md"
  p "First line: GREEN or RED. Then: blocking failures (each with How to fix, Guides, Re-run only this),"
  p "advisory findings, BLIND sensors (harness problems — report, never work around), warnings, passed."
  kv "make harness-one s=<sensor>" "re-run a single sensor while you fix it"
  kv "make harness-list" "all sensors with stage, plane, blocking, command"
  h "Trust the harness"
  kv "make harness-selftest" "every sensor fires on its seeded defects and stays quiet on clean fixtures"
  kv "make harness-selftest-live" "the same for live-plane sensors (deps-audit; review-agent when an LLM is set)"
  kv "make harness-selftest-host" "the same for host-plane sensors (prom-rules, unit, contract, eval; stack up, PyYAML)"
  kv "make harness-coverage" "guides × sensors: rules nobody checks, lessons nobody teaches"
  kv "make harness-stats" "steering loop: what fires often (weak guide), what never fires, what is blind"
  kv "make harness-test" "tests and lint of the harness code itself"
  p ""
  p "Manifest: harness.yaml · rubric: harness/review/RUBRIC.md · design: harness/HARNESS.md"
}

topic_agent() {
  h "In the browser"
  p "make console (stack up) → http://127.0.0.1:8090 → Agent tab: compose a prompt, Run agent (AGENT_CMD,"
  p "default claude -p), watch its output and the harness runs its Stop hook triggers."
  h "Any coding agent"
  p "Entry point is AGENTS.md. Skills live in harness/skills/<name>/SKILL.md:"
  for f in harness/skills/*/SKILL.md; do
    kv "$(basename "$(dirname "$f")")" "$(sed -n 's/^description: //p' "$f" | cut -c1-90)"
  done
  p "Start a task with:  ./help.sh prompt task \"<your task>\"   (fills harness/prompts/agent/task.md)"
  h "Claude Code (wired in this repo)"
  p "CLAUDE.md imports AGENTS.md; the skills are under .claude/skills/. A Stop hook"
  p "(harness/hooks/agent-stop.sh) runs the static sensors when the agent tries to finish with uncommitted"
  p "changes and sends it back with the report while they are RED (it never blocks twice in a row)."
  kv "claude \"\$(./help.sh prompt 02)\"" "interactive session that starts with a guided step"
  kv "./help.sh prompt 02 | claude -p" "non-interactive: run one guided step and print the result"
  h "git and CI"
  kv "git config core.hooksPath .githooks" "blocking static sensors before every commit"
  kv ".github/workflows/harness.yml" "selftest, fast loop, stack + pipeline on every PR; continuous nightly"
  h "Review agent (advisory)"
  p "Opt-in. Needs an OpenAI-compatible LLM: ./run.sh --llm (local Ollama) or LLM_BASE_URL / LLM_MODEL in .env."
  p "Not configured → SKIPPED (expected). Configured but unreachable → BLIND (fix the endpoint). Never blocks."
}

topic_prompts() {
  h "Next-step prompts — in the order you will need them"
  for f in "$PROMPTS"/*.md; do
    local n title when
    n=$(basename "$f" .md)
    title=$(sed -n '1s/^# [0-9]* · //p' "$f")
    when=$(sed -n 's/^When: //p' "$f")
    kv "${n%%-*}  $title" ""
    printf '        %s%s%s\n' "$DIM" "$when" "$N"
  done
  h "Use one"
  kv "./help.sh prompt 02" "print it (copy into Claude Code, Cursor, Codex, ...)"
  kv "claude \"\$(./help.sh prompt 02)\"" "start Claude Code with it (| claude -p for headless)"
  kv "./help.sh prompt task \"add X\"" "generic task prompt with your task filled in"
  kv "./help.sh prompt fix-red" "agent templates: task, fix-red (current report filled in), done-check"
}

topic_config() {
  h "Configuration"
  p "Every setting has a working default in docker-compose.yml. To change one: cp .env.example .env and edit."
  p "The topology sensor (T8) fails if compose uses a variable that .env.example does not document."
  p ""
  grep -E '^[A-Z_]+=' .env.example | sed 's/^/  /'
}

topic_troubleshoot() {
  h "Troubleshooting"
  kv "Cannot connect to the Docker daemon" "start Docker Desktop / sudo systemctl start docker"
  kv "port is already allocated" "set GATEWAY_PORT / PROMETHEUS_PORT in .env, then ./run.sh"
  kv "service unhealthy / exited" "docker compose ps -a, then make logs s=<service>"
  kv "migrate exited with an error" "make logs s=migrate — a migration failed; never edit an applied one, add V<next>"
  kv "subpath / volume errors" "Docker Engine 26+ and Compose 2.24+ are required (volume subpath)"
  kv "review-agent SKIPPED" "no LLM configured — expected; to enable: ./run.sh --llm or LLM_BASE_URL in .env"
  kv "review-agent BLIND" "LLM_BASE_URL is set but unreachable: check the endpoint (advisory, never blocks)"
  kv "host plane needs PyYAML" "pip install pyyaml (only for harness-integration / -pipeline)"
  kv "start from scratch" "make purge (deletes DATA_DIR content), then ./run.sh"
  kv "stale results in the report" "re-run: make harness-fast — results from another commit are marked stale"
}

print_prompt() {
  local key="${1:-}"; shift || true
  local file=""
  case "$key" in
    "") topic_prompts; return 0 ;;
    task|fix-red|done-check) file="harness/prompts/agent/$key.md" ;;
    *) file=$(ls "$PROMPTS"/"$key"*.md 2>/dev/null | head -1)
       [ -z "$file" ] && file=$(ls "$PROMPTS"/*-"$key"*.md 2>/dev/null | head -1) ;;
  esac
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    printf '%sno prompt "%s"%s — see ./help.sh prompts\n' "$Y" "$key" "$N" >&2; return 1
  fi
  if [ "$key" = task ]; then
    local task="$*"
    [ -z "$task" ] && { printf '%susage: ./help.sh prompt task "<what the agent should do>"%s\n' "$Y" "$N" >&2; return 1; }
    TASK="$task" python3 -c 'import os,sys; sys.stdout.write(open(sys.argv[1]).read().replace("{{task}}", os.environ["TASK"]))' "$file" 2>/dev/null \
      || sed "s|{{task}}|$task|" "$file"
  elif [ "$key" = fix-red ]; then
    [ -f .harness/report.md ] || { printf '%srun make harness-fast first (no .harness/report.md)%s\n' "$Y" "$N" >&2; return 1; }
    python3 -c 'import sys; sys.stdout.write(open(sys.argv[1]).read().replace("{{report_md}}", open(sys.argv[2]).read()))' \
      "$file" .harness/report.md
  elif grep -q '^---$' "$file"; then
    sed '1,/^---$/d' "$file"           # header is for humans; print only the prompt
  else
    cat "$file"
  fi
}

case "${1:-}" in
  ""|-h|--help|help) overview ;;
  run) topic_run ;;
  app) topic_app ;;
  commands|make) topic_commands ;;
  urls|status) topic_urls ;;
  harness|loop) topic_harness ;;
  agent|agents|claude) topic_agent ;;
  prompts) topic_prompts ;;
  prompt) shift; print_prompt "$@" ;;
  config|env) topic_config ;;
  troubleshoot|trouble|faq) topic_troubleshoot ;;
  *) printf '%sunknown topic "%s"%s\n\n' "$Y" "$1" "$N"; overview; exit 1 ;;
esac
