#!/usr/bin/env python3
"""air-harness console: one web UI for the product API, the harness and the coding agent.

  make console            (or ./run.sh --console)  →  http://127.0.0.1:8090

Runs on the host plane, like `make harness-integration`: harness stages start containers, so the console calls
`make` instead of mounting the Docker socket into a container. Stdlib only (plus PyYAML, which the host plane has).

Safety: binds 127.0.0.1 by default; runs only the allowlisted make targets in ACTIONS, one job at a time; serves
only the files in READABLE; every POST must carry the `X-Console` header, which a cross-site form cannot send.

Environment: CONSOLE_HOST (127.0.0.1), CONSOLE_PORT (8090), GATEWAY_URL (http://localhost:$GATEWAY_PORT or :8080),
PROMETHEUS_URL (http://localhost:$PROMETHEUS_PORT or :9090), AGENT_CMD (the coding agent, prompt appended as the
last argument; default `claude -p --permission-mode acceptEdits`).
"""
from __future__ import annotations

import contextlib
import fnmatch
import itertools
import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(os.environ.get("HARNESS_ROOT", Path(__file__).resolve().parents[2]))


def load_dotenv(path: Path) -> None:
    """Settings in .env, like ./run.sh: the environment wins, then .env, then the defaults below."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip().isidentifier() and not line.lstrip().startswith("#"):
            os.environ.setdefault(name.strip(), value.split(" #", 1)[0].strip())


load_dotenv(ROOT / ".env")
OUT = Path(os.environ.get("HARNESS_OUT", ROOT / ".harness"))
STATIC = Path(__file__).resolve().parent / "static"
GATEWAY = os.environ.get("GATEWAY_URL", f"http://localhost:{os.environ.get('GATEWAY_PORT', '8080')}").rstrip("/")
PROMETHEUS = os.environ.get("PROMETHEUS_URL",
                            f"http://localhost:{os.environ.get('PROMETHEUS_PORT', '9090')}").rstrip("/")
AGENT_CMD = shlex.split(os.environ.get("AGENT_CMD", "claude -p --permission-mode acceptEdits"))
MAX_LINES = 5000

# id: (label, command, what it does). Nothing else can be run from the browser.
ACTIONS: dict[str, tuple[str, list[str], str]] = {
    "fast": ("Fast loop", ["make", "-s", "harness-fast"], "pre-commit: static sensors (blocking) + review agent"),
    "static": ("Static only", ["make", "-s", "harness-static"], "the blocking static sensors (git hook, Stop hook)"),
    "integration": ("Integration", ["make", "-s", "harness-integration"], "unit + contract suite (stack up)"),
    "pipeline": ("Pipeline", ["make", "-s", "harness-pipeline"], "everything CI runs: + eval, alert rules"),
    "selftest": ("Selftest", ["make", "-s", "harness-selftest"], "seeded defects of the static sensors"),
    "selftest-host": ("Selftest host", ["make", "-s", "harness-selftest-host"],
                      "prom-rules, unit and contract mutants, eval (stack up)"),
    "selftest-live": ("Selftest live", ["make", "-s", "harness-selftest-live"], "deps-audit, review agent (LLM)"),
    "coverage": ("Coverage", ["make", "-s", "harness-coverage"], "guide × sensor matrix and gaps"),
    "stats": ("Stats", ["make", "-s", "harness-stats"], "steering table from the ledger"),
    "harness-test": ("Harness tests", ["make", "-s", "harness-test"], "tests and lint of the harness itself"),
    "up": ("Start stack", ["make", "-s", "up"], "build and start the reference system"),
    "ps": ("Stack status", ["make", "-s", "ps"], "docker compose ps"),
}

READABLE = ["AGENTS.md", "CLAUDE.md", "README.md", "harness.yaml", "harness/HARNESS.md", "harness/CHANGELOG.md",
            "harness/review/RUBRIC.md", "harness/skills/*/SKILL.md", "harness/prompts/*.md",
            "harness/prompts/*/*.md", "contract/README.md", "eval/README.md", "docs/*.md", "docs/*/*.md",
            ".harness/report.md", ".harness/eval-report.md"]


def readable(rel: str) -> Path | None:
    """The file if `rel` is on the allowlist and stays inside the repository, else None."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    if not any(fnmatch.fnmatch(rel, pattern) for pattern in READABLE):
        return None
    path = (ROOT / rel).resolve()
    return path if path.is_file() and path.is_relative_to(ROOT.resolve()) else None


def listing() -> list[str]:
    files = set()
    for pattern in READABLE:
        files |= {str(p.relative_to(ROOT)) for p in ROOT.glob(pattern) if p.is_file()}
    return sorted(files)


# ------------------------------------------------------------------ jobs
class Jobs:
    """Runs one allowlisted command at a time and keeps its output for the browser to poll."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[int, dict] = {}
        self.ids = itertools.count(1)
        self.running: int | None = None

    def start(self, kind: str, label: str, argv: list[str]) -> dict:
        with self.lock:
            if self.running is not None:
                raise RuntimeError(f"job {self.running} is still running")
            job = {"id": next(self.ids), "kind": kind, "label": label, "cmd": shlex.join(argv), "lines": [],
                   "started": time.time(), "finished": None, "rc": None}
            self.jobs[job["id"]] = job
            self.running = job["id"]
        threading.Thread(target=self._run, args=(job, argv), daemon=True).start()
        return job

    def _run(self, job: dict, argv: list[str]) -> None:
        try:
            p = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,  # noqa: S603 — allowlisted argv
                                 stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "NO_COLOR": "1"})
            for line in p.stdout:
                if len(job["lines"]) < MAX_LINES:
                    job["lines"].append(line.rstrip("\n"))
            job["rc"] = p.wait()
        except OSError as e:
            job["lines"].append(f"console: cannot start {argv[0]}: {e}")
            job["rc"] = 127
        finally:
            job["finished"] = time.time()
            with self.lock:
                self.running = None

    def view(self, job_id: int, since: int = 0) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if k != "lines"} | {"lines": job["lines"][since:],
                                                                 "next": len(job["lines"])}


JOBS = Jobs()


# ------------------------------------------------------------------ harness state
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def ledger(limit: int = 300) -> list[dict]:
    path = OUT / "ledger.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def stats(rows: list[dict]) -> dict[str, dict]:
    runs, fired, blind, skipped = Counter(), Counter(), Counter(), Counter()
    for r in rows:
        if r.get("status") == "skipped":
            skipped[r["id"]] += 1
            continue
        runs[r["id"]] += 1
        fired[r["id"]] += r.get("status") == "fail"
        blind[r["id"]] += r.get("status") in ("unavailable", "timeout")
    return {sid: {"runs": runs[sid], "fired": fired[sid], "blind": blind[sid], "skipped": skipped[sid]}
            for sid in set(runs) | set(skipped)}


def state() -> dict:
    manifest = yaml.safe_load((ROOT / "harness.yaml").read_text())
    results = {p.stem: read_json(p, {}) for p in (OUT / "results").glob("*.json")} if (OUT / "results").exists() else {}
    selftest = read_json(OUT / "selftest.json", {})
    report = (OUT / "report.md").read_text() if (OUT / "report.md").exists() else ""
    rows = ledger()
    counts = stats(rows)
    sensors = []
    for s in manifest["sensors"]:
        last = results.get(s["id"], {})
        sensors.append({"id": s["id"], "kind": s["kind"], "category": s["category"], "plane": s["plane"],
                        "stages": s["stages"], "blocking": s.get("blocking", True), "run": s["run"].strip(),
                        "fix_hint": s.get("fix_hint", ""), "pairs_with": s.get("pairs_with", []),
                        "last": {k: last.get(k) for k in ("status", "rc", "seconds", "rev", "stage", "ts")} if last
                        else None,
                        "output": (last.get("output") or "")[-4000:],
                        "selftest": selftest.get(s["id"], {}).get("verdict"),
                        "stats": counts.get(s["id"], {"runs": 0, "fired": 0, "blind": 0, "skipped": 0})})
    return {
        "version": manifest.get("template", {}).get("version"),
        "verdict": report.splitlines()[0].split(": ", 1)[-1] if report else None,
        "report": report,
        "has_eval": (OUT / "eval-report.md").exists(),
        "sensors": sensors,
        "guides": [{"id": g["id"], "path": g["path"], "kind": g["kind"]} for g in manifest["guides"]],
        "ledger": rows[-200:],
        "actions": [{"id": k, "label": v[0], "cmd": shlex.join(v[1]), "help": v[2]} for k, v in ACTIONS.items()],
        "running": JOBS.running,
        "agent": {"cmd": shlex.join(AGENT_CMD), "available": shutil.which(AGENT_CMD[0]) is not None},
        "gateway": GATEWAY, "prometheus": PROMETHEUS,
    }


def prompts() -> list[dict]:
    items = []
    for path in sorted((ROOT / "harness" / "prompts" / "next-steps").glob("*.md")):
        text = path.read_text()
        head, _, body = text.partition("\n---\n")
        title = head.splitlines()[0].lstrip("# ").strip()
        when = next((ln[6:] for ln in head.splitlines() if ln.startswith("When: ")), "")
        items.append({"id": path.stem, "title": title, "when": when, "text": body.strip() or text,
                      "command": f'claude "$(./help.sh prompt {path.stem[:2]})"'})
    for name in ("task", "fix-red", "done-check"):
        path = ROOT / "harness" / "prompts" / "agent" / f"{name}.md"
        if path.exists():
            items.append({"id": name, "title": f"Agent template: {name}", "when": "", "text": path.read_text(),
                          "command": f'./help.sh prompt {name}'})
    return items


def fill_prompt(name: str, task: str) -> str:
    text = (ROOT / "harness" / "prompts" / "agent" / f"{name}.md").read_text()
    report = (OUT / "report.md").read_text() if (OUT / "report.md").exists() else "(no report yet: run the fast loop)"
    return text.replace("{{task}}", task).replace("{{report_md}}", report)


def probe(url: str) -> dict:
    t = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 — fixed local URLs from config
            return {"url": url, "ok": 200 <= r.status < 300, "status": r.status,
                    "ms": round((time.monotonic() - t) * 1000)}
    except (urllib.error.URLError, OSError) as e:
        return {"url": url, "ok": False, "status": None, "error": str(getattr(e, "reason", e))}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "air-harness-console"

    def log_message(self, fmt, *args):  # quiet: the console is interactive
        pass

    def send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status: int = 200) -> None:
        self.send(status, json.dumps(data).encode())

    def error(self, status: int, message: str) -> None:
        self.json({"error": message}, status)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(min(n, 1_000_000)) if n else b""

    # -- routing
    def do_GET(self):  # noqa: N802 — http.server API
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/gw/"):
            return self.proxy("GET", url)
        routes = {
            "/api/state": lambda: self.json(state()),
            "/api/prompts": lambda: self.json(prompts()),
            "/api/files": lambda: self.json(listing()),
            "/api/health": lambda: self.json({"gateway": probe(f"{GATEWAY}/healthz"),
                                              "prometheus": probe(f"{PROMETHEUS}/-/ready")}),
        }
        if url.path in routes:
            return routes[url.path]()
        if url.path == "/api/file":
            path = readable(q.get("path", ""))
            return self.json({"path": q["path"], "text": path.read_text()}) if path else self.error(404, "not readable")
        if url.path.startswith("/api/jobs/"):
            try:
                view = JOBS.view(int(url.path.rsplit("/", 1)[1]), int(q.get("since", 0)))
            except ValueError:
                view = None
            return self.json(view) if view else self.error(404, "no such job")
        return self.static(url.path)

    def do_POST(self):  # noqa: N802
        url = urlsplit(self.path)
        if self.headers.get("X-Console") != "1":
            return self.error(403, "missing X-Console header")
        if url.path.startswith("/gw/"):
            return self.proxy("POST", url)
        try:
            data = json.loads(self.body() or b"{}")
        except ValueError:
            return self.error(400, "body is not JSON")
        try:
            if url.path == "/api/run":
                action = ACTIONS.get(data.get("action", ""))
                if not action:
                    return self.error(400, f"unknown action; allowed: {', '.join(ACTIONS)}")
                return self.json(JOBS.start(data["action"], action[0], action[1]) | {"lines": []})
            if url.path == "/api/agent":
                prompt = (data.get("prompt") or "").strip()
                if not prompt:
                    return self.error(400, "empty prompt")
                if shutil.which(AGENT_CMD[0]) is None:
                    return self.error(409, f"agent not installed: {AGENT_CMD[0]} (set AGENT_CMD)")
                return self.json(JOBS.start("agent", "Coding agent", [*AGENT_CMD, prompt]) | {"lines": []})
            if url.path == "/api/prompt":
                return self.json({"text": fill_prompt(data.get("name", "task"), data.get("task", ""))})
        except RuntimeError as e:
            return self.error(409, str(e))
        except OSError as e:
            return self.error(404, str(e))
        return self.error(404, "unknown endpoint")

    def proxy(self, method: str, url) -> None:
        """Forward /gw/<path> to the public API so the browser needs no CORS; returns status, type, body, ms."""
        target = f"{GATEWAY}/{url.path[4:]}" + (f"?{url.query}" if url.query else "")
        data = self.body() if method == "POST" else None
        req = urllib.request.Request(target, data=data, method=method,  # noqa: S310 — GATEWAY from config
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        t = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                status, ctype, body = r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            status, ctype, body = e.code, e.headers.get("Content-Type", ""), e.read()
        except (urllib.error.URLError, OSError) as e:
            return self.error(502, f"gateway unreachable at {GATEWAY}: {getattr(e, 'reason', e)}")
        self.send_response(status)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Upstream-Ms", str(round((time.monotonic() - t) * 1000)))
        self.end_headers()
        self.wfile.write(body)

    def static(self, path: str) -> None:
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        file = (STATIC / name).resolve()
        if not file.is_file() or not file.is_relative_to(STATIC.resolve()):
            return self.error(404, "not found")
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml"}
        self.send(200, file.read_bytes(), types.get(file.suffix, "application/octet-stream"))


def serve(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    host = os.environ.get("CONSOLE_HOST", "127.0.0.1")
    port = int(os.environ.get("CONSOLE_PORT", "8090"))
    httpd = serve(host, port)
    print(f"air-harness console: http://{host}:{port}   (API {GATEWAY}, agent: {shlex.join(AGENT_CMD)}) — Ctrl-C stops")
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
