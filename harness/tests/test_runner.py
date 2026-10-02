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
