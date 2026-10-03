from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_FIXTURES = sorted((ROOT / "harness/sensors/fixtures/topology").glob("*.yml"))


@pytest.fixture(autouse=True)
def at_repo_root(monkeypatch):
    monkeypatch.chdir(ROOT)                                  # x-harness paths are relative to the repo root


def test_real_compose_file_is_clean(topology):
    assert topology.main("docker-compose.yml") == 0
    assert topology.findings == []


@pytest.mark.parametrize("fixture", TOPOLOGY_FIXTURES, ids=[f.stem for f in TOPOLOGY_FIXTURES])
def test_each_topology_fixture_fires_its_rule(topology, fixture):
    expect = fixture.read_text().splitlines()[0].split("expect:", 1)[1].strip()
    rc = topology.main(str(fixture), strict=True)
    if expect == "clean":
        assert rc == 0, topology.findings
    else:
        assert rc == 1 and any(f[1] == expect for f in topology.findings), topology.findings


def test_t1_ignores_dev_tooling(topology, tmp_path):
    compose = tmp_path / "c.yml"
    compose.write_text(
        "services:\n"
        "  store: { image: s:1, environment: { TRUSTED_CALLERS: api } }\n"
        "  contract: { image: t:1, profiles: [tools], environment: { STORE_URL: 'http://store:8000' } }\n")
    assert topology.main(str(compose)) == 0


def test_defaults_resolve_innermost_first(topology):
    assert topology.resolve_defaults("http://${HOST:-${FALLBACK:-db}}:5432") == "http://db:5432"


def test_real_migrations_are_clean(migrations, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_BASE", "none")
    assert migrations.main("db/migrations", strict=True) == 0


def test_grant_on_other_table_does_not_count(migrations, tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_BASE", "none")
    (tmp_path / "V1__a.sql").write_text("CREATE TABLE app.a (id int);\nGRANT SELECT ON app.b TO x_svc;\n")
    assert migrations.main(str(tmp_path)) == 1
    assert [f[1] for f in migrations.findings] == ["M4 granted"]


def test_grant_list_covers_several_tables(migrations, tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_BASE", "none")
    (tmp_path / "V1__ab.sql").write_text(
        "CREATE TABLE app.a (id int);\nCREATE TABLE app.b (id int);\nGRANT SELECT ON app.a, app.b TO x_svc;\n")
    assert migrations.main(str(tmp_path)) == 0


def test_review_parses_fenced_and_thinking_replies():
    from conftest import HARNESS, load

    review = load("review", HARNESS / "sensors" / "review.py")
    reply = '<think>hmm {"no": 1}</think>\n```json\n{"findings":[{"severity":"ERROR","rule":"R1"}]}\n```'
    assert review.parse_findings(reply) == [{"severity": "ERROR", "rule": "R1"}]
    assert review.parse_findings('{"findings": []}') == []
    with pytest.raises(ValueError):
        review.parse_findings("I could not review this.")


@pytest.fixture()
def deps_audit():
    from conftest import HARNESS, load
    return load("deps_audit", HARNESS / "sensors" / "deps_audit.py")


@pytest.mark.parametrize("rc, output, expected", [
    (0, "No known vulnerabilities found", 0),
    (1, "Found 3 known vulnerabilities in 1 package", 1),
    (1, "ERROR:pip_audit._cli:Couldn't execute in a temporary directory under /tmp.", 126),
])
def test_deps_audit_tells_findings_from_an_environment_that_cannot_audit(deps_audit, monkeypatch, rc, output,
                                                                         expected):
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], rc, stdout=output, stderr=""))
    assert deps_audit.main(["requirements.txt"]) == expected
