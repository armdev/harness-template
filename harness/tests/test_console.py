import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import HARNESS, load


@pytest.fixture()
def console(tmp_path, monkeypatch):
    """The console server on a free port, over this repository, with its own .harness output directory."""
    out = tmp_path / ".harness"
    (out / "results").mkdir(parents=True)
    (out / "report.md").write_text("# Harness report — stage `pre-commit`, rev abc: GREEN\n\n## Passed\n")
    (out / "ledger.jsonl").write_text(json.dumps({"id": "ruff", "status": "fail", "rc": 1, "seconds": 0.1, "rev": "abc",
                                                  "stage": "pre-commit", "blocking": True, "ts": 1}) + "\n")
    (out / "selftest.json").write_text(json.dumps({"ruff": {"verdict": "proven", "rev": "abc", "ts": 1}}))
    monkeypatch.setenv("HARNESS_OUT", str(out))
    monkeypatch.setenv("GATEWAY_URL", "http://127.0.0.1:9")            # nothing listens: proxy must say 502
    monkeypatch.setenv("AGENT_CMD", "definitely-not-an-agent -p")
    mod = load("console_server", HARNESS / "console" / "server.py")
    httpd = mod.serve("127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield mod, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, header=True):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} | ({"X-Console": "1"} if header else {})
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_state_joins_manifest_results_selftest_and_ledger(console):
    mod, base = console
    status, st = call(base, "/api/state")
    assert status == 200 and st["verdict"] == "GREEN"
    ruff = next(s for s in st["sensors"] if s["id"] == "ruff")
    assert ruff["selftest"] == "proven" and ruff["stats"]["fired"] == 1
    assert {a["id"] for a in st["actions"]} == set(mod.ACTIONS)
    assert st["agent"]["available"] is False


def test_only_allowlisted_files_inside_the_repository_are_readable(console):
    _, base = console
    assert call(base, "/api/file?path=AGENTS.md")[0] == 200
    assert call(base, "/api/file?path=harness/review/RUBRIC.md")[0] == 200
    for path in ("harness/harness.py", "../../etc/passwd", "/etc/passwd", ".env", "docs/../harness/harness.py"):
        assert call(base, f"/api/file?path={path}")[0] == 404, path
    assert "harness/skills/harness-report/SKILL.md" in call(base, "/api/files")[1]


def test_posts_need_the_console_header_and_an_allowlisted_action(console):
    _, base = console
    assert call(base, "/api/run", {"action": "fast"}, header=False)[0] == 403
    assert call(base, "/api/run", {"action": "rm -rf /"})[0] == 400
    assert call(base, "/api/agent", {"prompt": "hi"})[0] == 409                  # agent CLI not installed


def test_a_job_streams_its_output_and_only_one_runs_at_a_time(console):
    mod, base = console
    mod.ACTIONS["slow"] = ("Slow", ["sh", "-c", "echo started; sleep 1; echo finished"], "test")
    status, job = call(base, "/api/run", {"action": "slow"})
    assert status == 200
    assert call(base, "/api/run", {"action": "slow"})[0] == 409
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        view = call(base, f"/api/jobs/{job['id']}")[1]
        if view["finished"] is not None:
            break
        time.sleep(0.1)
    assert view["rc"] == 0 and view["lines"] == ["started", "finished"]
    assert call(base, f"/api/jobs/{job['id']}?since=1")[1]["lines"] == ["finished"]


def test_gateway_proxy_forwards_and_reports_an_unreachable_gateway(console):
    mod, base = console
    assert call(base, "/gw/healthz")[0] == 502

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"echo": json.loads(body), "path": self.path}).encode())

        def log_message(self, *a):
            pass

    upstream = HTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    mod.GATEWAY = f"http://127.0.0.1:{upstream.server_address[1]}"
    status, body = call(base, "/gw/api/posts?x=1", {"title": "t"})
    upstream.shutdown()
    assert status == 201 and body == {"echo": {"title": "t"}, "path": "/api/posts?x=1"}


def test_prompts_and_the_task_template(console):
    _, base = console
    items = call(base, "/api/prompts")[1]
    assert {"01-explore", "task", "fix-red"} <= {p["id"] for p in items}
    text = call(base, "/api/prompt", {"name": "task", "task": "Add rate limiting"})[1]["text"]
    assert "Add rate limiting" in text and "{{task}}" not in text
