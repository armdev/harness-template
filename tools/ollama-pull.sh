#!/usr/bin/env bash
# Pull a model into an Ollama and wait until it is ready to answer.
#
#   tools/ollama-pull.sh http://127.0.0.1:11434 qwen3:8b [container|host]
#
# 1. waits until the Ollama API answers (it may still be starting);
# 2. pulls through the API with progress, retrying with backoff (a download of several GB meets network hiccups);
# 3. checks that the model is installed, then loads it into memory so the first question is not slow;
# 4. on failure, says why: a DNS or network error gets the concrete checks for where Ollama runs.
# Exit code 0 when the model is installed and loaded. Settings: PULL_ATTEMPTS (5), OLLAMA_READY_TIMEOUT (120 s).
set -uo pipefail

BASE="${1:?usage: tools/ollama-pull.sh <ollama-url> <model> [container|host]}"
MODEL="${2:?usage: tools/ollama-pull.sh <ollama-url> <model> [container|host]}"
WHERE="${3:-container}"
ATTEMPTS="${PULL_ATTEMPTS:-5}"
READY_TIMEOUT="${OLLAMA_READY_TIMEOUT:-120}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'; else G=; R=; Y=; N=; fi
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
fail() { printf '  %s✘%s %s\n' "$R" "$N" "$1"; }

installed() { curl -fsS -m 10 "$BASE/api/tags" 2>/dev/null | grep -qE "\"name\": *\"$MODEL\""; }
json_field() { sed -n "s/.*\"$1\": *\"\\{0,1\\}\\([^\",}]*\\).*/\\1/p" <<< "$2"; }   # compact or spaced JSON

wait_ready() {
  local waited=0
  until curl -fsS -m 5 -o /dev/null "$BASE/api/tags" 2>/dev/null; do
    if [ "$waited" -ge "$READY_TIMEOUT" ]; then printf '\n'; return 1; fi
    [ "$waited" = 0 ] && printf '  waiting for Ollama at %s ' "$BASE"
    printf '.'; sleep 2; waited=$((waited + 2))
  done
  [ "$waited" -gt 0 ] && printf '\n'
  return 0
}

# One pull through the streaming API; prints progress, sets LAST_ERROR from an {"error": ...} line or curl.
LAST_ERROR=""
pull_once() {
  local line status total completed pct last_shown="" out
  LAST_ERROR=""
  while IFS= read -r line; do
    if [[ "$line" == *'"error"'* ]]; then          # the message may contain escaped quotes: take it whole
      LAST_ERROR=$(sed -n 's/.*"error": *"\(.*\)"[,}].*/\1/p' <<< "$line" | sed 's/\\"/"/g'); continue
    fi
    if [[ "$line" == curl:* ]]; then LAST_ERROR="$line"; continue; fi
    status=$(json_field status "$line"); total=$(json_field total "$line"); completed=$(json_field completed "$line")
    if [ -n "$total" ] && [ -n "$completed" ] && [ "$total" -gt 0 ] 2>/dev/null; then
      pct=$((completed * 100 / total))
      out="$status $pct% ($((completed / 1048576)) / $((total / 1048576)) MB)"
      if [ -t 1 ]; then printf '\r  %-78s' "$out"; elif [ $((pct % 10)) = 0 ] && [ "$out" != "$last_shown" ]; then printf '  %s\n' "$out"; fi
      last_shown=$out
    elif [ -n "$status" ] && [ "$status" != "$last_shown" ]; then
      [ -t 1 ] && printf '\r%-82s\r' ''
      printf '  %s\n' "$status"; last_shown=$status
    fi
  done < <(curl -sS -N -m 7200 "$BASE/api/pull" -d "{\"model\":\"$MODEL\"}" 2>&1)
  [ -t 1 ] && printf '\r%-82s\r' ''
  installed
}

explain() {
  case "$LAST_ERROR" in
    *lookup*|*"no such host"*|*"dial tcp"*|*"i/o timeout"*|*"connection refused"*|*"network is unreachable"*|*TLS*|*x509*)
      fail "Ollama cannot reach the model registry (registry.ollama.ai): $LAST_ERROR"
      [[ "$LAST_ERROR" == *127.0.0.53* ]] && printf '    %s\n' \
        "127.0.0.53 is this machine's systemd-resolved, and it refused the lookup: is it running?" \
        "  check: systemctl status systemd-resolved  ·  resolvectl query registry.ollama.ai  ·  sudo systemctl restart systemd-resolved"
      if [ "$WHERE" = container ]; then
        printf '    %s\n' \
          "the Ollama container has no working DNS or internet access. Check: docker run --rm busybox nslookup registry.ollama.ai" \
          "if that fails, Docker's DNS is the problem (common with systemd-resolved on 127.0.0.53):" \
          "  add {\"dns\": [\"1.1.1.1\", \"8.8.8.8\"]} to /etc/docker/daemon.json, then: sudo systemctl restart docker" \
          "behind a proxy: set OLLAMA_HTTPS_PROXY in .env (it is passed to the Ollama container), then retry" \
          "or install Ollama on this machine, run 'ollama pull $MODEL' there: ./app.sh up --llm then uses it"
      else
        printf '    %s\n' "your Ollama has no working DNS or internet access: check 'ollama pull $MODEL' in a terminal"
      fi ;;
    "") fail "the model $MODEL is not installed after $ATTEMPTS attempts" ;;
    *) fail "could not pull $MODEL: $LAST_ERROR" ;;
  esac
}

wait_ready || { fail "Ollama at $BASE did not answer within ${READY_TIMEOUT}s"; exit 1; }
if installed; then
  ok "model $MODEL is already installed"
else
  delay=5
  for attempt in $(seq 1 "$ATTEMPTS"); do
    [ "$attempt" -gt 1 ] && printf '  attempt %d of %d\n' "$attempt" "$ATTEMPTS"
    if pull_once; then ok "model $MODEL installed"; break; fi
    if [ "$attempt" = "$ATTEMPTS" ]; then explain; exit 1; fi
    warn "pull failed (${LAST_ERROR:-incomplete}); retrying in ${delay}s"
    sleep "$delay"; delay=$((delay * 2))
  done
fi
printf '  loading %s into memory (the first time takes a while)…\n' "$MODEL"
if curl -fsS -m 900 -o /dev/null "$BASE/api/generate" -d "{\"model\":\"$MODEL\",\"prompt\":\"\",\"keep_alive\":\"30m\"}"; then
  ok "model $MODEL is loaded and ready"
else
  warn "the model is installed but did not load yet; the first question will load it"
fi
exit 0
