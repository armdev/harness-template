"""Planner API for clients that are not the portal: bulk import in one transaction, re-plans as jobs (submit, then
poll; a model on a CPU may take minutes), and the status of the model behind the re-plan.

Holds with or without a reachable model: a job ends `done` with the model's plan or the rules' plan.
"""
import uuid

from conftest import eventually

MON = "2031-03-03"                     # a Monday


def team_payload(tag: str) -> dict:
    a, b, p = f"imp-{tag}-a", f"imp-{tag}-b", "I" + tag.upper()[:6]
    return {
        "employees": [{"handle": a, "name": "Ann", "role": "Engineer", "team": f"imp-{tag}"},
                      {"handle": b, "name": "Bob", "role": "QA", "team": f"imp-{tag}", "capacity_hours": 5}],
        "tasks": [{"key": f"{p}-1", "title": "Fix", "severity": "blocker", "assignee": a, "estimate_hours": 2,
                   "due": MON},
                  {"key": f"{p}-2", "title": "Test the fix", "severity": "major", "assignee": b, "estimate_hours": 3,
                   "depends_on": [f"{p}-1"]}],
        "meetings": [{"id": f"imp-{tag}-sync", "title": "Sync", "starts_at": f"{MON}T10:00:00",
                      "ends_at": f"{MON}T10:30:00", "organizer": a, "attendees": [a, b]}],
    }


def test_bulk_import_loads_everything_in_one_call(api):
    tag = uuid.uuid4().hex[:8]
    body = team_payload(tag)
    r = api.post("/api/planner/import", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"employees": 2, "tasks": 2, "meetings": 1}
    people = api.get("/api/planner/employees", params={"team": f"imp-{tag}", "start": MON}).json()["employees"]
    assert {p["handle"]: p["open_tasks"] for p in people} == {f"imp-{tag}-a": 1, f"imp-{tag}-b": 1}
    key = body["tasks"][1]["key"]
    assert api.get(f"/api/planner/tasks/{key}", params={"start": MON}).json()["blocked_by"] == [body["tasks"][0]["key"]]
    meetings = api.get("/api/planner/meetings", params={"attendee": f"imp-{tag}-b", "start": MON, "days": 1}).json()
    assert [m["id"] for m in meetings["meetings"]] == [f"imp-{tag}-sync"]
    assert api.post("/api/planner/import", json=body).json()["tasks"] == 2          # again: an upsert, not a copy


def test_bulk_import_is_all_or_nothing(api):
    tag = uuid.uuid4().hex[:8]
    body = team_payload(tag)
    body["tasks"].append({"key": "NOPE-1", "title": "x", "severity": "minor", "estimate_hours": 1,
                          "assignee": "nobody-" + tag})
    r = api.post("/api/planner/import", json=body)
    assert r.status_code == 422 and "unknown assignee" in r.text
    assert api.get("/api/planner/employees", params={"team": f"imp-{tag}"}).json()["employees"] == []
    bad = team_payload(tag) | {"tasks": [{"key": "lower-1", "title": "x", "severity": "minor", "estimate_hours": 1}]}
    assert api.post("/api/planner/import", json=bad).status_code == 422


def test_replan_job_is_queued_then_done_with_a_plan_that_keeps_the_rules(api):
    tag = uuid.uuid4().hex[:8]
    body = team_payload(tag)
    assert api.post("/api/planner/import", json=body).status_code == 200
    a, first = f"imp-{tag}-a", body["tasks"][0]["key"]                  # the second task is Bob's
    r = api.post(f"/api/planner/plan/{a}/ai/jobs", json={"instruction": "incidents first", "start": MON})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in ("queued", "running", "done") and job["handle"] == a
    assert job["poll"] == f"/api/planner/jobs/{job['id']}"

    def finished():
        j = api.get(f"/api/planner/jobs/{job['id']}").json()
        return j if j["status"] in ("done", "failed") else None

    done = eventually(finished, timeout=300, interval=1)
    assert done and done["status"] == "done", done
    plan = done["result"]
    assert plan["source"] in ("model", "rules") and plan["order"] == [first]
    assert plan["employee"]["handle"] == a and plan["days"][0]["date"] == MON
    if plan["source"] == "rules":
        assert plan["fallback"]


def test_replan_job_errors(api):
    nobody = "nobody-" + uuid.uuid4().hex[:8]
    assert api.post(f"/api/planner/plan/{nobody}/ai/jobs", json={}).status_code == 404
    assert api.post(f"/api/planner/plan/{nobody}/ai/jobs", json={"days": 99}).status_code == 422
    assert api.get(f"/api/planner/jobs/{uuid.uuid4().hex}").status_code == 404
    assert api.get("/api/planner/jobs/not-a-job").status_code == 422


def test_status_describes_the_model_and_the_queue(api):
    r = api.get("/api/planner/status")
    assert r.status_code == 200
    s = r.json()
    assert isinstance(s["model"]["configured"], bool) and isinstance(s["model"]["reachable"], bool)
    assert isinstance(s["model"]["think"], bool) and s["model"]["tasks_shown"] > 0
    assert set(s["jobs"]) == {"queued", "running", "done", "failed"} and s["cached_answers"] >= 0
