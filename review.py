#!/usr/bin/env python3
"""Inferential sensor: review the diff against the same rubric the coding agent was given.

OpenAI-compatible endpoint (vLLM, Ollama, ...). Stdlib only. Exit 1 if the reviewer reports an ERROR.
Advisory in harness.yaml until its precision on real diffs has been measured.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:11434/v1").rstrip("/")
MODEL = os.environ.get("REVIEW_MODEL") or os.environ.get("LLM_MODEL", "qwen3:8b")
KEY = os.environ.get("LLM_API_KEY", "not-needed")
NO_THINK = os.environ.get("LLM_NO_THINK", "true").lower() == "true"
DIFF_BASE = os.environ.get("REVIEW_DIFF_BASE", "")          # empty: staged changes; else e.g. origin/main
MAX_DIFF = int(os.environ.get("REVIEW_MAX_DIFF_CHARS", "60000"))

SYSTEM = """You are a code reviewer acting as a feedback sensor for a coding agent.
Review ONLY the diff. Apply ONLY the rubric. Do not restate style issues a linter would catch.
Reply with JSON only, no prose, no code fences:
{"findings":[{"severity":"ERROR|WARN","rule":"<rubric id>","file":"<path>","line":<int|null>,
"what":"<one sentence>","fix":"<one concrete instruction the agent can execute>"}]}
Use ERROR only when the rubric marks the rule as blocking and the diff clearly violates it.
An empty list is a valid and common answer."""


def main() -> int:
    args = ["git", "diff", "--unified=5"] + ([DIFF_BASE] if DIFF_BASE else ["--cached"])
    diff = subprocess.run(args, capture_output=True, text=True).stdout
    if not diff.strip():
        print("review: empty diff, nothing to review")
        return 0
    truncated = len(diff) > MAX_DIFF
    rubric = Path("harness/review/RUBRIC.md").read_text()
    body = {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"RUBRIC:\n{rubric}\n\nDIFF{' (truncated)' if truncated else ''}:\n{diff[:MAX_DIFF]}"},
        ],
    }
    if NO_THINK:
        body["chat_template_kwargs"] = {"enable_thinking": False}   # vLLM/Qwen3; other servers ignore it
    req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
    except Exception as e:                       # 127 => the runner reports the sensor as BLIND, not as a code failure
        print(f"review: LLM unreachable at {BASE}: {e}")
        return 127
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        findings = json.loads(text).get("findings", [])
    except json.JSONDecodeError:
        print(f"review: reviewer returned non-JSON (sensor noise, not a code failure):\n{text[:500]}")
        return 127
    for f in findings:
        print(f"{f.get('severity', 'WARN'):5} {f.get('rule', '?'):12} {f.get('file', '?')}:{f.get('line') or '-'}\n"
              f"      what: {f.get('what', '')}\n      fix:  {f.get('fix', '')}")
    if truncated:
        print(f"review: diff truncated to {MAX_DIFF} chars — split the change")
    errors = sum(f.get("severity") == "ERROR" for f in findings)
    print(f"review: {len(findings)} findings, {errors} errors ({MODEL})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
