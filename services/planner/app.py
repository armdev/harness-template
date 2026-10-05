"""planner: employees, their Jira-style tasks and Outlook-style meetings, and a plan of each person's week.

The rules (planning.py) score every task (severity, due date, what waits for it, whether it is started) and fill
the working days around the meetings. On request a language model re-orders a person's tasks, guided by an
instruction ("Friday off", "security first"); its order is checked and the same scheduler fills the week, so a
model can change what comes first but never break a dependency or overfill a day. Without a usable model the plan
is the rules' plan, and says so (`source`).

Built for a model on a CPU: model calls run one at a time on a single worker (jobs.py), identical requests share a
job, a model answer is cached by everything the model saw, the prompt is short and asks for JSON without
reasoning (PLANNER_THINK=false). Slow answers are available as jobs (submit, then poll), and the synchronous
endpoint keeps its connection alive while it waits.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, field_validator, model_validator

import planning
from common.llm import ChatModel, ModelUnavailable, ThinkFilter
from common.service_auth import require_caller
from common.telemetry import create_app
from jobs import Cache, Jobs, fingerprint

log = logging.getLogger(__name__)

pool = ConnectionPool(os.environ.get("DB_DSN", ""), open=False, kwargs={"row_factory": dict_row})
model = ChatModel(os.environ.get("PLANNER_LLM_URL", ""), os.environ.get("PLANNER_MODEL", "qwen3:8b"),
                  api_key=os.environ.get("PLANNER_LLM_API_KEY", "not-needed"), timeout=600.0,
                  think=os.environ.get("PLANNER_THINK", "false").lower() == "true")
answers = Cache(256)                                    # model answers by fingerprint of what the model saw
jobs = Jobs(errors=(psycopg.Error, HTTPException))      # one model call at a time: a CPU is fastest that way
HEARTBEAT = 10.0                                        # seconds between keep-alive spaces of a waiting answer
probe: dict = {"at": -1e9, "reachable": False}
last_model_seconds: list[float] = []                    # the duration of the latest generation, for /status
HANDLE = r"^[A-Za-z0-9._-]{1,64}$"
HANDLE_RE = re.compile(HANDLE)
Severity = Literal["blocker", "critical", "major", "minor", "trivial"]
Status = Literal["todo", "in_progress", "review", "done"]



@asynccontextmanager
async def lifespan(_app):
    pool.open(wait=True, timeout=30)
    yield
    pool.close()
    model.close()


app = create_app("planner", lifespan=lifespan)
auth = require_caller()


# ------------------------------------------------------------------ input
class EmployeeIn(BaseModel):
    handle: str = Field(pattern=HANDLE)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    team: str = Field(min_length=1, max_length=64)
    capacity_hours: float = Field(6, gt=0, le=10, description="focus hours a day for tasks")


class TaskIn(BaseModel):
    key: str = Field(pattern=planning.KEY_RE.pattern, description="Jira key, PROJECT-123")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    severity: Severity
    status: Status = "todo"
    assignee: str | None = Field(None, pattern=HANDLE)
    estimate_hours: float = Field(gt=0, le=200)
    due: date | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("depends_on")
    @classmethod
    def keys(cls, v: list[str]) -> list[str]:
        if not all(planning.KEY_RE.match(k) for k in v):
            raise ValueError("every dependency is a task key, PROJECT-123")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def not_itself(self):
        if self.key in self.depends_on:
            raise ValueError("a task cannot depend on itself")
        return self


class StatusIn(BaseModel):
    status: Status


class MeetingIn(BaseModel):
    id: str = Field(pattern=HANDLE)
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime = Field(description="office wall clock; a time zone, if given, is ignored")
    ends_at: datetime
    organizer: str = Field(pattern=HANDLE)
    attendees: list[str] = Field(min_length=1, max_length=50)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def wall_clock(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=None)

    @field_validator("attendees")
    @classmethod
    def handles(cls, v: list[str]) -> list[str]:
        if not all(HANDLE_RE.match(a) for a in v):
            raise ValueError("every attendee is an employee handle")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def ends_after_start(self):
        if not self.starts_at < self.ends_at <= self.starts_at + timedelta(hours=12):
            raise ValueError("a meeting ends after it starts, within 12 hours")
        return self


class ImportIn(BaseModel):
    employees: list[EmployeeIn] = Field(default_factory=list, max_length=1000)
    tasks: list[TaskIn] = Field(default_factory=list, max_length=5000)
    meetings: list[MeetingIn] = Field(default_factory=list, max_length=5000)


class AiIn(BaseModel):
    instruction: str = Field("", max_length=500, description="e.g. 'I am off on Friday', 'security work first'")
    days: int = Field(5, ge=1, le=10)
    start: date | None = None


# ------------------------------------------------------------------ data
UPSERT_EMPLOYEE = """
    INSERT INTO planner.employees (handle, name, role, team, capacity_hours) VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (handle) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role, team = EXCLUDED.team,
       capacity_hours = EXCLUDED.capacity_hours, updated_at = now()"""
UPSERT_TASK = """
    INSERT INTO planner.tasks (key, title, description, severity, status, assignee, estimate_hours, due, depends_on)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (key) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,
       severity = EXCLUDED.severity, status = EXCLUDED.status, assignee = EXCLUDED.assignee,
       estimate_hours = EXCLUDED.estimate_hours, due = EXCLUDED.due, depends_on = EXCLUDED.depends_on,
       updated_at = now()"""
UPSERT_MEETING = """
    INSERT INTO planner.meetings (id, title, starts_at, ends_at, organizer, attendees) VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, starts_at = EXCLUDED.starts_at,
       ends_at = EXCLUDED.ends_at, organizer = EXCLUDED.organizer, attendees = EXCLUDED.attendees"""


def task_row(t: TaskIn) -> tuple:
    return (t.key, t.title, t.description, t.severity, t.status, t.assignee, t.estimate_hours, t.due, t.depends_on)


def all_tasks() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            """SELECT key, title, description, severity, status, assignee, estimate_hours::float AS estimate_hours,
                      due, depends_on FROM planner.tasks""").fetchall()


def employee(handle: str) -> dict:
    with pool.connection() as conn:
        e = conn.execute("""SELECT handle, name, role, team, capacity_hours::float AS capacity_hours
                              FROM planner.employees WHERE handle = %s""", (handle,)).fetchone()
    if e is None:
        raise HTTPException(status_code=404, detail=f"no employee {handle}")
    return e


def employees(team: str | None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute("""SELECT handle, name, role, team, capacity_hours::float AS capacity_hours
                                 FROM planner.employees WHERE %s::text IS NULL OR team = %s ORDER BY team, name""",
                            (team, team)).fetchall()


def meetings_between(start: date, end: date, attendee: str | None = None) -> list[dict]:
    """Meetings overlapping the days [start, end) — one person's, or everyone's."""
    lo, hi = datetime.combine(start, time()), datetime.combine(end, time())
    with pool.connection() as conn:
        return conn.execute(
            """SELECT id, title, starts_at, ends_at, organizer, attendees FROM planner.meetings
                WHERE (%s::text IS NULL OR attendees @> ARRAY[%s::text]) AND starts_at < %s AND ends_at > %s
                ORDER BY starts_at, id""",
            (attendee, attendee, hi, lo)).fetchall()


def meeting_minutes(day: date, meetings: list[dict]) -> int:
    return sum(b - a for a, b in planning.merge([(a, b) for a, b, _ in planning.busy_of(day, meetings)]))


# ------------------------------------------------------------------ employees
@app.post("/employees")
def upsert_employee(e: EmployeeIn, _caller: str = Depends(auth)) -> dict:
    with pool.connection() as conn:
        conn.execute(
            UPSERT_EMPLOYEE, (e.handle, e.name, e.role, e.team, e.capacity_hours))
    return employee(e.handle)


@app.get("/employees")
def list_employees(team: str | None = Query(None, min_length=1, max_length=64), start: date | None = None,
                   _caller: str = Depends(auth)) -> dict:
    """Everyone (or one team) with their load: open work, overdue and urgent tasks, meetings in the next 5 days."""
    today = start or date.today()
    people = employees(team)
    ranked = planning.rank(all_tasks(), today)
    days = planning.working_days(today, 5)
    week = meetings_between(days[0], days[-1] + timedelta(days=1))
    out = []
    for p in people:
        mine = [t for t in ranked if t["assignee"] == p["handle"] and planning.is_open(t)]
        theirs = [m for m in week if p["handle"] in m["attendees"]]
        hours = sum(t["estimate_hours"] for t in mine)
        out.append(p | {
            "open_tasks": len(mine), "open_hours": round(hours, 2),
            "overdue": sum(1 for t in mine if t["due"] is not None and t["due"] < today),
            "urgent": sum(1 for t in mine if t["bucket"] == "now"),
            "meeting_hours": round(sum(meeting_minutes(d, theirs) for d in days) / 60, 2),
            "load": round(hours / (p["capacity_hours"] * 5), 2),       # above 1: more work than a week of focus
        })
    return {"start": today, "employees": out}


# ------------------------------------------------------------------ tasks
@app.post("/tasks")
def upsert_task(t: TaskIn, _caller: str = Depends(auth)) -> dict:
    with pool.connection() as conn:
        if t.assignee is not None and not conn.execute(
                "SELECT 1 FROM planner.employees WHERE handle = %s", (t.assignee,)).fetchone():
            raise HTTPException(status_code=422, detail=f"unknown assignee {t.assignee}")
        conn.execute(
            UPSERT_TASK, task_row(t))
    return task(t.key)


def task(key: str, today: date | None = None) -> dict:
    ranked = planning.rank(all_tasks(), today or date.today())
    found = next((t for t in ranked if t["key"] == key), None)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no task {key}")
    return found


@app.get("/tasks/{key}")
def get_task(key: str = Path(pattern=planning.KEY_RE.pattern), start: date | None = None,
             _caller: str = Depends(auth)) -> dict:
    return task(key, start)


@app.post("/tasks/{key}/status")
def set_status(body: StatusIn, key: str = Path(pattern=planning.KEY_RE.pattern),
               _caller: str = Depends(auth)) -> dict:
    with pool.connection() as conn:
        if conn.execute("UPDATE planner.tasks SET status = %s, updated_at = now() WHERE key = %s",
                        (body.status, key)).rowcount == 0:
            raise HTTPException(status_code=404, detail=f"no task {key}")
    return task(key)


SORTS = {
    "priority": planning.rule_order_key,
    "due": lambda t: (t["due"] or date.max, -t["score"], t["key"]),
    "severity": lambda t: (-planning.SEVERITY[t["severity"]], -t["score"], t["key"]),
    "estimate": lambda t: (-t["estimate_hours"], -t["score"], t["key"]),
    "key": lambda t: (t["key"].split("-")[0], int(t["key"].split("-")[1])),
}


@app.get("/tasks")
def list_tasks(assignee: str | None = Query(None, pattern=HANDLE),
               severity: Annotated[list[Severity] | None, Query()] = None,
               status: Literal["open", "todo", "in_progress", "review", "done"] | None = None,
               project: str | None = Query(None, pattern=r"^[A-Z][A-Z0-9]{1,9}$"),
               q: str | None = Query(None, min_length=1, max_length=100),
               sort: Literal["priority", "due", "severity", "estimate", "key"] = "priority",
               start: date | None = None, limit: int = Query(200, ge=1, le=500),
               _caller: str = Depends(auth)) -> dict:
    """Tasks with their priority (score, bucket, reasons, what blocks them and what they block), filtered and sorted."""
    today = start or date.today()
    words = q.lower().split() if q else []
    out = [t for t in planning.rank(all_tasks(), today)
           if (assignee is None or t["assignee"] == assignee)
           and (not severity or t["severity"] in severity)
           and (status is None or (planning.is_open(t) if status == "open" else t["status"] == status))
           and (project is None or t["key"].split("-")[0] == project)
           and all(w in f"{t['key']} {t['title']} {t['description']}".lower() for w in words)]
    out.sort(key=SORTS[sort])
    return {"start": today, "total": len(out), "tasks": out[:limit]}


# ------------------------------------------------------------------ meetings
@app.post("/meetings")
def upsert_meeting(m: MeetingIn, _caller: str = Depends(auth)) -> dict:
    with pool.connection() as conn:
        conn.execute(UPSERT_MEETING, (m.id, m.title, m.starts_at, m.ends_at, m.organizer, m.attendees))
        return conn.execute("SELECT id, title, starts_at, ends_at, organizer, attendees FROM planner.meetings"
                            " WHERE id = %s", (m.id,)).fetchone()


@app.get("/meetings")
def list_meetings(attendee: str | None = Query(None, pattern=HANDLE), start: date | None = None,
                  days: int = Query(7, ge=1, le=31), _caller: str = Depends(auth)) -> dict:
    """Meetings on the calendar days from `start` (today), one person's or everyone's, in time order."""
    first = start or date.today()
    return {"start": first, "meetings": meetings_between(first, first + timedelta(days=days), attendee)}


# ------------------------------------------------------------------ bulk import
@app.post("/import")
def bulk_import(data: ImportIn, _caller: str = Depends(auth)) -> dict:
    """Employees, tasks and meetings in one transaction (all or nothing), upserted like the single endpoints.
    An assignee must be an employee of this import or one that already exists."""
    with pool.connection() as conn:
        given = {e.handle for e in data.employees}
        wanted = sorted({t.assignee for t in data.tasks if t.assignee} - given)
        if wanted:
            known = {r["handle"] for r in conn.execute(
                "SELECT handle FROM planner.employees WHERE handle = ANY(%s)", (wanted,)).fetchall()}
            if unknown := [h for h in wanted if h not in known]:
                raise HTTPException(status_code=422, detail=f"unknown assignee(s): {', '.join(unknown[:10])}")
        with conn.cursor() as cur:
            cur.executemany(UPSERT_EMPLOYEE, [(e.handle, e.name, e.role, e.team, e.capacity_hours)
                                              for e in data.employees])
            cur.executemany(UPSERT_TASK, [task_row(t) for t in data.tasks])
            cur.executemany(UPSERT_MEETING, [(m.id, m.title, m.starts_at, m.ends_at, m.organizer, m.attendees)
                                             for m in data.meetings])
    return {"employees": len(data.employees), "tasks": len(data.tasks), "meetings": len(data.meetings)}


# ------------------------------------------------------------------ plans
def plan_for(handle: str, start: date | None, days: int, order_keys: list[str] | None = None,
             off: frozenset[date] = frozenset()) -> dict:
    """A person's plan: their open tasks ranked by the rules (or in `order_keys`), scheduled around meetings."""
    who = employee(handle)
    today = start or date.today()
    ranked = planning.rank(all_tasks(), today)
    by_key = {t["key"]: t for t in ranked}
    mine = [t for t in ranked if t["assignee"] == handle and planning.is_open(t)]
    if order_keys:
        mine = [by_key[k] for k in order_keys]
    work_days = planning.working_days(today, days)
    meetings = meetings_between(work_days[0], work_days[-1] + timedelta(days=1), handle)
    s = planning.schedule(mine, meetings, who["capacity_hours"], today, days, by_key, off)
    return {"employee": who, "start": today, "order": [t["key"] for t in mine], "tasks": mine,
            "days": s["days"], "unscheduled": s["unscheduled"], "warnings": s["warnings"],
            "finishes": s["finishes"], "source": "rules", "model": None, "summary": rules_summary(who, mine, s),
            "notes": {}}


def rules_summary(who: dict, mine: list[dict], s: dict) -> str:
    if not mine:
        return f"{who['name']} has no open tasks."
    now = [t["key"] for t in mine if t["bucket"] == "now"]
    focus = sum(d["focus_minutes"] for d in s["days"]) / 60
    meet = sum(d["meeting_minutes"] for d in s["days"]) / 60
    text = (f"{len(mine)} open tasks; {focus:g} h of task work and {meet:g} h of meetings planned over "
            f"{len(s['days'])} working days.")
    if now:
        text += f" Do first: {', '.join(now[:5])}."
    if s["unscheduled"]:
        text += f" {len(s['unscheduled'])} task(s) do not fit."
    return text


@app.get("/plan/{handle}")
def get_plan(handle: str = Path(pattern=HANDLE), start: date | None = None, days: int = Query(5, ge=1, le=10),
             _caller: str = Depends(auth)) -> dict:
    return plan_for(handle, start, days)


def ask_model(messages: list[dict], open_keys: list[str], plan_days: list[date]) -> dict:
    """One generation; raises ModelUnavailable or planning.BadAnswer."""
    think = ThinkFilter()
    pieces = model.stream(messages, temperature=0.1, max_tokens=4096 if model.think else 1536,
                          json_mode=not model.think)
    text = "".join(think.feed(p) for p in pieces) + think.flush()
    return planning.read_answer(text, open_keys, plan_days)


def ai_plan_now(handle: str, body: AiIn, generate: bool = True) -> dict | None:
    """The model's plan for the person (from the cache when the model saw exactly this before), or the rules' plan
    with the reason in `fallback`. With generate=False: None when only a new generation can answer (the caller
    queues it), so cached answers and fallbacks never wait behind other people's generations."""
    rules = plan_for(handle, body.start, body.days)
    if not rules["tasks"]:
        return rules
    if not model.configured:
        return rules | {"fallback": "no language model is configured (PLANNER_LLM_URL); this is the rules' plan"}
    meetings = {d["date"]: d["meeting_minutes"] / 60 for d in rules["days"]}
    messages = planning.prompt(rules["employee"], rules["tasks"], meetings, body.instruction, rules["start"])
    key = fingerprint(model.model, model.think, messages, rules["order"])
    answer, seconds = answers.get(key), 0.0
    if answer is None and not generate:
        return None
    if answer is None:
        t0 = monotonic()
        try:
            answer = ask_model(messages, rules["order"], list(meetings))
        except ModelUnavailable as e:
            log.warning("model unavailable: %s", e)
            return rules | {"fallback": "the language model is not reachable; this is the rules' plan"}
        except planning.BadAnswer as e:
            log.warning("unusable model answer: %s", e)
            return rules | {"fallback": f"{e}; this is the rules' plan"}
        seconds = round(monotonic() - t0, 1)
        last_model_seconds[:] = [seconds]
        answers.put(key, answer)
    plan = plan_for(handle, body.start, body.days, answer["order"], frozenset(answer["days_off"]))
    moved = sum(1 for a, b in zip(answer["order"], rules["order"], strict=True) if a != b)
    return plan | {"source": "model", "model": model.model, "notes": answer["notes"],
                   "summary": answer["summary"] or plan["summary"], "instruction": body.instruction,
                   "days_off": answer["days_off"], "changed": moved, "cached": seconds == 0.0,
                   "model_seconds": seconds}


def submit(handle: str, body: AiIn):
    """A job for the re-plan: already done when no generation is needed, else queued for the model worker."""
    about = {"handle": handle, "instruction": body.instruction}
    quick = ai_plan_now(handle, body, generate=False)    # also the 404 for an unknown person, before any job
    if quick is not None:
        return jobs.completed(quick, about)
    return jobs.submit(fingerprint(handle, body.model_dump(mode="json")), lambda: ai_plan_now(handle, body), about)


@app.post("/plan/{handle}/ai")
def ai_plan(body: AiIn, handle: str = Path(pattern=HANDLE), _caller: str = Depends(auth)):
    """The model re-orders the person's tasks following the instruction; the rules check and schedule its order.
    Waits for the answer: a quick one (cached, no model, fallback) is returned at once; a slow one is preceded by a
    space every HEARTBEAT seconds (valid JSON whitespace), so proxies on the way do not time out."""
    job = submit(handle, body)
    if job.done.wait(timeout=2.0):
        if job.status == "done":
            return job.result
        return JSONResponse({"detail": job.error}, status_code=500)

    def body_with_heartbeat() -> Iterator[str]:
        while not job.done.wait(timeout=HEARTBEAT):
            yield " "
        out = job.result if job.status == "done" else {"detail": job.error, "status": "failed"}
        yield json.dumps(jsonable_encoder(out))

    return StreamingResponse(body_with_heartbeat(), media_type="application/json")


@app.post("/plan/{handle}/ai/jobs", status_code=202)
def ai_plan_job(body: AiIn, handle: str = Path(pattern=HANDLE), _caller: str = Depends(auth)) -> dict:
    """Queue a re-plan and return at once; poll GET /jobs/{id} until `status` is `done` (then `result` is the plan,
    as POST /plan/{handle}/ai returns it) or `failed`. An identical request still waiting or running is the same job."""
    job = submit(handle, body)
    return job.view(jobs.position(job)) | {"poll": f"/api/planner/jobs/{job.id}"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str = Path(pattern=r"^[0-9a-f]{32}$"), _caller: str = Depends(auth)) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job {job_id} (jobs are forgotten when the planner restarts)")
    return job.view(jobs.position(job))


@app.get("/status")
def status(_caller: str = Depends(auth)) -> dict:
    """The model behind the AI re-plan and the work waiting for it."""
    if monotonic() - probe["at"] > 15:
        probe["at"], probe["reachable"] = monotonic(), model.available()
    return {"model": {"name": model.model if model.configured else None, "configured": model.configured,
                      "reachable": probe["reachable"], "think": model.think,
                      "tasks_shown": planning.MODEL_TASKS},
            "jobs": jobs.counts(), "cached_answers": len(answers),
            "last_model_seconds": last_model_seconds[0] if last_model_seconds else None}


# ------------------------------------------------------------------ graph
@app.get("/graph")
def graph(handle: str | None = Query(None, pattern=HANDLE), team: str | None = Query(None, min_length=1, max_length=64),
          start: date | None = None, limit: int = Query(80, ge=1, le=300), _caller: str = Depends(auth)) -> dict:
    """Who works on what and what waits for what: employees, their open tasks (the most important `limit`),
    dependencies between tasks, and how often people meet in the next 5 working days."""
    today = start or date.today()
    people = employees(team)
    if handle and not any(p["handle"] == handle for p in people):
        raise HTTPException(status_code=404, detail=f"no employee {handle}")
    ranked = [t for t in planning.rank(all_tasks(), today) if planning.is_open(t)]
    by_key = {t["key"]: t for t in ranked}
    handles = {p["handle"] for p in people}
    if handle:                         # the person's tasks, plus the tasks they wait for and that wait for them
        mine = [t for t in ranked if t["assignee"] == handle]
        near = {k for t in mine for k in t["depends_on"] + t["blocks"] if k in by_key}
        tasks = mine + [by_key[k] for k in sorted(near) if by_key[k]["assignee"] != handle]
        handles = {handle} | {t["assignee"] for t in tasks if t["assignee"]}
    else:
        tasks = [t for t in ranked if t["assignee"] in handles][:limit]
    keys = {t["key"] for t in tasks}
    nodes = [{"id": "e:" + p["handle"], "type": "employee", "ref": p["handle"], "label": p["name"],
              "team": p["team"], "role": p["role"]} for p in people if p["handle"] in handles]
    nodes += [{"id": "t:" + t["key"], "type": "task", "ref": t["key"], "label": f"{t['key']} {t['title']}",
               "severity": t["severity"], "status": t["status"], "score": t["score"], "bucket": t["bucket"],
               "assignee": t["assignee"]} for t in tasks]
    edges = [{"source": "e:" + t["assignee"], "target": "t:" + t["key"], "kind": "assigned"}
             for t in tasks if t["assignee"] in handles]
    edges += [{"source": "t:" + t["key"], "target": "t:" + d, "kind": "depends_on"}
              for t in tasks for d in t["depends_on"] if d in keys]
    days = planning.working_days(today, 5)
    together: dict[tuple[str, str], int] = {}
    for m in meetings_between(days[0], days[-1] + timedelta(days=1)):
        present = sorted(set(m["attendees"]) & handles)
        for i, a in enumerate(present):
            for b in present[i + 1:]:
                together[(a, b)] = together.get((a, b), 0) + 1
    edges += [{"source": "e:" + a, "target": "e:" + b, "kind": "meets", "weight": n}
              for (a, b), n in sorted(together.items())]
    return {"start": today, "nodes": nodes, "edges": edges}
