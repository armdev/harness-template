import argparse
import json

import yaml

MANIFEST = {
    "harness": 1,
    "categories": ["maintainability"],
    "guides": [{"id": "g", "path": "GUIDE.md", "kind": "inferential", "category": ["maintainability"]}],
    "sensors": [
        {"id": "passes", "kind": "computational", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "run": "echo fine", "pairs_with": ["g"]},
        {"id": "fails", "kind": "computational", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "run": "echo 'ERROR broken'; exit 1", "fix_hint": "do the thing",
         "pairs_with": ["g"]},
        {"id": "blind", "kind": "computational", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "blocking": False, "run": "no-such-tool-xyz", "pairs_with": ["g"]},
        {"id": "warns", "kind": "computational", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "run": "printf 'WARN T6 x\\n      fix: pin it\\n'", "pairs_with": ["g"]},
        {"id": "live-one", "kind": "inferential", "category": "maintainability", "plane": "live",
         "stages": ["pre-commit"], "blocking": False, "run": "true", "pairs_with": ["g"]},
    ],
}


def setup(tmp_path, manifest=MANIFEST):
    (tmp_path / "harness.yaml").write_text(yaml.safe_dump(manifest))
    (tmp_path / "GUIDE.md").write_text("guide")


def run_args(**kw):
    return argparse.Namespace(**({"stage": "pre-commit", "plane": "static", "only": None} | kw))


def test_run_fails_on_blocking_failure_and_writes_report(runner, tmp_path):
    setup(tmp_path)
    assert runner.cmd_run(run_args()) == 1
    report = (tmp_path / ".harness" / "report.md").read_text()
    assert ": RED" in report
    assert "### fails" in report and "do the thing" in report and "ERROR broken" in report
    assert "## Blind sensors" in report and "`blind`" in report
    assert "## Warnings" in report and "pin it" in report
    assert "`live-one` (plane live)" in report             # other plane: listed as not run, not as passed
    ledger = [json.loads(x) for x in (tmp_path / ".harness" / "ledger.jsonl").read_text().splitlines()]
    assert {r["id"]: r["status"] for r in ledger} == {
        "passes": "pass", "fails": "fail", "blind": "unavailable", "warns": "pass"}


def test_only_runs_one_sensor_and_rejects_unknown_or_other_plane(runner, tmp_path):
    setup(tmp_path)
    assert runner.cmd_run(run_args(only="passes")) == 0
    assert runner.cmd_run(run_args(only="nope")) == 2
    assert runner.cmd_run(run_args(only="live-one")) == 3


def test_report_marks_results_from_another_revision_as_stale(runner, tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr(runner, "git_rev", lambda: "aaaa")
    runner.cmd_run(run_args(only="fails"))
    monkeypatch.setattr(runner, "git_rev", lambda: "bbbb")
    runner.cmd_run(run_args(only="passes"))
    report = (tmp_path / ".harness" / "report.md").read_text()
    assert "stale: from rev aaaa" in report


def test_selftest_needs_fire_on_defects_and_quiet_on_clean(runner, tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "bad.txt").write_text("# expect: BOOM\n")
    (fx / "ok.txt").write_text("# expect: clean\n")
    manifest = {**MANIFEST, "sensors": [{
        "id": "grep", "kind": "computational", "category": "maintainability", "plane": "static",
        "stages": ["pre-commit"], "run": "true", "pairs_with": ["g"],
        "selftest": {"fixtures": "fx", "run": "grep -q BOOM {fixture} && echo BOOM && exit 1 || exit 0"}}]}
    setup(tmp_path, manifest)
    assert runner.cmd_selftest(argparse.Namespace(only=None)) == 0
    (fx / "bad.txt").write_text("# expect: KABOOM\n")       # sensor output no longer contains the expectation
    assert runner.cmd_selftest(argparse.Namespace(only=None)) == 1


def test_coverage_flags_inconsistent_manifest(runner, tmp_path, capsys):
    bad = {**MANIFEST, "sensors": [{**MANIFEST["sensors"][0], "stages": ["pre-commit", "someday"],
                                    "pairs_with": ["ghost"]}]}
    setup(tmp_path, bad)
    assert runner.cmd_coverage(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "DANGLING" in out and "someday" in out


def test_coverage_is_clean_for_the_real_manifest(runner, monkeypatch):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner, "ROOT", root)
    assert runner.cmd_coverage(argparse.Namespace()) == 0


SKIP_MANIFEST = {
    "harness": 1,
    "categories": ["maintainability"],
    "guides": [{"id": "g", "path": "GUIDE.md", "kind": "inferential", "category": ["maintainability"]}],
    "sensors": [
        {"id": "optional-llm", "kind": "inferential", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "blocking": False, "pairs_with": ["g"],
         "run": "echo 'review: skipped, no LLM configured (set LLM_BASE_URL)'; exit 125"},
        {"id": "must-run", "kind": "computational", "category": "maintainability", "plane": "static",
         "stages": ["pre-commit"], "pairs_with": ["g"], "run": "exit 125"},
    ],
}


def test_exit_125_is_skipped_for_advisory_and_blind_for_blocking(runner, tmp_path):
    setup(tmp_path, SKIP_MANIFEST)
    assert runner.cmd_run(run_args(only="optional-llm")) == 0          # skipped never fails the stage
    report = (tmp_path / ".harness" / "report.md").read_text()
    assert "## Skipped (not configured)" in report and "set LLM_BASE_URL" in report
    assert "## Blind sensors" not in report
    assert runner.cmd_run(run_args(only="must-run")) == 1              # a blocking sensor cannot opt out
    ledger = [json.loads(x) for x in (tmp_path / ".harness" / "ledger.jsonl").read_text().splitlines()]
    assert [r["status"] for r in ledger] == ["skipped", "unavailable"]


def test_stats_ignore_skipped_runs(runner, tmp_path, capsys):
    out = tmp_path / ".harness"
    out.mkdir()
    rows = [{"id": "optional-llm", "status": "skipped", "seconds": 0.1}] * 5 + \
           [{"id": "optional-llm", "status": "fail", "seconds": 1.0}]
    (out / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert runner.cmd_stats(argparse.Namespace(min_runs=20)) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("optional-llm"))
    cols = line.split()
    assert cols[1:5] == ["1", "1", "100%", "0"] and cols[6] == "5"      # runs, fired, rate, blind, …, skipped


def test_review_without_llm_is_skipped(monkeypatch, capsys, tmp_path):
    from conftest import HARNESS, load

    monkeypatch.setenv("LLM_BASE_URL", "")
    review = load("review_skip", HARNESS / "sensors" / "review.py")
    monkeypatch.setattr(review, "collect_diff", lambda: "diff --git a/x b/x\n+change\n")
    assert review.main() == 125
    assert "LLM_BASE_URL" in capsys.readouterr().out
