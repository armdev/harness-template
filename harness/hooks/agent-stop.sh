#!/usr/bin/env sh
# Stop hook for coding agents (Claude Code `Stop` event; adapt for others).
# When the agent tries to finish with uncommitted changes, run the static sensors. If they are RED, exit 2:
# the agent is not allowed to stop, and stderr tells it where to look. Exit 0 in every other case.
set -u
input=$(cat)
# Already continuing because of this hook: let it stop, so a broken harness cannot trap the agent in a loop.
case "$input" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0 ;; esac

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}" || exit 0
[ -n "$(git status --porcelain 2>/dev/null)" ] || exit 0          # nothing changed: nothing to check
command -v docker >/dev/null 2>&1 || exit 0                      # no sensors available here

if make -s harness-static >/dev/null 2>&1; then
  exit 0
fi
{
  echo "Harness is RED: blocking sensors fail on your uncommitted changes."
  echo "Read .harness/report.md and follow harness/skills/harness-report/SKILL.md before finishing."
  sed -n '1,60p' .harness/report.md 2>/dev/null
} >&2
exit 2
