#!/usr/bin/env python3
"""Seeded defects for test suites: apply one mutant to a copy of libs/common and run the unit tests on it.

  mutate.py <fixture dir>     the dir holds .expect (first line `# expect: <text>`) and mutant.yml:
                              {file: common/<module>.py, find: <exact text>, replace: <text>}

A suite that still passes with the mutant applied does not guard that behaviour: selftest reports the `unit`
sensor BLIND. Exit 126 when the mutant no longer applies (the code moved on; update the fixture), so a stale
mutant is reported as a harness problem, never as a pass. Host plane: runs the `unit` container (docker compose).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "libs" / "common"
STALE = 126


def main(fixture: str) -> int:
    m = yaml.safe_load((Path(fixture) / "mutant.yml").read_text())
    with tempfile.TemporaryDirectory(prefix="air-harness-mutant-") as tmp:
        copy = Path(tmp) / "common"
        shutil.copytree(LIB, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        target = copy / m["file"]
        src = target.read_text()
        if src.count(m["find"]) != 1:
            print(f"mutant {fixture}: `find` occurs {src.count(m['find'])}x in {m['file']} (need exactly 1)",
                  file=sys.stderr)
            return STALE
        target.write_text(src.replace(m["find"], m["replace"]))
        cmd = ["docker", "compose", "--profile", "tools", "run", "--rm", "-T",
               "-v", f"{copy}:/repo/libs/common:ro", "unit"]
        return subprocess.run(cmd, cwd=ROOT, check=False).returncode  # noqa: S603,S607 — fixed argv


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
