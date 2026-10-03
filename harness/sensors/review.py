#!/usr/bin/env python3
"""Inferential sensor: review the diff against the same rubric the coding agent was given.

OpenAI-compatible endpoint (vLLM, Ollama, ...). Stdlib only. Exit 1 if the reviewer reports an ERROR,
125 if no endpoint is configured (LLM_BASE_URL empty: the runner reports SKIPPED), 127 if the configured reviewer is
unreachable or answers nonsense (the runner reports the sensor BLIND, not the code bad).
Advisory in harness.yaml until its precision on real diffs has been measured.

What is reviewed (REVIEW_DIFF_BASE):
  empty      staged changes; if nothing is staged, the working tree against HEAD plus untracked files
             (so the post-edit hook of a coding agent sees its uncommitted work)
  <rev>      everything since <rev>, e.g. origin/main in CI
REVIEW_DIFF_FILE, when set, is reviewed instead (the selftest feeds seeded diffs from harness/sensors/fixtures/review).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("LLM_BASE_URL", "").rstrip("/")             # empty: review is off (opt-in)
MODEL = os.environ.get("REVIEW_MODEL") or os.environ.get("LLM_MODEL", "qwen3:8b")
KEY = os.environ.get("LLM_API_KEY", "not-needed")
NO_THINK = os.environ.get("LLM_NO_THINK", "true").lower() == "true"
DIFF_BASE = os.environ.get("REVIEW_DIFF_BASE", "")
DIFF_FILE = os.environ.get("REVIEW_DIFF_FILE", "")
MAX_DIFF = int(os.environ.get("REVIEW_MAX_DIFF_CHARS", "60000"))
RUBRIC = Path(os.environ.get("REVIEW_RUBRIC", "harness/review/RUBRIC.md"))
PROMPT = Path(os.environ.get("REVIEW_PROMPT", "harness/prompts/review.md"))
TIMEOUT = int(os.environ.get("REVIEW_TIMEOUT", "180"))
# what the rubric governs; harness/install.py sets REVIEW_SCOPE to the adopting project's sources
SCOPE = tuple(os.environ.get("REVIEW_SCOPE", "services libs db contract docker-compose.yml infra").split())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout  # noqa: S603,S607


def collect_diff() -> str:
    if DIFF_FILE:
        return Path(DIFF_FILE).read_text()
    if DIFF_BASE:
        return git("diff", "--unified=5", DIFF_BASE, "--", *SCOPE)
    staged = git("diff", "--unified=5", "--cached", "--", *SCOPE)
    if staged.strip():
        return staged
    diff = git("diff", "--unified=5", "HEAD", "--", *SCOPE)
    for path in git("ls-files", "--others", "--exclude-standard", "--", *SCOPE).splitlines():
        try:
            body = Path(path).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        diff += f"\n--- /dev/null\n+++ b/{path}\n" + "".join(f"+{ln}\n" for ln in body.splitlines())
    return diff


def parse_findings(text: str) -> list[dict]:
    """Tolerate thinking blocks and code fences around the JSON object; raise ValueError if there is none."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    findings = json.loads(text[start:end + 1]).get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("findings is not a list")
    return [f for f in findings if isinstance(f, dict)]


def ask(rubric: str, diff: str, truncated: bool) -> str:
    body = {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": PROMPT.read_text()},
            {"role": "user", "content": f"RUBRIC:\n{rubric}\n\nDIFF{' (truncated)' if truncated else ''}:\n{diff}"},
        ],
    }
    if NO_THINK:
        body["chat_template_kwargs"] = {"enable_thinking": False}   # vLLM/Qwen3; other servers ignore it
    if not BASE.startswith(("http://", "https://")):
        raise ValueError(f"LLM_BASE_URL must be http(s): {BASE}")
    req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(body).encode(),  # noqa: S310
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — scheme checked above
        return json.load(r)["choices"][0]["message"]["content"]


def main() -> int:
    if not BASE:
        print("review: skipped — no LLM configured. Set LLM_BASE_URL (and LLM_MODEL) in .env, e.g. "
              "LLM_BASE_URL=http://host.docker.internal:11434/v1 after ./run.sh --llm")
        return 125
    diff = collect_diff()
    if not diff.strip():
        print("review: empty diff, nothing to review")
        return 0
    truncated = len(diff) > MAX_DIFF
    try:
        text = ask(RUBRIC.read_text(), diff[:MAX_DIFF], truncated)
    except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError) as e:
        print(f"review: LLM unreachable at {BASE} ({MODEL}): {e}")
        return 127
    try:
        findings = parse_findings(text)
    except ValueError:
        print(f"review: reviewer returned non-JSON (sensor noise, not a code failure):\n{text[:500]}")
        return 127
    for f in findings:
        sev = "ERROR" if f.get("severity") == "ERROR" else "WARN"
        print(f"{sev:5} {f.get('rule', '?'):12} {f.get('file', '?')}:{f.get('line') or '-'}\n"
              f"      what: {f.get('what', '')}\n      fix:  {f.get('fix', '')}")
    if truncated:
        print(f"WARN  review: diff truncated to {MAX_DIFF} chars — split the change")
    errors = sum(f.get("severity") == "ERROR" for f in findings)
    print(f"review: {len(findings)} findings, {errors} errors ({MODEL})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
