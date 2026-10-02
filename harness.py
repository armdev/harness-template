#!/usr/bin/env python3
"""Harness runner. One manifest (harness.yaml), four verbs.

  run --stage S [--plane P] [--only ID]  execute sensors, write .harness/report.md for the agent
  selftest                               prove each sensor still fires on seeded defects
  coverage                               guides x sensors x categories; feedforward-only / feedback-only gaps
  stats                                  steering-loop data from the ledger: what fires, what never does

Only dependency: PyYAML. Same script runs in the harness container (static/live planes) and on the host.
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
TAIL = int(os.environ.get("HARNESS_TAIL_LINES", "60"))     # what the agent sees per failure
TIMEOUT = int(os.environ.get("HARNESS_TIMEOUT", "900"))
STAGES = ["pre-commit", "integration", "pipeline", "continuous"]


def manifest() -> dict:
    return yaml.safe_load((ROOT / "harness.yaml").read_text())


def git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return os.environ.get("GIT_COMMIT", "unknown")


def execute(cmd: str) -> tuple[str, int, str, float]:
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
        out, rc = (p.stdout + p.stderr).strip(), p.returncode
        status = "pass" if rc == 0 else "unavailable" if rc in (126, 127) else "fail"
    except subprocess.TimeoutExpired:
        out, rc, status = f"timed out after {TIMEOUT}s", -1, "timeout"
    return status, rc, out, time.monotonic() - t0


# ------------------------------------------------------------------ run
def cmd_run(a: argparse.Namespace) -> int:
    m = manifest()
    planes = {a.plane} if a.plane != "all" else {"static", "live", "host"}
    sensors = [s for s in m["sensors"]
               if a.stage in s["stages"] and s["plane"] in planes and (not a.only or s["id"] == a.only)]
    (OUT / "results").mkdir(parents=True, exist_ok=True)
    rev, blocking_failed = git_rev(), False

    for s in sensors:
        status, rc, out, dur = execute(s["run"])
        res = {"id": s["id"], "status": status, "rc": rc, "seconds": round(dur, 2), "rev": rev,
               "stage": a.stage, "plane": s["plane"], "kind": s["kind"], "category": s["category"],
               "blocking": s.get("blocking", True), "ts": int(time.time()),
               "output": "\n".join(out.splitlines()[-TAIL:])}
        (OUT / "results" / f"{s['id']}.json").write_text(json.dumps(res, ensure_ascii=False))
        with (OUT / "ledger.jsonl").open("a") as f:
            f.write(json.dumps({k: v for k, v in res.items() if k != "output"}) + "\n")
        mark = {"pass": "ok", "fail": "FAIL", "unavailable": "BLIND", "timeout": "TIMEOUT"}[status]
        print(f"[{mark:7}] {s['id']:22} {s['kind']:13} {dur:6.1f}s")
        if status != "pass" and res["blocking"]:
            blocking_failed = True

    write_report(m, a.stage)
    print(f"report: {OUT / 'report.md'}")
    return 1 if blocking_failed else 0


def write_report(m: dict, stage: str) -> None:
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
    missing = [sid for sid in by_id if sid not in {r["id"] for r in results}]

    lines = [f"# Harness report — stage `{stage}`, rev {git_rev()}", "",
             "Read this before your next change. Fix blocking failures first; advisory findings are judgement calls.", ""]
    for title, group in (("Blocking failures", [r for r in failed if r["blocking"]]),
                         ("Advisory findings", [r for r in failed if not r["blocking"]])):
        if group:
            lines += [f"## {title}", ""]
            for r in group:
                s = by_id[r["id"]]
                lines += [f"### {r['id']} ({r['kind']}, {r['category']})", "",
                          f"**How to fix:** {s.get('fix_hint', '-')}", "",
                          f"**Re-run only this:** `python harness/harness.py run --stage {stage} "
                          f"--plane {r['plane']} --only {r['id']}`", "", "```", r["output"], "```", ""]
    if blind:
        lines += ["## Blind sensors (not your code — the harness is broken)", ""]
        lines += [f"- `{r['id']}`: {r['status']} — {r['output'][:200]}" for r in blind] + [""]
    if missing:
        lines += ["## Not run in this stage yet", "", *[f"- `{x}` (plane {by_id[x]['plane']})" for x in missing], ""]
    lines += ["## Passed", "", ", ".join(f"`{r['id']}`" for r in passed) or "-", ""]
    (OUT / "report.md").write_text("\n".join(lines))


# ------------------------------------------------------------------ selftest
def cmd_selftest(_: argparse.Namespace) -> int:
    """A sensor that never fires is either a sign of quality or blindness; seeded defects tell which."""
    rc = 0
    for s in manifest()["sensors"]:
        st = s.get("selftest")
        if not st:
            print(f"[ skip  ] {s['id']:22} no seeded defects — firing ability unproven")
            continue
        for fx in sorted((ROOT / st["fixtures"]).iterdir()):
            first = fx.read_text().splitlines()[0]
            expect = first.split("expect:", 1)[1].strip() if "expect:" in first else None
            _, code, out, _ = execute(st["run"].format(fixture=fx))
            ok = code != 0 and (expect is None or expect in out)
            rc |= 0 if ok else 1
            print(f"[{'fires' if ok else 'BLIND':7}] {s['id']:22} {fx.name} (expect {expect})")
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
        row = [len(cells[(c, d, k)]) for d in ("guide", "sensor") for k in ("computational", "inferential")]
        print(f"{c:16}" + "".join(f"{n:>12}" for n in row[:2]) + f"{row[2]:>13}{row[3]:>12}")

    paired = {g for s in m["sensors"] for g in s.get("pairs_with", [])}
    problems = 0
    for gid, g in guides.items():
        if not (ROOT / g["path"]).exists():
            print(f"MISSING  guide {gid}: {g['path']} does not exist"); problems += 1
        if gid not in paired:
            print(f"FF-ONLY  guide {gid}: no sensor checks it — the rule is encoded but never verified")
    for s in m["sensors"]:
        if not s.get("pairs_with"):
            print(f"FB-ONLY  sensor {s['id']}: no guide teaches it — expect the agent to repeat the mistake")
        for g in s.get("pairs_with", []):
            if g not in guides:
                print(f"DANGLING sensor {s['id']} pairs with unknown guide {g}"); problems += 1
        if s.get("stages", [None])[0] not in STAGES:
            print(f"BAD      sensor {s['id']}: unknown stage"); problems += 1
    for c in m["categories"]:
        if not any(cells[(c, "sensor", k)] for k in ("computational", "inferential")):
            print(f"GAP      category {c}: no sensor at all"); problems += 1
    return 1 if problems else 0


# ------------------------------------------------------------------ stats
def cmd_stats(a: argparse.Namespace) -> int:
    p = OUT / "ledger.jsonl"
    if not p.exists():
        print("no ledger yet"); return 0
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
        hint = ("fires often: strengthen the paired guide" if rate > 0.3 else
                "never fired: run selftest, or demote/remove" if runs[sid] >= a.min_runs and fails[sid] == 0 else "")
        print(f"{sid:22}{runs[sid]:>6}{fails[sid]:>7}{rate:>7.0%}{blind[sid]:>7}{secs[sid] / runs[sid]:>8.1f}  {hint}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--stage", required=True, choices=STAGES)
    r.add_argument("--plane", default=os.environ.get("HARNESS_PLANE", "all"),
                   choices=["static", "live", "host", "all"])
    r.add_argument("--only")
    sub.add_parser("selftest")
    sub.add_parser("coverage")
    s = sub.add_parser("stats")
    s.add_argument("--min-runs", type=int, default=20)
    a = ap.parse_args()
    return {"run": cmd_run, "selftest": cmd_selftest, "coverage": cmd_coverage, "stats": cmd_stats}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
