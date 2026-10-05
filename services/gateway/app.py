"""gateway: the public HTTP API. Holds no data; every call goes to an internal service, signed as `gateway`."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal

import httpx
from fastapi import Body, HTTPException, Path, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from common.relay import relay
from common.service_auth import SignedClient
from common.telemetry import create_app

log = logging.getLogger(__name__)
clients: dict[str, SignedClient] = {}


@asynccontextmanager
async def lifespan(_app):
    clients["content"] = SignedClient(os.environ["CONTENT_URL"])
    clients["search"] = SignedClient(os.environ["SEARCH_URL"])
    clients["notify"] = SignedClient(os.environ["NOTIFY_URL"])
    clients["graph"] = SignedClient(os.environ["GRAPH_URL"])
    clients["chat"] = SignedClient(os.environ["CHAT_URL"])
    clients["planner"] = SignedClient(os.environ["PLANNER_URL"])
    yield
    for c in clients.values():
        c.close()
        await c.aclose()


app = create_app("gateway", lifespan=lifespan, description=(
    "Public API of air-harness. Every call is forwarded, signed as `gateway`, to the service that owns the data. "
    "The contract suite in `contract/` is the specification of this API."))

CHAT_EXAMPLE = {"messages": [{"role": "user", "content": "How do consumers avoid processing an event twice?"}]}
EMPLOYEE_EXAMPLE = {"handle": "anna.petrosyan", "name": "Anna Petrosyan", "role": "Backend engineer",
                    "team": "Payments", "capacity_hours": 6}
TASK_EXAMPLE = {"key": "PAY-101", "title": "Card authorisations time out at peak", "severity": "blocker",
                "status": "in_progress", "assignee": "anna.petrosyan", "estimate_hours": 6, "due": "2030-01-08",
                "depends_on": [], "description": "p99 of the authorisation call is above 2 s between 12:00 and 14:00."}
MEETING_EXAMPLE = {"id": "pay-standup-2030-01-07", "title": "Payments stand-up", "starts_at": "2030-01-07T09:30:00",
                   "ends_at": "2030-01-07T09:45:00", "organizer": "anna.petrosyan", "attendees": ["anna.petrosyan"]}
AI_EXAMPLE = {"instruction": "I am off on Friday; security findings first.", "days": 5}
HANDLE = r"^[A-Za-z0-9._-]{1,64}$"
KEY = r"^[A-Z][A-Z0-9]{1,9}-[0-9]{1,6}$"
Severity = Literal["blocker", "critical", "major", "minor", "trivial"]
POST_EXAMPLE = {"title": "Hello air-harness", "body": "My first post, searchable in a second.", "author": "me",
                "tags": ["intro"]}


async def forward(service: str, method: str, path: str, **kw) -> Response:
    try:
        r = await run_in_threadpool(clients[service].request, method, path, **kw)
    except httpx.HTTPError as e:
        log.warning("upstream %s unavailable: %s", service, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} unavailable") from None
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.post("/api/posts", status_code=201, summary="Create a post (validated and stored by content)")
async def create_post(post: dict = Body(examples=[POST_EXAMPLE])) -> Response:  # noqa: B008 — FastAPI idiom
    return await forward("content", "POST", "/posts", json=post)


@app.get("/api/posts", summary="List one author's posts, newest first")
async def list_posts(author: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
                     limit: int = Query(20, ge=1, le=50),
                     before: int | None = Query(None, ge=1, le=2**63 - 1,
                                                description="next page: the id of the last post seen")) -> Response:
    if before:
        return await forward("content", "GET", "/posts", params={"author": author, "limit": limit, "before": before})
    return await forward("content", "GET", "/posts", params={"author": author, "limit": limit})


@app.get("/api/posts/{post_id}", summary="Read a post")
async def get_post(post_id: int) -> Response:
    return await forward("content", "GET", f"/posts/{post_id}")


@app.get("/api/search", summary="Full-text search over posts (indexed asynchronously via Kafka)")
async def search(q: str = Query(min_length=1, max_length=200), author: str | None = None,
                 tag: str | None = Query(None, pattern=r"^[a-z0-9-]{1,32}$"),
                 limit: int = Query(10, ge=1, le=50)) -> Response:
    params = {"q": q, "limit": limit} | ({"author": author} if author else {}) | ({"tag": tag} if tag else {})
    return await forward("search", "GET", "/search", params=params)


@app.get("/api/notifications", summary="Notifications recorded for an author's posts, newest first")
async def notifications(author: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
                        limit: int = Query(20, ge=1, le=50)) -> Response:
    return await forward("notify", "GET", "/outbox", params={"author": author, "limit": limit})


@app.get("/api/posts/{post_id}/related",
         summary="Posts related through shared tags or the same author (knowledge graph)")
async def related_posts(post_id: int, limit: int = Query(10, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", f"/related/{post_id}", params={"limit": limit})


@app.get("/api/tags/{tag}", summary="A tag in the knowledge graph: how many posts carry it, which tags appear with it")
async def tag_neighbourhood(tag: str = Path(pattern=r"^[a-z0-9-]{1,32}$"),
                            limit: int = Query(10, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", f"/tags/{tag}", params={"limit": limit})


@app.get("/api/tags/{tag}/posts", summary="The newest posts carrying a tag (knowledge graph)")
async def tag_posts(tag: str = Path(pattern=r"^[a-z0-9-]{1,32}$"), limit: int = Query(20, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", f"/tags/{tag}/posts", params={"limit": limit})


@app.get("/api/graph/overview",
         summary="The knowledge graph at a glance: sizes, biggest tags and authors, how the top tags co-occur")
async def graph_overview(limit: int = Query(10, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", "/overview", params={"limit": limit})


@app.post("/api/chat", summary="Ask a question; the answer cites posts and streams as server-sent events",
          description="Fixed pipeline: search finds posts matching the question, the knowledge graph adds their "
                      "closest neighbours, a language model answers from them citing `[#id]`. Events: `sources` "
                      "(first), `token` (the answer, piece by piece), `done` (`citations`, `model`), `error`.")
async def chat(body: dict = Body(examples=[CHAT_EXAMPLE])) -> Response:  # noqa: B008 — FastAPI idiom
    return await relay(clients["chat"], "POST", "/chat", service="chat", json=body)


# ------------------------------------------------------------------ planner: employees, tasks, meetings, plans
def given(**params) -> dict:
    return {k: v for k, v in params.items() if v is not None}


@app.post("/api/planner/employees", summary="Add or update an employee (by handle)")
async def upsert_employee(body: Annotated[dict, Body(examples=[EMPLOYEE_EXAMPLE])]) -> Response:
    return await forward("planner", "POST", "/employees", json=body)


@app.get("/api/planner/employees", summary="Employees with their load: open work, overdue, urgent, meeting hours")
async def list_employees(team: str | None = Query(None, min_length=1, max_length=64),
                         start: date | None = None) -> Response:
    return await forward("planner", "GET", "/employees", params=given(team=team, start=start))


@app.post("/api/planner/tasks", summary="Add or update a Jira-style task (by key)")
async def upsert_task(body: Annotated[dict, Body(examples=[TASK_EXAMPLE])]) -> Response:
    return await forward("planner", "POST", "/tasks", json=body)


@app.get("/api/planner/tasks", summary="Tasks with their priority and its reasons, filtered and sorted")
async def list_tasks(assignee: str | None = Query(None, pattern=HANDLE),
                     severity: Annotated[list[Severity] | None, Query()] = None,
                     status: Literal["open", "todo", "in_progress", "review", "done"] | None = None,
                     project: str | None = Query(None, pattern=r"^[A-Z][A-Z0-9]{1,9}$"),
                     q: str | None = Query(None, min_length=1, max_length=100),
                     sort: Literal["priority", "due", "severity", "estimate", "key"] = "priority",
                     start: date | None = None, limit: int = Query(200, ge=1, le=500)) -> Response:
    return await forward("planner", "GET", "/tasks", params=given(
        assignee=assignee, severity=severity, status=status, project=project, q=q, sort=sort, start=start,
        limit=limit))


@app.get("/api/planner/tasks/{key}", summary="A task with its priority: score, bucket, reasons, what it blocks")
async def get_task(key: str = Path(pattern=KEY), start: date | None = None) -> Response:
    return await forward("planner", "GET", f"/tasks/{key}", params=given(start=start))


@app.post("/api/planner/tasks/{key}/status", summary="Move a task: todo, in_progress, review, done")
async def set_task_status(body: Annotated[dict, Body(examples=[{"status": "done"}])],
                          key: str = Path(pattern=KEY)) -> Response:
    return await forward("planner", "POST", f"/tasks/{key}/status", json=body)


@app.post("/api/planner/meetings", summary="Add or update a meeting (by id); times on the office wall clock")
async def upsert_meeting(body: Annotated[dict, Body(examples=[MEETING_EXAMPLE])]) -> Response:
    return await forward("planner", "POST", "/meetings", json=body)


@app.get("/api/planner/meetings", summary="Meetings on the days from `start`, one person's or everyone's")
async def list_meetings(attendee: str | None = Query(None, pattern=HANDLE), start: date | None = None,
                        days: int = Query(7, ge=1, le=31)) -> Response:
    return await forward("planner", "GET", "/meetings", params=given(attendee=attendee, start=start, days=days))


@app.get("/api/planner/plan/{handle}", summary="A person's plan by the rules: tasks in priority order, scheduled "
                                                "around meetings over the next working days")
async def get_plan(handle: str = Path(pattern=HANDLE), start: date | None = None,
                   days: int = Query(5, ge=1, le=10)) -> Response:
    return await forward("planner", "GET", f"/plan/{handle}", params=given(start=start, days=days))


@app.post("/api/planner/plan/{handle}/ai", summary="Re-plan a person's week with the language model",
          description="The model re-orders the open tasks following the instruction and may mark days off; the "
                      "rules check its answer and schedule it (dependencies, meetings, capacity). `source` says "
                      "whether the plan is the model's or, when no usable model answered, the rules' (`fallback`).")
async def ai_plan(body: Annotated[dict, Body(examples=[AI_EXAMPLE])],
                  handle: str = Path(pattern=HANDLE)) -> Response:
    return await relay(clients["planner"], "POST", f"/plan/{handle}/ai", service="planner", json=body)


@app.post("/api/planner/plan/{handle}/ai/jobs", status_code=202,
          summary="Queue a re-plan with the language model; poll the returned job",
          description="Returns at once with a job (`id`, `status`: queued, running, done or failed; `position` while "
                      "queued; `poll`: where to ask). For a model on a CPU, where an answer can take minutes. An "
                      "identical request still waiting or running is the same job; an answer the model already gave "
                      "for the same data comes back as a job that is already done.")
async def ai_plan_job(body: Annotated[dict, Body(examples=[AI_EXAMPLE])],
                      handle: str = Path(pattern=HANDLE)) -> Response:
    return await forward("planner", "POST", f"/plan/{handle}/ai/jobs", json=body)


@app.get("/api/planner/jobs/{job_id}", summary="A re-plan job: its status and, when done, the plan (`result`)")
async def planner_job(job_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> Response:
    return await forward("planner", "GET", f"/jobs/{job_id}")


@app.get("/api/planner/status", summary="The planner's model (configured, reachable, thinking) and its queue")
async def planner_status() -> Response:
    return await forward("planner", "GET", "/status")


@app.post("/api/planner/import", summary="Bulk import employees, tasks and meetings in one transaction",
          description="All or nothing; each item is upserted as by the single endpoints. Up to 1000 employees, "
                      "5000 tasks and 5000 meetings per call.")
async def planner_import(body: Annotated[dict, Body(examples=[{"employees": [EMPLOYEE_EXAMPLE],
                                                               "tasks": [TASK_EXAMPLE],
                                                               "meetings": [MEETING_EXAMPLE]}])]) -> Response:
    return await relay(clients["planner"], "POST", "/import", service="planner", json=body)   # no 5 s limit


@app.get("/api/planner/graph", summary="Who works on what and what waits for what: employees, tasks, "
                                        "dependencies, shared meetings")
async def planner_graph(handle: str | None = Query(None, pattern=HANDLE),
                        team: str | None = Query(None, min_length=1, max_length=64), start: date | None = None,
                        limit: int = Query(80, ge=1, le=300)) -> Response:
    return await forward("planner", "GET", "/graph", params=given(handle=handle, team=team, start=start, limit=limit))
