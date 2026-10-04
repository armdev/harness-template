"""The planner's rules: priority, scheduling around meetings, and reading a model's answer."""
from datetime import date, datetime

import pytest

import planning

MON = date(2030, 1, 7)                         # a Monday


def task(key, severity="major", status="todo", hours=2, due=None, deps=(), assignee="ann", title=None):
    return {"key": key, "title": title or key, "description": "", "severity": severity, "status": status,
            "assignee": assignee, "estimate_hours": hours, "due": due, "depends_on": list(deps)}


def meeting(mid, day, start, end):
    return {"id": mid, "title": mid, "starts_at": datetime.combine(day, datetime.strptime(start, "%H:%M").time()),
            "ends_at": datetime.combine(day, datetime.strptime(end, "%H:%M").time()), "attendees": ["ann"]}


def plan(tasks, meetings=(), capacity=6, days=5, off=frozenset()):
    ranked = planning.rank(tasks, MON)
    by_key = {t["key"]: t for t in ranked}
    mine = [t for t in ranked if t["assignee"] == "ann"]
    return planning.schedule(mine, list(meetings), capacity, MON, days, by_key, off)


def test_severity_due_date_and_dependents_raise_the_score_with_reasons():
    ranked = planning.rank([task("A-1", "minor"), task("A-2", "blocker"), task("A-3", "minor", due=MON),
                            task("A-4", "trivial"), task("A-5", "trivial", deps=["A-4"])], MON)
    by = {t["key"]: t for t in ranked}
    assert ranked[0]["key"] == "A-2" and by["A-2"]["bucket"] == "now"
    assert by["A-3"]["score"] == 10 + 60 and "due today" in by["A-3"]["reasons"]
    assert by["A-4"]["score"] == 3 + 15 and by["A-4"]["blocks"] == ["A-5"]
    assert "blocks 1 open task" in by["A-4"]["reasons"]
    assert by["A-5"]["blocked_by"] == ["A-4"] and "waits for A-4" in by["A-5"]["reasons"]


def test_overdue_beats_severity_and_done_tasks_go_last():
    ranked = planning.rank([task("A-1", "critical"), task("A-2", "major", due=date(2030, 1, 1)),
                            task("A-3", "blocker", status="done")], MON)
    assert [t["key"] for t in ranked] == ["A-2", "A-1", "A-3"]
    assert "overdue by 6 days" in ranked[0]["reasons"]


def test_a_done_dependency_no_longer_blocks():
    ranked = planning.rank([task("A-1", status="done"), task("A-2", deps=["A-1"])], MON)
    assert next(t for t in ranked if t["key"] == "A-2")["blocked_by"] == []


def test_free_slots_skip_lunch_and_meetings():
    assert planning.free_slots([(10 * 60, 11 * 60)]) == [(540, 600), (660, 780), (840, 1080)]


def test_schedule_fills_around_meetings_up_to_capacity():
    s = plan([task("A-1", hours=8)], [meeting("standup", MON, "09:00", "09:30")], capacity=6)
    mon = s["days"][0]
    assert mon["meeting_minutes"] == 30 and mon["focus_minutes"] == 360
    assert [(i["start"], i["end"]) for i in mon["items"]] == [("09:30", "13:00"), ("14:00", "16:30")]
    assert s["days"][1]["items"][0]["minutes"] == 120 and s["finishes"]["A-1"] == date(2030, 1, 8)


def test_dependencies_come_first_even_if_less_important():
    s = plan([task("A-1", "blocker", hours=1, deps=["A-2"]), task("A-2", "trivial", hours=1)])
    items = [i["key"] for i in s["days"][0]["items"]]
    assert items == ["A-2", "A-1"]


def test_a_cycle_is_reported_not_scheduled():
    s = plan([task("A-1", deps=["A-2"]), task("A-2", deps=["A-1"])])
    assert {u["key"] for u in s["unscheduled"]} == {"A-1", "A-2"}
    assert all("waits for" in u["reason"] for u in s["unscheduled"])


def test_work_that_does_not_fit_and_late_finishes_are_warned():
    s = plan([task("A-1", hours=10, due=MON), task("A-2", hours=40)], days=2)
    assert any("after its due date" in w for w in s["warnings"])
    assert [u["key"] for u in s["unscheduled"]] == ["A-2"]
    assert any("do not fit" in w for w in s["warnings"])


def test_someone_elses_open_dependency_is_reported_but_does_not_hold():
    s = plan([task("A-1", hours=1, deps=["B-1"]), task("B-1", assignee="bob")])
    assert s["days"][0]["items"][0]["key"] == "A-1"
    assert "A-1 waits for B-1 (todo, @bob)" in s["warnings"]


def test_days_off_stay_empty_and_weekends_are_skipped():
    s = plan([task("A-1", hours=6)], [meeting("m", MON, "10:00", "11:00")], days=6, off=frozenset({MON}))
    assert s["days"][0]["off"] and s["days"][0]["items"] == []
    assert s["days"][1]["items"][0]["key"] == "A-1"
    assert [d["date"].weekday() for d in s["days"]] == [0, 1, 2, 3, 4, 0]
    assert any("day off" in w for w in s["warnings"])


def test_read_answer_keeps_known_keys_once_and_appends_the_rest():
    text = ('<think>hmm</think>Here: {"order": ["a-2", "X-9", "A-2", "A-3"], "notes": {"A-2": "outage", "Z-1": "x"},'
            ' "days_off": ["2030-01-11", "2031-01-01"], "summary": "Fix the outage first."}')
    a = planning.read_answer(text, ["A-1", "A-2", "A-3"], [MON, date(2030, 1, 11)])
    assert a["order"] == ["A-2", "A-3", "A-1"]
    assert a["notes"] == {"A-2": "outage"} and a["days_off"] == [date(2030, 1, 11)]
    assert a["summary"] == "Fix the outage first."


@pytest.mark.parametrize("text", ["no json here", "{not json}", '{"notes": {}}', '{"order": ["NOPE-1"]}'])
def test_read_answer_refuses_unusable_answers(text):
    with pytest.raises(planning.BadAnswer):
        planning.read_answer(text, ["A-1"], [MON])


def test_prompt_lists_tasks_days_and_instruction():
    ranked = planning.rank([task("A-1", "critical", due=MON, title="Fix card outage")], MON)
    emp = {"name": "Ann", "handle": "ann", "role": "SRE", "team": "core", "capacity_hours": 6}
    msgs = planning.prompt(emp, ranked, {MON: 1.5}, "security first", MON)
    user = msgs[1]["content"]
    assert "A-1 [" in user and "Fix card outage" in user and "Monday 2030-01-07 1.5 h" in user
    assert user.endswith("Instruction: security first")
