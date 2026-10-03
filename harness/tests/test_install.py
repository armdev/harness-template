import sys

import yaml
from conftest import HARNESS, load

install = load("harness_install", HARNESS / "install.py")


def project(tmp_path, *, tests=False, compose=False, migrations=False, agents=None):
    p = tmp_path / "proj"
    (p / "app").mkdir(parents=True)
    (p / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    if tests:
        (p / "Makefile").write_text("test:\n\tpytest -q\n")
    if compose:
        (p / "docker-compose.yml").write_text("services: {}\n")
    if migrations:
        (p / "db" / "migrations").mkdir(parents=True)
    if agents:
        (p / "AGENTS.md").write_text(agents)
    return p


def sensors(p):
    return {s["id"]: s for s in yaml.safe_load((p / "harness.yaml").read_text())["sensors"]}


def test_minimal_project_gets_generic_sensors_pointed_at_its_sources(tmp_path):
    p = project(tmp_path)
    install.install(p, None, None)
    s = sensors(p)
    assert set(s) == {"ruff", "semgrep-local", "review-agent", "dead-code", "deps-audit"}
    assert s["ruff"]["run"].endswith(" app") and "REVIEW_SCOPE=\"app\"" in s["review-agent"]["run"]
    m = yaml.safe_load((p / "harness.yaml").read_text())
    assert m["categories"] == ["maintainability", "architecture"]          # no behaviour sensor: not claimed
    assert all(set(g["category"]) <= set(m["categories"]) for g in m["guides"])


def test_compose_migrations_and_tests_add_their_sensors(tmp_path):
    p = project(tmp_path, tests=True, compose=True, migrations=True)
    install.install(p, None, None)
    s = sensors(p)
    assert {"topology", "migrations", "unit"} <= set(s)
    assert "selftest" not in s["unit"] and s["unit"]["run"] == "make -s test"
    assert "behaviour" in yaml.safe_load((p / "harness.yaml").read_text())["categories"]


def test_project_files_are_never_overwritten_and_install_is_idempotent(tmp_path):
    p = project(tmp_path, agents="# our own rules\n")
    install.install(p, None, None)
    install.install(p, None, None)
    assert (p / "AGENTS.md").read_text() == "# our own rules\n"
    assert (p / "Makefile").read_text().count("include harness.mk") == 1
    assert (p / ".gitignore").read_text().count(".harness/") == 1


def test_reference_only_parts_are_not_copied(tmp_path):
    p = project(tmp_path)
    install.install(p, None, None)
    assert sorted(x.name for x in (p / "harness" / "skills").iterdir()) == ["harness-report", "harness-steer"]
    fixtures = {x.name for x in (p / "harness" / "sensors" / "fixtures").iterdir()}
    assert not fixtures & {"unit", "contract", "eval", "prom-rules", "migrations"}
    assert not (p / "harness" / "install.py").exists()


def test_a_project_without_python_sources_needs_src(tmp_path, monkeypatch):
    p = tmp_path / "empty"
    p.mkdir()
    monkeypatch.setattr(sys, "argv", ["install.py"])
    try:
        install.install(p, None, None)
    except SystemExit as e:
        assert "--src" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_rerun_keeps_the_projects_manifest_and_files(tmp_path):
    p = project(tmp_path)
    install.install(p, None, None)
    (p / "harness.yaml").write_text((p / "harness.yaml").read_text() + "# ours\n")
    (p / "harness" / "rules" / "semgrep" / "ours.yml").write_text("rules: []\n")
    install.install(p, None, None)
    assert (p / "harness.yaml").read_text().endswith("# ours\n")
    assert (p / "harness" / "rules" / "semgrep" / "ours.yml").exists()


def test_upgrade_replaces_machinery_only_and_reports_what_changed(tmp_path):
    p = project(tmp_path)
    install.install(p, None, None)
    m = yaml.safe_load((p / "harness.yaml").read_text())
    m["template"]["version"] = "0.3.5"
    m["sensors"] = [s for s in m["sensors"] if s["id"] != "deps-audit"]           # the project dropped one
    (p / "harness.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    (p / "harness" / "harness.py").write_text("stale\n")
    (p / "harness" / "review" / "RUBRIC.md").write_text("our rubric\n")
    added = install.install(p, None, None, upgrade=True)
    assert "harness/harness.py (upgraded)" in added
    assert (p / "harness" / "harness.py").read_text() == (HARNESS / "harness.py").read_text()
    assert (p / "harness" / "review" / "RUBRIC.md").read_text() == "our rubric\n"           # project-owned
    report = install.upgrade_report(p, ["app"], None)
    assert yaml.safe_load((p / "harness.yaml").read_text())["template"]["version"] != "0.3.5"
    assert any("0.3.5 ->" in line for line in report) and any("upstream changes" in line for line in report)
    assert any("deps-audit" in line for line in report)                               # offered, not forced
    assert "deps-audit" not in {s["id"] for s in yaml.safe_load((p / "harness.yaml").read_text())["sensors"]}
