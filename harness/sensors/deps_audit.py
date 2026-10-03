#!/usr/bin/env python3
"""Computational sensor: known-vulnerable pinned dependencies (pip-audit against the vulnerability database).

  deps_audit.py [PATH ...]   files are audited as given; directories are searched for requirements*.txt
                             (default: services/, libs/, tools/)

pip-audit exits 1 both when it found vulnerabilities and when it could not run at all (no network, a noexec /tmp,
no pip in the throwaway venv). Exit 1 only for the first; 126 for the second, so the runner reports the sensor
BLIND (a harness problem) instead of turning an environment error into findings about the code.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FOUND = "known vulnerabilit"          # "Found 3 known vulnerabilities in 1 package"
CANNOT_RUN = 126


def audit(path: str) -> int:
    cmd = ["pip-audit", "--progress-spinner", "off", "-r", path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603,S607 — fixed argv, image tool
    out = p.stdout + p.stderr
    print(f"== {path}\n{out.rstrip()}")
    if p.returncode == 0:
        return 0
    if FOUND in out:
        return 1
    print(f"deps-audit: pip-audit could not audit {path} (exit {p.returncode}); this is the environment, not the "
          "code", file=sys.stderr)
    return CANNOT_RUN


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [d for d in (Path("services"), Path("libs"), Path("tools")) if d.is_dir()]
    files = sorted(str(f) for p in paths for f in (p.rglob("requirements*.txt") if p.is_dir() else [p]))
    try:
        codes = [audit(f) for f in files]
    except FileNotFoundError:                           # pip-audit not installed in this image
        print("deps-audit: pip-audit not found", file=sys.stderr)
        return CANNOT_RUN
    return max(codes, default=0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
