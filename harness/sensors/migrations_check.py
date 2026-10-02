#!/usr/bin/env python3
"""Migrations sensor: Flyway files are append-only history. Computational, no network, PyYAML-free.

Rules
  M1 naming          V<n>__<snake_case>.sql or R__<snake_case>.sql; nothing else in the directory
  M2 unique-version  each version number appears once
  M3 append-only     a committed V-migration is never edited or deleted (it has already run somewhere);
                     compared against MIGRATIONS_BASE (default HEAD; CI: origin/main). Skipped outside git.
  M4 granted         a CREATE TABLE is followed by a GRANT on that table in the same file, otherwise no
                     service role (<name>_svc) can use it
  M5 no-gaps         versions are contiguous (WARN: a gap usually means a lost or renumbered file)

  python harness/sensors/migrations_check.py db/migrations [--strict]
Exit code: 1 if any error (or any finding with --strict), else 0.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

NAME_RE = re.compile(r"^(?:V(?P<v>\d+)|R)__[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")
TABLE_RE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_.\"]+)", re.I)
GRANT_RE = re.compile(r"grant\s+[^;]*?\s+on\s+(?:table\s+)?([^;]*?)\s+to\s", re.I | re.S)

findings: list[tuple[str, str, str, str, str]] = []


def report(sev: str, rule: str, where: str, msg: str, fix: str) -> None:
    findings.append((sev, rule, where, msg, fix))


def changed_committed(directory: Path) -> list[tuple[str, str]]:
    """(status, path) of migrations changed relative to the base revision; empty outside a git work tree."""
    base = os.environ.get("MIGRATIONS_BASE", "HEAD")
    try:
        out = subprocess.run(["git", "diff", "--name-status", base, "--", str(directory)],  # noqa: S603,S607
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [tuple(line.split("\t")[:2]) for line in out.stdout.splitlines() if "\t" in line]


def main(directory: str, strict: bool = False) -> int:
    d = Path(directory)
    files = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
    versions: dict[int, list[str]] = {}

    for p in files:
        m = NAME_RE.match(p.name)
        if not m:
            report("ERROR", "M1 naming", str(p),
                   f"'{p.name}' is not a Flyway migration name, so Flyway ignores it or fails",
                   "rename to V<next number>__<snake_case>.sql (versioned) or R__<snake_case>.sql (repeatable)")
            continue
        if m.group("v"):
            versions.setdefault(int(m.group("v")), []).append(p.name)
        sql = re.sub(r"--[^\n]*", "", p.read_text())
        granted = {t.strip().strip('"').lower() for g in GRANT_RE.findall(sql) for t in g.split(",")}
        for table in TABLE_RE.findall(sql):
            if table.strip('"').lower() not in granted:
                report("ERROR", "M4 granted", str(p),
                       f"table {table} is created without a GRANT, so no service role can use it",
                       f"add 'GRANT SELECT[, INSERT, UPDATE] ON {table} TO <service>_svc;' in the same file")

    for v, names in sorted(versions.items()):
        if len(names) > 1:
            report("ERROR", "M2 unique-version", str(d),
                   f"version {v} is used by {', '.join(names)}",
                   "renumber the newer file to the next free version")
    if versions:
        missing = sorted(set(range(1, max(versions) + 1)) - set(versions))
        if missing:
            report("WARN", "M5 no-gaps", str(d), f"versions {missing} are missing",
                   "check no migration was lost; renumber only files that have never been merged")

    for status, path in changed_committed(d):
        if Path(path).name.startswith("V") and status[0] in "MD":
            report("ERROR", "M3 append-only", path,
                   f"committed migration {Path(path).name} was {'edited' if status[0] == 'M' else 'deleted'}; "
                   f"databases that already ran it will not see the change (and Flyway validation fails)",
                   f"restore it (git checkout -- {path}) and put the change in a new V<next>__*.sql")

    order = {"ERROR": 0, "WARN": 1}
    for sev, rule, where, msg, fix in sorted(findings, key=lambda f: (order[f[0]], f[1], f[2])):
        print(f"{sev:5} {rule:18} {where}\n      what: {msg}\n      fix:  {fix}")
    errors = sum(1 for f in findings if f[0] == "ERROR")
    print(f"migrations: {len(files)} files, {errors} errors, {len(findings) - errors} warnings")
    return 1 if errors or (strict and findings) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--strict"]
    sys.exit(main(args[0] if args else "db/migrations", strict="--strict" in sys.argv[1:]))
