#!/usr/bin/env python3
"""Harness runner. One manifest (harness.yaml), five verbs.

  run --stage S [--plane P] [--only ID]  execute sensors, write .harness/report.md for the agent
  selftest [--only ID]                   prove each sensor still fires on seeded defects (and stays quiet on clean ones)
  coverage                               guides x sensors x categories; feedforward-only / feedback-only gaps
  stats [--min-runs N]                   steering-loop data from the ledger: what fires, what never does
  list                                   every sensor with its stage, plane and command (what the agent can run)

Only dependency: PyYAML. Same script runs in the harness container (static/live planes) and on the host.
Exit codes: run 1 = a blocking sensor failed or is blind; selftest 1 = a sensor is blind; coverage 1 = manifest
is inconsistent; 2 = usage error; 3 = run --only names a sensor of another plane.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("HARNESS_ROOT", ".")).resolve()
OUT = Path(os.environ.get("HARNESS_OUT", ROOT / ".harness"))
MANIFEST = Path(os.environ.get("HARNESS_MANIFEST", "harness.yaml"))
TAIL = int(os.environ.get("HARNESS_TAIL_LINES", "60"))     # what the agent sees per failure
TIMEOUT = int(os.environ.get("HARNESS_TIMEOUT", "900"))
STAGES = ["pre-commit", "integration", "pipeline", "continuous"]
PLANES = ["static", "live", "host"]
KINDS = ["computational", "inferential"]
MARK = {"pass": "ok", "fail": "FAIL", "unavailable": "BLIND", "timeout": "TIMEOUT"}


def manifest() -> dict:
    return yaml.safe_load((ROOT / MANIFEST).read_text())


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,  # noqa: S607
                             text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    return rev or os.environ.get("GIT_COMMIT", "unknown")


def execute(cmd: str) -> tuple[str, int, str, float]:
    """Run a manifest command. 126/127 (cannot execute / not found) mean the sensor is blind, not the code bad."""
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True,  # noqa: S602 — manifest is trusted
                           timeout=TIMEOUT)
        out, rc = (p.stdout + p.stderr).strip(), p.returncode
        status = "pass" if rc == 0 else "unavailable" if rc in (126, 127) else "fail"
    except subprocess.TimeoutExpired:
        out, rc, status = f"timed out after {TIMEOUT}s", -1, "timeout"
    return status, rc, out, time.monotonic() - t0


def warnings_in(output: str) -> list[str]:
    """Sensor convention: a line starting with WARN is advice that does not fail the sensor."""
    lines = output.splitlines()
    return ["\n".join([ln, *[x for x in lines[i + 1:i + 3] if x.startswith("      ")]])
            for i, ln in enumerate(lines) if ln.startswith("WARN")]


# ------------------------------------------------------------------ run
def cmd_run(a: argparse.Namespace) -> int:
    m = manifest()
    ids = {s["id"] for s in m["sensors"]}
    if a.only and a.only not in ids:
        print(f"unknown sensor '{a.only}'; known: {', '.join(sorted(ids))}", file=sys.stderr)
        return 2
    planes = set(PLANES) if a.plane == "all" else {a.plane}
    if a.only:
        plane = next(s["plane"] for s in m["sensors"] if s["id"] == a.only)
        if plane not in planes:
            print(f"sensor '{a.only}' runs on plane {plane}, not {a.plane}", file=sys.stderr)
            return 3
    sensors = [s for s in m["sensors"]
               if a.stage in s["stages"] and s["plane"] in planes and (not a.only or s["id"] == a.only)]
    (OUT / "results").mkdir(parents=True, exist_ok=True)
    rev, blocking_failed = git_rev(), False

    if not sensors:
        print(f"no sensors for stage {a.stage} on plane {a.plane}")
    for s in sensors:
        status, rc, out, dur = execute(s["run"])
        res = {"id": s["id"], "status": status, "rc": rc, "seconds": round(dur, 2), "rev": rev,
               "stage": a.stage, "plane": s["plane"], "kind": s["kind"], "category": s["category"],
               "blocking": s.get("blocking", True), "ts": int(time.time()),
               "output": "\n".join(out.splitlines()[-TAIL:]), "warnings": warnings_in(out)}
        (OUT / "results" / f"{s['id']}.json").write_text(json.dumps(res, ensure_ascii=False))
        with (OUT / "ledger.jsonl").open("a") as f:
            f.write(json.dumps({k: v for k, v in res.items() if k not in ("output", "warnings")}) + "\n")
        print(f"[{MARK[status]:7}] {s['id']:22} {s['kind']:13} {dur:6.1f}s")
        if status != "pass" and res["blocking"]:
            blocking_failed = True

    write_report(m, a.stage, rev)
    print(f"report: {OUT / 'report.md'}")
    return 1 if blocking_failed else 0


def write_report(m: dict, stage: str, rev: str) -> None:
    """Union of the latest result of every sensor in this stage (planes run separately, one report)."""
    by_id = {s["id"]: s for s in m["sensors"] if stage in s["stages"]}
    results = []
    for sid in by_id:
        p = OUT / "results" / f"{sid}.json"
        if p.exists():
            r = json.loads(p.read_text())
            if r["stage"] == stage:
                results.append(r)
    failed = [r for r in results if r["status"] == "fail"]
    blind = [r for r in results if r["status"] in ("unavailable", "timeout")]
    passed = [r for r in results if r["status"] == "pass"]
    warned = [r for r in passed if r.get("warnings")]
    missing = [sid for sid in by_id if sid not in {r["id"] for r in results}]

    def stale(r: dict) -> str:
        return f" — stale: from rev {r['rev']}, re-run it" if r["rev"] != rev else ""

    def rerun(r: dict) -> str:
        if r["plane"] == "host":
            return f"`python3 harness/harness.py run --stage {stage} --plane host --only {r['id']}`"
        service = "harness" if r["plane"] == "static" else "harness-live"
        return f"`make harness-one s={r['id']}{'' if stage == 'pre-commit' else f' stage={stage}'}` " \
               f"(container `{service}`)"

    blocking = [r for r in failed if r["blocking"]] + [r for r in blind if r["blocking"]]
    verdict = "RED — fix the blocking failures below before anything else" if blocking else "GREEN"
    lines = [f"# Harness report — stage `{stage}`, rev {rev}: {verdict}", "",
             "Read this before your next change. Fix blocking failures first, one sensor at a time, re-running only",
             "that sensor; advisory findings are judgement calls. Playbook: `harness/skills/harness-report/SKILL.md`.",
             ""]
    for title, group in (("Blocking failures", [r for r in failed if r["blocking"]]),
                         ("Advisory findings", [r for r in failed if not r["blocking"]])):
        if group:
            lines += [f"## {title}", ""]
            for r in group:
                s = by_id[r["id"]]
                lines += [f"### {r['id']} ({r['kind']}, {r['category']}){stale(r)}", "",
                          f"**How to fix:** {s.get('fix_hint', '-')}", "",
                          f"**Guides:** {', '.join(guide_paths(m, s)) or '-'}", "",
                          f"**Re-run only this:** {rerun(r)}", "", "```", r["output"], "```", ""]
    if blind:
        lines += ["## Blind sensors (not your code — the harness is broken; report it, do not work around it)", ""]
        lines += [f"- `{r['id']}`: {r['status']}{stale(r)} — {r['output'][:300]}" for r in blind] + [""]
    if warned:
        lines += ["## Warnings (sensor passed; fix if your change caused them)", ""]
        for r in warned:
            lines += [f"### {r['id']}", "", "```", *r["warnings"], "```", ""]
    if missing:
        lines += ["## Not run in this stage yet", "", *[f"- `{x}` (plane {by_id[x]['plane']})" for x in missing], ""]
    lines += ["## Passed", "", ", ".join(f"`{r['id']}`{' (stale)' if stale(r) else ''}" for r in passed) or "-", ""]
    (OUT / "report.md").write_text("\n".join(lines))


def guide_paths(m: dict, sensor: dict) -> list[str]:
    guides = {g["id"]: g["path"] for g in m["guides"]}
    return [f"`{guides[g]}`" for g in sensor.get("pairs_with", []) if g in guides]


# ------------------------------------------------------------------ selftest
def fixture_expectation(fx: Path) -> str | None:
    """First line `# expect: <text>` (the sensor must fail and print <text>) or `# expect: clean` (must pass).
    A fixture may be a directory; its expectation is then the first line of the .expect file inside it."""
    src = fx / ".expect" if fx.is_dir() else fx
    first = (src.read_text().splitlines() or [""])[0] if src.exists() else ""
    return first.split("expect:", 1)[1].strip() if "expect:" in first else None


def cmd_selftest(a: argparse.Namespace) -> int:
    """A sensor that never fires is either a sign of quality or blindness; seeded defects tell which."""
    rc = 0
    for s in manifest()["sensors"]:
        if a.only and s["id"] != a.only:
            continue
        st = s.get("selftest")
        if not st:
            print(f"[ skip  ] {s['id']:22} no seeded defects — firing ability unproven")
            continue
        fixtures = sorted(f for f in (ROOT / st["fixtures"]).iterdir() if not f.name.startswith("."))
        if not fixtures:
            print(f"[ BLIND ] {s['id']:22} fixture directory {st['fixtures']} is empty")
            rc = 1
        for fx in fixtures:
            expect = fixture_expectation(fx)
            _, code, out, _ = execute(st["run"].format(fixture=fx.relative_to(ROOT)))
            if expect == "clean":
                ok, label = code == 0, "quiet" if code == 0 else "NOISY"
            else:
                ok = code not in (0, 126, 127) and (expect is None or expect in out)
                label = "fires" if ok else "BLIND"
            rc |= 0 if ok else 1
            print(f"[{label:7}] {s['id']:22} {fx.name} (expect {expect})")
            if not ok:
                print("          " + "\n          ".join(out.splitlines()[-8:]))
    return rc


# ------------------------------------------------------------------ coverage
def cmd_coverage(_: argparse.Namespace) -> int:
    m = manifest()
    guides = {g["id"]: g for g in m["guides"]}
    cells: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for g in m["guides"]:
        for c in g["category"]:
            cells[(c, "guide", g["kind"])].append(g["id"])
    for s in m["sensors"]:
        cells[(s["category"], "sensor", s["kind"])].append(s["id"])

    print(f"{'category':16}{'guide/comp':>12}{'guide/inf':>12}{'sensor/comp':>13}{'sensor/inf':>12}")
    for c in m["categories"]:
        row = [len(cells[(c, d, k)]) for d in ("guide", "sensor") for k in KINDS]
        print(f"{c:16}" + "".join(f"{n:>12}" for n in row[:2]) + f"{row[2]:>13}{row[3]:>12}")
    print()

    paired = {g for s in m["sensors"] for g in s.get("pairs_with", [])}
    problems = 0

    def problem(msg: str) -> None:
        nonlocal problems
        print(msg)
        problems += 1

    for gid, g in guides.items():
        if not (ROOT / g["path"]).exists():
            problem(f"MISSING  guide {gid}: {g['path']} does not exist")
        if g["kind"] not in KINDS or not set(g["category"]) <= set(m["categories"]):
            problem(f"BAD      guide {gid}: unknown kind or category")
        if gid not in paired:
            print(f"FF-ONLY  guide {gid}: no sensor checks it — the rule is encoded but never verified")
    seen: set[str] = set()
    for s in m["sensors"]:
        sid = s["id"]
        if sid in seen:
            problem(f"DUP      sensor {sid}: id used twice")
        seen.add(sid)
        if not s.get("pairs_with"):
            print(f"FB-ONLY  sensor {sid}: no guide teaches it — expect the agent to repeat the mistake")
        for g in s.get("pairs_with", []):
            if g not in guides:
                problem(f"DANGLING sensor {sid} pairs with unknown guide {g}")
        if not s.get("stages") or not set(s["stages"]) <= set(STAGES):
            problem(f"BAD      sensor {sid}: stages {s.get('stages')} not in {STAGES}")
        if s.get("plane") not in PLANES:
            problem(f"BAD      sensor {sid}: plane {s.get('plane')} not in {PLANES}")
        if s.get("kind") not in KINDS or s.get("category") not in m["categories"]:
            problem(f"BAD      sensor {sid}: unknown kind or category")
        if s.get("kind") == "inferential" and s.get("blocking", True):
            print(f"RISK     sensor {sid}: inferential and blocking — is its precision measured?")
        st = s.get("selftest")
        if st and not (ROOT / st["fixtures"]).is_dir():
            problem(f"MISSING  sensor {sid}: selftest fixtures {st['fixtures']} do not exist")
        elif not st and s.get("kind") == "computational" and s.get("plane") == "static":
            print(f"UNPROVEN sensor {sid}: no seeded defects; selftest cannot tell quiet from blind")
    for c in m["categories"]:
        if not any(cells[(c, "sensor", k)] for k in KINDS):
            problem(f"GAP      category {c}: no sensor at all")
    print(f"\ncoverage: {len(guides)} guides, {len(m['sensors'])} sensors, {problems} problems")
    return 1 if problems else 0


# ------------------------------------------------------------------ stats
def cmd_stats(a: argparse.Namespace) -> int:
    p = OUT / "ledger.jsonl"
    if not p.exists():
        print("no ledger yet — run some stages first")
        return 0
    runs, fails, blind, secs = Counter(), Counter(), Counter(), defaultdict(float)
    for line in p.read_text().splitlines():
        r = json.loads(line)
        runs[r["id"]] += 1
        secs[r["id"]] += r["seconds"]
        fails[r["id"]] += r["status"] == "fail"
        blind[r["id"]] += r["status"] in ("unavailable", "timeout")
    print(f"{'sensor':22}{'runs':>6}{'fired':>7}{'rate':>7}{'blind':>7}{'avg s':>8}  steer")
    for sid in sorted(runs, key=lambda x: -fails[x] / runs[x]):
        rate = fails[sid] / runs[sid]
        hint = ("blind too often: fix the sensor's environment" if blind[sid] / runs[sid] > 0.2 else
                "fires often: strengthen the paired guide" if rate > 0.3 else
                "never fired: run selftest, or demote/remove" if runs[sid] >= a.min_runs and fails[sid] == 0 else "")
        print(f"{sid:22}{runs[sid]:>6}{fails[sid]:>7}{rate:>7.0%}{blind[sid]:>7}{secs[sid] / runs[sid]:>8.1f}  {hint}")
    return 0


# ------------------------------------------------------------------ list
def cmd_list(_: argparse.Namespace) -> int:
    for s in manifest()["sensors"]:
        flag = "blocking" if s.get("blocking", True) else "advisory"
        print(f"{s['id']:22} {','.join(s['stages']):26} {s['plane']:7} {flag:9} {s['run'].strip()[:90]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--stage", required=True, choices=STAGES)
    r.add_argument("--plane", default=os.environ.get("HARNESS_PLANE", "all"), choices=[*PLANES, "all"])
    r.add_argument("--only")
    st = sub.add_parser("selftest")
    st.add_argument("--only")
    sub.add_parser("coverage")
    s = sub.add_parser("stats")
    s.add_argument("--min-runs", type=int, default=20)
    sub.add_parser("list")
    a = ap.parse_args()
    verbs = {"run": cmd_run, "selftest": cmd_selftest, "coverage": cmd_coverage, "stats": cmd_stats, "list": cmd_list}
    return verbs[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
