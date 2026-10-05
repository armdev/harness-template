"""Seed the application with a dataset through the public API, so every service sees the data as users would add it.

  python tools/seed.py bank        # a dataset from services/web/static/datasets (general, bank, ibank), or a .json path
  ./app.sh seed bank  ·  make seed d=bank
  ./app.sh seed planner            # employees, Jira-style tasks and meetings for the planner

Posts: the dataset is validated first (the same rules as POST /api/posts). Seeding is idempotent: a post is skipped
when its author already has a post with the same title, so running it twice adds nothing.
Planner ({"kind": "planner", ...}): one POST /api/planner/import upserts employees, tasks and meetings by handle, key
and id, in one transaction. Their dates are relative (day 0 = the first working day from today), so seeding again
moves the demo to the current week and resets the tasks' status.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
PAGE = 50                                   # the API's largest page of an author's posts
TAG, AUTHOR = re.compile(r"^[a-z0-9-]{1,32}$"), re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def datasets_dir() -> Path:
    """DATASETS_DIR, else the datasets the portal serves, next to this script in a checkout."""
    if env := os.environ.get("DATASETS_DIR"):
        return Path(env)
    return Path(__file__).resolve().parent.parent / "services/web/static/datasets"


def load(name: str) -> list[dict] | dict:
    datasets = datasets_dir()
    path = Path(name) if name.endswith(".json") else datasets / f"{name}.json"
    if not path.is_file():
        known = sorted(p.stem for p in datasets.glob("*.json") if p.stem != "index")
        raise SystemExit(f"no dataset '{name}' (known: {', '.join(known)}; or pass a path to a .json file)")
    return json.loads(path.read_text())


def problems(posts: list[dict]) -> list[str]:
    out, seen = [], set()
    for i, p in enumerate(posts):
        where = f"post {i} ({p.get('title', '?')!r})"
        if not (isinstance(p.get("title"), str) and 1 <= len(p["title"]) <= 200):
            out.append(f"{where}: title must be 1-200 characters")
        if not (isinstance(p.get("body"), str) and 1 <= len(p["body"]) <= 20000):
            out.append(f"{where}: body must be 1-20000 characters")
        if not AUTHOR.match(str(p.get("author", ""))):
            out.append(f"{where}: author must match {AUTHOR.pattern}")
        tags = p.get("tags", [])
        if len(tags) > 5 or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            out.append(f"{where}: at most 5 tags matching {TAG.pattern}")
        if (p.get("author"), p.get("title")) in seen:
            out.append(f"{where}: duplicate author and title")
        seen.add((p.get("author"), p.get("title")))
    return out


def titles_of(api: httpx.Client, author: str) -> set[str]:
    """Every title the author already has, page by page (the newest PAGE first, then older)."""
    titles: set[str] = set()
    before = None
    while True:
        params = {"author": author, "limit": PAGE} | ({"before": before} if before else {})
        r = api.get("/api/posts", params=params)
        r.raise_for_status()
        posts = r.json()["posts"]
        titles |= {p["title"] for p in posts}
        if len(posts) < PAGE:
            return titles
        if before is not None and posts[-1]["id"] >= before:
            raise RuntimeError("the API ignored the 'before' cursor (an older gateway?); cannot page safely")
        before = posts[-1]["id"]


def wait_indexed(api: httpx.Client, post_id: int, timeout: float = 60) -> bool:
    """True once the last created post is in the knowledge graph (consumers are then caught up)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if api.get(f"/api/posts/{post_id}/related").status_code == 200:
            return True
        time.sleep(0.5)
    return False


def working_days(start: date, n: int) -> list[date]:
    """The planner's calendar: n weekdays from start (Saturday and Sunday are skipped)."""
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def planner_import(data: dict, today: date) -> tuple[dict, date]:
    """The dataset as one POST /api/planner/import body: due_in (working days from today) and day (working-day
    offset of a meeting) become dates."""
    horizon = 1 + max([t["due_in"] or 0 for t in data["tasks"]] + [m["day"] for m in data["meetings"]])
    days = working_days(today, horizon)
    tasks = [{k: v for k, v in t.items() if k != "due_in"} | {"due": None if t.get("due_in") is None
                                                              else str(days[t["due_in"]])} for t in data["tasks"]]
    meetings = []
    for m in data["meetings"]:
        starts = datetime.combine(days[m["day"]], datetime.strptime(m["start"], "%H:%M").time())
        meetings.append({k: m[k] for k in ("id", "title", "organizer", "attendees")} | {
            "starts_at": starts.isoformat(), "ends_at": (starts + timedelta(minutes=m["minutes"])).isoformat()})
    return {"employees": data["employees"], "tasks": tasks, "meetings": meetings}, days[0]


def seed_planner(name: str, data: dict, today: date) -> int:
    """Everything in one call, one transaction: all of it is loaded, or nothing."""
    body, day0 = planner_import(data, today)
    with httpx.Client(base_url=GATEWAY_URL, timeout=120) as api:
        r = api.post("/api/planner/import", json=body)
    if r.status_code != 200:
        print(f"{name}: POST /api/planner/import failed: {r.status_code} {r.text[:2000]}", file=sys.stderr)
        return 1
    n = r.json()
    print(f"{name}: {n['employees']} employees, {n['tasks']} tasks, {n['meetings']} meetings (day 0 = {day0})")
    return 0


def main(argv: list[str]) -> int:
    name = argv[1] if len(argv) > 1 else "general"
    posts = load(name)
    if isinstance(posts, dict) and posts.get("kind") == "planner":
        return seed_planner(name, posts, date.today())
    if errors := problems(posts):
        print(f"{name}: invalid dataset\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    with httpx.Client(base_url=GATEWAY_URL, timeout=15) as api:
        existing: dict[str, set[str]] = {}
        for author in sorted({p["author"] for p in posts}):
            existing[author] = titles_of(api, author)
        created, last = 0, None
        for p in posts:
            if p["title"] in existing[p["author"]]:
                continue
            r = api.post("/api/posts", json={k: p[k] for k in ("title", "body", "author", "tags") if k in p})
            if r.status_code != 201:
                print(f"{name}: POST /api/posts failed for {p['title']!r}: {r.status_code} {r.text}", file=sys.stderr)
                return 1
            created, last = created + 1, r.json()["id"]
        print(f"{name}: {created} posts created, {len(posts) - created} already there "
              f"({len({t for p in posts for t in p.get('tags', [])})} tags, {len(existing)} authors)")
        if last is not None:
            print("indexed by search, graph and notify" if wait_indexed(api, last)
                  else "created; the consumers are still indexing (check: ./app.sh logs graph)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
