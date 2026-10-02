import importlib.util
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """harness.py bound to a throwaway project root."""
    monkeypatch.setenv("HARNESS_ROOT", str(tmp_path))
    monkeypatch.setenv("HARNESS_OUT", str(tmp_path / ".harness"))
    return load("harness_runner", HARNESS / "harness.py")


@pytest.fixture()
def topology():
    mod = load("topology_check", HARNESS / "sensors" / "topology_check.py")
    mod.findings.clear()
    return mod


@pytest.fixture()
def migrations():
    mod = load("migrations_check", HARNESS / "sensors" / "migrations_check.py")
    mod.findings.clear()
    return mod
