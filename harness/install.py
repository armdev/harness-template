#!/usr/bin/env python3
"""Install air-harness into another project, with a manifest that fits that project.

  python3 harness/install.py <project> [--src DIR ...] [--migrations DIR] [--upgrade]

Copies the harness machinery (runner, sensors, rules, rubric, generic skills and prompts, hooks, make targets,
sensor containers) and writes a harness.yaml with the sensors that apply to the project as it is:

  always          ruff, semgrep-local (pre-commit, blocking) · review-agent (advisory) · dead-code, deps-audit (nightly)
  compose file    topology
  migrations dir  migrations (Flyway naming and history)
  `test:` target  unit (`make -s test`, integration stage) — without one, `behaviour` is left out of the categories
                  and the installer says so: no sensor checks behaviour yet

pointed at the project's source directories (--src, default: top-level directories that contain Python files).
Sensors that need the reference system (unit, contract, eval, prom-rules) are not installed: add your own
entries from the template manifest once the project has a test suite, a public API or alert rules.

Never overwrites the project's own files: harness.yaml, AGENTS.md, CLAUDE.md, ruff configuration,
.claude/settings.json, .githooks, the rubric, skills, prompts and any rule or fixture the project added are written
only when missing. Re-running adds what is missing and changes nothing else.

  --upgrade   replace the upstream-owned machinery (runner, sensors, hooks, harness tests, seeded defects, the
              organisation semgrep rules, harness.mk, compose.harness.yml) with this version, bump template.version
              in the project's harness.yaml, and print the upstream changes since its version and the sensors it
              could add. Then: make harness-build && make harness-selftest.
Then: make harness-coverage && make harness-selftest && make harness-fast — GREEN on a clean project.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parents[1]
GENERIC_GUIDES = ["agents-md", "skill-harness-report", "skill-harness-steer", "prompts", "review-rubric",
                  "semgrep-rules"]
GENERIC_SKILLS = ["harness-report", "harness-steer"]
REFERENCE_PROMPTS = ["02-first-endpoint.md", "03-schema-change.md", "04-new-service.md"]   # about the demo system
REFERENCE_FIXTURES = ["unit", "contract", "eval", "prom-rules"]
SKIP_DIRS = {"harness", ".git", ".harness", ".venv", "venv", "node_modules", "__pycache__", ".claude", ".githooks"}


def detect_src(project: Path) -> list[str]:
    return sorted(d.name for d in project.iterdir()
                  if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".") and any(d.rglob("*.py")))


def has_ruff_config(project: Path) -> bool:
    pyproject = project / "pyproject.toml"
    return ((project / "ruff.toml").exists() or (project / ".ruff.toml").exists()
            or (pyproject.exists() and "[tool.ruff" in pyproject.read_text()))


def has_test_target(project: Path) -> bool:
    makefile = project / "Makefile"
    return makefile.exists() and re.search(r"^test\s*:", makefile.read_text(), re.M) is not None


def manifest(project: Path, src: list[str], migrations: str | None) -> dict:
    tpl = yaml.safe_load((TEMPLATE / "harness.yaml").read_text())
    s = " ".join(src)
    runs = {
        "topology": None,                                      # template command as is
        "migrations": f"python harness/sensors/migrations_check.py {migrations}",
        "ruff": f"ruff check --output-format=concise {s}",
        "semgrep-local": "semgrep scan --config harness/rules/semgrep --error --metrics=off --disable-version-check "
                         f"--quiet --emacs {s}",
        "review-agent": f'REVIEW_SCOPE="{s}" python harness/sensors/review.py',
        "dead-code": f"vulture {s} harness/rules/vulture_whitelist.py --min-confidence 80",
        "deps-audit": f"python harness/sensors/deps_audit.py {s}",
        "unit": None,                                          # the project's own `make -s test`
    }
    if not (project / "docker-compose.yml").exists():
        runs.pop("topology")
    if not migrations:
        runs.pop("migrations")
    if not has_test_target(project):
        runs.pop("unit")
    sensors = []
    for sensor in tpl["sensors"]:
        if sensor["id"] not in runs:
            continue
        sensor = dict(sensor)
        if runs[sensor["id"]]:
            sensor["run"] = runs[sensor["id"]]
        sensor["pairs_with"] = [g for g in sensor.get("pairs_with", []) if g in GENERIC_GUIDES] or ["agents-md"]
        if sensor["id"] == "unit":                             # the template's mutants target its own libs/common
            sensor.pop("selftest", None)
            sensor["fix_hint"] = "Fix the code; change a test only together with the behaviour it specifies."
        sensors.append(sensor)
    categories = sorted({s["category"] for s in sensors}, key=tpl["categories"].index)
    guides = []
    for guide in tpl["guides"]:
        if guide["id"] in GENERIC_GUIDES:
            guides.append(dict(guide, category=[c for c in guide["category"] if c in categories]))
    return {
        "harness": tpl["harness"],
        "template": {"name": project.resolve().name, "version": tpl["template"]["version"],
                     "from": tpl["template"]["name"]},
        "categories": categories,
        "guides": guides,
        "sensors": sensors,
    }


# Upstream-owned: replaced on --upgrade. Everything else under harness/ (rubric, skills, prompts, the project's own
# rules and fixtures, vulture whitelist) belongs to the project once installed: added when missing, never replaced.
MACHINERY = ("harness.py", "Dockerfile", "HARNESS.md", "CHANGELOG.md", "sensors/*.py", "hooks/*", "tests/*",
             "sensors/fixtures/**", "rules/semgrep/python.yml", "console/**")


def upstream_owned(rel: Path) -> bool:
    return any(rel.match(p) or (p.endswith("/**") and rel.is_relative_to(p[:-3])) for p in MACHINERY)


def sync_tree(src: Path, dst: Path, ignore, upgrade: bool) -> tuple[list[str], list[str]]:
    """Copy src into dst: missing files always; upstream-owned files also when upgrading. Returns (added, updated)."""
    added, updated = [], []
    for root, dirs, files in os.walk(src):                         # os.walk: Path.walk needs Python 3.12
        directory = Path(root)
        skipped = ignore(root, dirs + files)
        dirs[:] = [d for d in dirs if d not in skipped]
        for name in files:
            if name in skipped:
                continue
            rel = (directory / name).relative_to(src)
            target = dst / rel
            if not target.exists():
                added.append(str(rel))
            elif upgrade and upstream_owned(rel) and target.read_bytes() != (directory / name).read_bytes():
                updated.append(str(rel))
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / name, target)
    return added, updated


def upgrade_report(project: Path, src: list[str], migrations: str | None) -> list[str]:
    """Bump the project's template.version; list upstream changes since its version and sensors it does not use."""
    path = project / "harness.yaml"
    text = path.read_text()
    mine = yaml.safe_load(text)
    old, new = str(mine["template"]["version"]), str(yaml.safe_load((TEMPLATE / "harness.yaml").read_text())
                                                     ["template"]["version"])
    lines = []
    if old != new:
        path.write_text(re.sub(rf"(\n\s+version:\s*){re.escape(old)}\b", rf"\g<1>{new}", text, count=1))
        lines.append(f"harness.yaml: template.version {old} -> {new}")
        changelog = (TEMPLATE / "harness" / "CHANGELOG.md").read_text()
        sections = re.split(r"(?m)^## ", changelog)[1:]
        newer = [sec.splitlines()[0].strip() for sec in sections]
        newer = newer[:newer.index(old)] if old in newer else newer
        if newer:
            lines.append("upstream changes since " + old + ": " + ", ".join(newer) + " (harness/CHANGELOG.md)")
    have = {s["id"] for s in mine["sensors"]}
    for sensor in manifest(project, src, migrations)["sensors"]:
        if sensor["id"] not in have:
            lines.append(f"available sensor not in your manifest: {sensor['id']} ({sensor['run']})")
    return lines


def copy_if_missing(src: Path, dst: Path, created: list[str], project: Path) -> None:
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        created.append(str(dst.relative_to(project)))


def append_line(path: Path, line: str) -> bool:
    text = path.read_text() if path.exists() else ""
    if line in text.splitlines():
        return False
    path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")
    return True


def install(project: Path, src: list[str] | None, migrations: str | None, upgrade: bool = False) -> list[str]:
    project = project.resolve()
    if not project.is_dir():
        raise SystemExit(f"install: {project} is not a directory")
    if project == TEMPLATE:
        raise SystemExit("install: that is the template itself")
    src = src or detect_src(project)
    if not src:
        raise SystemExit("install: no source directory with Python files found; pass --src DIR")
    if migrations is None and (project / "db" / "migrations").is_dir():
        migrations = "db/migrations"
    created: list[str] = []

    def harness_ignore(directory: str, names: list[str]) -> set[str]:
        d = Path(directory)
        skip = {"__pycache__", ".pytest_cache"}
        if d == TEMPLATE / "harness" / "skills":
            skip |= {n for n in names if n not in GENERIC_SKILLS}
        if d == TEMPLATE / "harness" / "prompts" / "next-steps":
            skip |= set(REFERENCE_PROMPTS)
        if d == TEMPLATE / "harness" / "sensors" / "fixtures":
            skip |= set(REFERENCE_FIXTURES) | ({"migrations"} if not migrations else set())
        if d == TEMPLATE / "harness":
            skip |= {"install.py", "templates"}
        if d == TEMPLATE / "harness" / "tests":
            skip |= {"test_install.py"}                         # tests the installer, which stays upstream
        return skip & set(names)

    added, updated = sync_tree(TEMPLATE / "harness", project / "harness", harness_ignore, upgrade)
    created += [f"harness/{f}" for f in added] if len(added) <= 5 else [f"harness/ ({len(added)} files)"]
    created += [f"harness/{f} (upgraded)" for f in updated]
    for name in ("compose.harness.yml", "harness.mk"):                  # upstream-owned
        target = project / name
        if not target.exists() or (upgrade and target.read_bytes() != (TEMPLATE / name).read_bytes()):
            created.append(name + (" (upgraded)" if target.exists() else ""))
            shutil.copy2(TEMPLATE / name, target)
    if not (project / "harness.yaml").exists():                        # the project's manifest: never replaced
        (project / "harness.yaml").write_text(
            "# Harness manifest written by harness/install.py — every guide and sensor of this project.\n"
            "# Add sensors from the template manifest as the project grows (unit, contract, eval, prom-rules).\n"
            + yaml.safe_dump(manifest(project, src, migrations), sort_keys=False, width=120))
        created.append("harness.yaml")

    tpl = TEMPLATE / "harness" / "templates"
    copy_if_missing(tpl / "AGENTS.md", project / "AGENTS.md", created, project)
    copy_if_missing(tpl / "CLAUDE.md", project / "CLAUDE.md", created, project)
    copy_if_missing(TEMPLATE / ".claude" / "settings.json", project / ".claude" / "settings.json", created, project)
    copy_if_missing(TEMPLATE / ".githooks" / "pre-commit", project / ".githooks" / "pre-commit", created, project)
    if not has_ruff_config(project):
        copy_if_missing(tpl / "ruff.toml", project / "ruff.toml", created, project)
    skills = project / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for name in GENERIC_SKILLS:
        link = skills / name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(Path("..") / ".." / "harness" / "skills" / name)
    if append_line(project / "Makefile", "include harness.mk"):
        created.append("Makefile: include harness.mk")
    if append_line(project / ".gitignore", ".harness/"):
        created.append(".gitignore: .harness/")
    return created


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="install.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--src", nargs="+", help="source directories the sensors check (default: detected)")
    ap.add_argument("--migrations", help="Flyway migrations directory (default: db/migrations if present)")
    ap.add_argument("--upgrade", action="store_true",
                    help="replace the upstream-owned machinery with this version; keeps the manifest, rubric, skills, "
                         "prompts and the project's own rules")
    a = ap.parse_args(argv)
    for line in install(a.project, a.src, a.migrations, a.upgrade):
        print(f"  + {line}")
    if a.upgrade:
        project = a.project.resolve()
        for line in upgrade_report(project, a.src or detect_src(project),
                                   a.migrations or ("db/migrations" if (project / "db" / "migrations").is_dir()
                                                    else None)):
            print(f"  ~ {line}")
    if not has_test_target(a.project):
        print("\n  ! no `test:` target in the Makefile: no sensor checks behaviour yet. Add one, then a `unit` sensor\n"
              "    to harness.yaml (stages: [integration, pipeline], run: make -s test) and `behaviour` to categories.")
    print(f"\nair-harness installed in {a.project.resolve()}. Next:\n"
          "  make harness-coverage && make harness-selftest && make harness-fast   # GREEN on a clean project\n"
          "  git config core.hooksPath .githooks                                   # blocking sensors before commit\n"
          "Then read AGENTS.md and harness/HARNESS.md; add unit / contract / eval sensors as the project grows.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
