#!/usr/bin/env python3
"""Seeded defects for test suites: apply one mutant to a copy of the code and run the suite that must catch it.

  mutate.py <fixture dir>     the dir holds .expect (first line `# expect: <text>`) and mutant.yml:
                              {target: unit | gateway, file: <path in the target>, find: <exact text>, replace: <text>}

  target unit     a copy of libs/common, mounted into the `unit` container (unit tests)
  target gateway  a copy of services/gateway, run as a second gateway next to the running stack; the `contract`
                  container is pointed at it (stack up)

A suite that still passes with the mutant applied does not guard that behaviour: selftest reports the sensor
BLIND. Exit 126 when the mutant no longer applies (the code moved on; update the fixture), so a stale mutant is a
harness problem, never a pass. Host plane: docker compose.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"unit": ROOT / "libs" / "common", "gateway": ROOT / "services" / "gateway"}
LIB = SOURCES["unit"]
STALE = 126
COMPOSE = ["docker", "compose"]


def compose(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run([*COMPOSE, *args], cwd=ROOT, check=check,  # noqa: S603 — fixed argv
                          capture_output=args[0] == "ps", text=True)


def mutated_copy(m: dict, source: Path, tmp: str) -> Path | None:
    copy = Path(tmp) / source.name
    shutil.copytree(source, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    target = copy / m["file"]
    src = target.read_text()
    if src.count(m["find"]) != 1:
        print(f"mutant: `find` occurs {src.count(m['find'])}x in {m['file']} (need exactly 1)", file=sys.stderr)
        return None
    target.write_text(src.replace(m["find"], m["replace"]))
    for p in [copy, *copy.rglob("*")]:                  # the services run as uid 10001
        p.chmod(0o755 if p.is_dir() else 0o644)
    Path(tmp).chmod(0o755)
    return copy


def run_unit(copy: Path) -> int:
    return compose("--profile", "tools", "run", "--rm", "-T", "-v", f"{copy}:/repo/libs/common:ro", "unit").returncode


def run_gateway(copy: Path) -> int:
    name = f"air-harness-mutant-gateway-{os.getpid()}"
    started = compose("run", "-d", "--rm", "--no-deps", "--name", name, "-v", f"{copy}:/app:ro", "gateway")
    if started.returncode != 0:
        return STALE
    try:
        for _ in range(60):                              # the image's HEALTHCHECK says when it serves
            state = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name],  # noqa: S603,S607
                                   capture_output=True, text=True, check=False).stdout.strip()
            if state == "healthy":
                break
            time.sleep(1)
        else:
            print(f"mutant gateway {name} never became healthy", file=sys.stderr)
            return STALE
        return compose("--profile", "tools", "run", "--rm", "-T", "-e", f"GATEWAY_URL=http://{name}:8000",
                       "contract").returncode
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603,S607


def main(fixture: str) -> int:
    m = yaml.safe_load((Path(fixture) / "mutant.yml").read_text())
    kind = m.get("target", "unit")
    source = LIB if kind == "unit" else SOURCES[kind]
    with tempfile.TemporaryDirectory(prefix="air-harness-mutant-") as tmp:
        copy = mutated_copy(m, source, tmp)
        if copy is None:
            return STALE
        return run_unit(copy) if kind == "unit" else run_gateway(copy)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
