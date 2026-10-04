"""Planner: employees, Jira-style tasks and meetings; every task's priority with its reasons; a person's week planned
around their meetings; a re-plan by a language model that the rules check (or the rules' plan when no model answers).

Every test uses its own team, handles and project key, and a fixed Monday as `start`, so tests never see each other's
data and dates do not depend on the day the suite runs. The model's wording and order are never checked: only that
its plan keeps the rules (every open task once, dependencies first, no meeting overlapped).
"""
import uuid

import pytest

MON = "2031-03-03"                     # a Monday
TUE, FRI = "2031-03-04", "2031-03-07"


@pytest.fixture()
def team(api):
    """A fresh team: two employees and a project key of its own."""
    tag = uuid.uuid4().hex[:8]
    people = [f"ct-{tag}-a", f"ct-{tag}-b"]
    for i, h in enumerate(people):
        r = api.post("/api/planner/employees", json={"handle": h, "name": f"Person {i}", "role": "Engineer",
                                                      "team": f"team-{tag}", "capacity_hours": 6})
        assert r.status_code == 200, r.text
    return {"name": f"team-{tag}", "people": people, "project": "Q" + tag.upper()[:6].replace("0", "X")}


def add_task(api, team, n, **kw):
    body = {"key": f"{team['project']}-{n}", "title": f"Task {n}", "severity": "major", "assignee": team["people"][0],
            "estimate_hours": 2} | kw
    r = api.post("/api/planner/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_employee_upsert_and_team_load(api, team):
    a, b = team["people"]
    add_task(api, team, 1, severity="blocker", due="2031-03-01", estimate_hours=10)
    add_task(api, team, 2, estimate_hours=5, status="done")
    r = api.post("/api/planner/employees", json={"handle": a, "name": "Anna", "role": "Lead", "team": team["name"],
                                                  "capacity_hours": 4})
    assert r.status_code == 200
    assert r.json() == {"handle": a, "name": "Anna", "role": "Lead", "team": team["name"], "capacity_hours": 4.0}
    r = api.get("/api/planner/employees", params={"team": team["name"], "start": MON})
    assert r.status_code == 200
    body = r.json()
    assert body["start"] == MON
    by = {e["handle"]: e for e in body["employees"]}
    assert set(by) == {a, b}
    assert by[a]["open_tasks"] == 1 and by[a]["open_hours"] == 10 and by[a]["overdue"] == 1 and by[a]["urgent"] == 1
    assert by[a]["load"] == 0.5 and by[b]["open_tasks"] == 0 and "meeting_hours" in by[a]


@pytest.mark.parametrize("bad", [
    {"key": "not-a-key"}, {"severity": "urgent"}, {"status": "doing"}, {"estimate_hours": 0},
    {"title": ""}, {"due": "tomorrow"}, {"depends_on": ["lower-1"]},
])
def test_task_validation(api, team, bad):
    body = {"key": f"{team['project']}-9", "title": "T", "severity": "major", "estimate_hours": 1} | bad
    assert api.post("/api/planner/tasks", json=body).status_code == 422


def test_a_task_cannot_depend_on_itself_or_go_to_an_unknown_person(api, team):
    key = f"{team['project']}-1"
    r = api.post("/api/planner/tasks", json={"key": key, "title": "T", "severity": "major", "estimate_hours": 1,
                                             "depends_on": [key]})
    assert r.status_code == 422
    r = api.post("/api/planner/tasks", json={"key": key, "title": "T", "severity": "major", "estimate_hours": 1,
                                             "assignee": "nobody-" + uuid.uuid4().hex[:8]})
    assert r.status_code == 422 and "unknown assignee" in r.text


def test_priority_has_reasons_and_orders_the_list(api, team):
    p = team["project"]
    add_task(api, team, 1, severity="trivial")
    add_task(api, team, 2, severity="minor", depends_on=[f"{p}-1"])
    add_task(api, team, 3, severity="critical", due=MON, status="in_progress")
    add_task(api, team, 4, severity="major", due="2031-02-20")
    r = api.get("/api/planner/tasks", params={"assignee": team["people"][0], "start": MON})
    assert r.status_code == 200
    tasks = r.json()["tasks"]
    assert [t["key"] for t in tasks] == [f"{p}-3", f"{p}-4", f"{p}-1", f"{p}-2"]
    top = tasks[0]
    assert top["score"] == 60 + 60 + 10 and top["bucket"] == "now"
    assert top["reasons"] == ["critical severity", "due today", "already started"]
    one = next(t for t in tasks if t["key"] == f"{p}-1")
    two = next(t for t in tasks if t["key"] == f"{p}-2")
    assert one["blocks"] == [f"{p}-2"] and two["blocked_by"] == [f"{p}-1"]
    assert "overdue by 11 days" in tasks[1]["reasons"]
    assert set(top) >= {"key", "title", "description", "severity", "status", "assignee", "estimate_hours", "due",
                        "depends_on", "score", "bucket", "reasons", "blocked_by", "blocks"}


def test_filter_and_sort(api, team):
    p = team["project"]
    add_task(api, team, 1, severity="minor", due="2031-03-20", title="Rotate vault secrets")
    add_task(api, team, 2, severity="blocker", due="2031-03-10", estimate_hours=8)
    add_task(api, team, 3, severity="major", status="done")
    base = {"assignee": team["people"][0], "start": MON}

    def keys(**q):
        return [t["key"] for t in api.get("/api/planner/tasks", params=base | q).json()["tasks"]]

    assert keys(status="open") == [f"{p}-2", f"{p}-1"]
    assert keys(status="done") == [f"{p}-3"]
    assert keys(severity=["blocker", "minor"], sort="due") == [f"{p}-2", f"{p}-1"]
    assert keys(q="vault") == [f"{p}-1"]
    assert keys(sort="estimate")[0] == f"{p}-2"
    assert keys(project=p, sort="key") == [f"{p}-1", f"{p}-2", f"{p}-3"]
    assert api.get("/api/planner/tasks", params={"sort": "random"}).status_code == 422
    assert api.get("/api/planner/tasks", params={"severity": "urgent"}).status_code == 422


def test_status_change_unblocks_and_unknown_task_is_404(api, team):
    p = team["project"]
    add_task(api, team, 1)
    add_task(api, team, 2, depends_on=[f"{p}-1"])
    r = api.post(f"/api/planner/tasks/{p}-1/status", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert api.get(f"/api/planner/tasks/{p}-2").json()["blocked_by"] == []
    assert api.post(f"/api/planner/tasks/{p}-999/status", json={"status": "done"}).status_code == 404
    assert api.post(f"/api/planner/tasks/{p}-1/status", json={"status": "gone"}).status_code == 422
    assert api.get(f"/api/planner/tasks/{p}-999").status_code == 404


def test_meetings_validated_and_listed_by_attendee(api, team):
    a, b = team["people"]
    m = {"id": f"m-{a}", "title": "Stand-up", "starts_at": f"{MON}T09:30:00", "ends_at": f"{MON}T09:45:00",
         "organizer": a, "attendees": [a, b]}
    r = api.post("/api/planner/meetings", json=m)
    assert r.status_code == 200 and r.json()["attendees"] == [a, b]
    bad = m | {"ends_at": f"{MON}T09:00:00"}
    assert api.post("/api/planner/meetings", json=bad).status_code == 422
    assert api.post("/api/planner/meetings", json=m | {"attendees": []}).status_code == 422
    r = api.get("/api/planner/meetings", params={"attendee": b, "start": MON, "days": 1})
    assert [x["id"] for x in r.json()["meetings"]] == [m["id"]]
    r = api.get("/api/planner/meetings", params={"attendee": b, "start": TUE})
    assert r.json()["meetings"] == []


def test_plan_fills_the_week_around_meetings_dependencies_first(api, team):
    p, (a, _) = team["project"], team["people"]
    add_task(api, team, 1, severity="blocker", estimate_hours=3, depends_on=[f"{p}-2"])
    add_task(api, team, 2, severity="trivial", estimate_hours=1)
    add_task(api, team, 3, severity="minor", estimate_hours=40)
    api.post("/api/planner/meetings", json={"id": f"m1-{a}", "title": "Review", "starts_at": f"{MON}T09:00:00",
                                            "ends_at": f"{MON}T10:00:00", "organizer": a, "attendees": [a]})
    r = api.get(f"/api/planner/plan/{a}", params={"start": MON, "days": 2})
    assert r.status_code == 200
    plan = r.json()
    assert plan["source"] == "rules" and plan["employee"]["handle"] == a
    assert plan["order"] == [f"{p}-1", f"{p}-2", f"{p}-3"]       # the blocker, what it waits for, the rest
    mon = plan["days"][0]
    assert mon["date"] == MON and mon["meetings"] == [{"id": f"m1-{a}", "title": "Review", "start": "09:00",
                                                       "end": "10:00"}]
    assert [(i["key"], i["start"]) for i in mon["items"][:2]] == [(f"{p}-2", "10:00"), (f"{p}-1", "11:00")]
    assert mon["focus_minutes"] == 360 and mon["meeting_minutes"] == 60
    assert [u["key"] for u in plan["unscheduled"]] == [f"{p}-3"]
    assert any("do not fit" in w for w in plan["warnings"])
    assert api.get("/api/planner/plan/nobody-" + uuid.uuid4().hex[:6]).status_code == 404
    assert api.get(f"/api/planner/plan/{a}", params={"days": 11}).status_code == 422


def test_ai_plan_keeps_the_rules(api, team):
    p, (a, _) = team["project"], team["people"]
    add_task(api, team, 1, severity="major", estimate_hours=2, depends_on=[f"{p}-2"])
    add_task(api, team, 2, severity="minor", estimate_hours=2)
    add_task(api, team, 3, severity="critical", estimate_hours=2, status="done")
    r = api.post(f"/api/planner/plan/{a}/ai", json={"instruction": f"I am off on Friday {FRI}.", "start": MON},
                 timeout=200)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["source"] in ("model", "rules")
    assert sorted(plan["order"]) == [f"{p}-1", f"{p}-2"]
    assert (plan["model"] is None) == (plan["source"] == "rules")
    if plan["source"] == "rules":
        assert plan["fallback"]
    done = [i["key"] for d in plan["days"] for i in d["items"]]
    assert done.index(f"{p}-2") < done.index(f"{p}-1")
    assert isinstance(plan["summary"], str) and plan["summary"]
    assert api.post(f"/api/planner/plan/{a}/ai", json={"instruction": "x" * 501}).status_code == 422


def test_graph_links_people_tasks_dependencies_and_meetings(api, team):
    p, (a, b) = team["project"], team["people"]
    add_task(api, team, 1, depends_on=[f"{p}-2"])
    add_task(api, team, 2, assignee=b)
    api.post("/api/planner/meetings", json={"id": f"g-{a}", "title": "Sync", "starts_at": f"{MON}T11:00:00",
                                            "ends_at": f"{MON}T11:30:00", "organizer": a, "attendees": [a, b]})
    r = api.get("/api/planner/graph", params={"handle": a, "start": MON})
    assert r.status_code == 200
    g = r.json()
    ids = {n["id"] for n in g["nodes"]}
    assert {f"e:{a}", f"e:{b}", f"t:{p}-1", f"t:{p}-2"} <= ids
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert (f"e:{a}", f"t:{p}-1", "assigned") in edges and (f"t:{p}-1", f"t:{p}-2", "depends_on") in edges
    assert (f"e:{a}", f"e:{b}", "meets") in edges or (f"e:{b}", f"e:{a}", "meets") in edges
    task = next(n for n in g["nodes"] if n["id"] == f"t:{p}-1")
    assert task["type"] == "task" and task["severity"] == "major" and task["bucket"]
    r = api.get("/api/planner/graph", params={"team": team["name"], "start": MON})
    assert {n["id"] for n in r.json()["nodes"] if n["type"] == "employee"} == {f"e:{a}", f"e:{b}"}
    assert api.get("/api/planner/graph", params={"handle": "nobody-" + uuid.uuid4().hex[:6]}).status_code == 404
