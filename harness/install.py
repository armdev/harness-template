#!/usr/bin/env python3
"""Install air-harness into another project, with a manifest that fits that project.

  python3 harness/install.py <project> [--src DIR ...] [--migrations DIR] [--force]

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

Never overwrites the project's own files: AGENTS.md, CLAUDE.md, ruff configuration, .claude/settings.json and
.githooks are written only when missing (--force replaces the harness machinery itself, never those).
Then: make harness-coverage && make harness-selftest && make harness-fast — GREEN on a clean project.
"""
from __future__ import annotations

import argparse
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


def copy_tree(src: Path, dst: Path, force: bool, ignore=None) -> None:
    if dst.exists() and force:
        shutil.rmtree(dst)
    if not dst.exists():
        shutil.copytree(src, dst, ignore=ignore, symlinks=True)


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


def install(project: Path, src: list[str] | None, migrations: str | None, force: bool) -> list[str]:
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
        return skip & set(names)

    copy_tree(TEMPLATE / "harness", project / "harness", force, ignore=harness_ignore)
    for name in ("compose.harness.yml", "harness.mk"):
        if force or not (project / name).exists():
            shutil.copy2(TEMPLATE / name, project / name)
    (project / "harness.yaml").write_text(
        "# Harness manifest written by harness/install.py — every guide and sensor of this project.\n"
        "# Add sensors from the template manifest as the project grows (unit, contract, eval, prom-rules).\n"
        + yaml.safe_dump(manifest(project, src, migrations), sort_keys=False, width=120))
    created += ["harness/", "harness.yaml", "harness.mk", "compose.harness.yml"]

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
    ap.add_argument("--force", action="store_true", help="replace an installed harness/ (never the project's files)")
    a = ap.parse_args(argv)
    for line in install(a.project, a.src, a.migrations, a.force):
        print(f"  + {line}")
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
