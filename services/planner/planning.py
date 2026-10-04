"""The planner's rules: how important a task is, and how a person's week is filled. Pure functions, no I/O.

priority  severity + how close the due date is + how much other work waits for it + whether it is started;
          every point comes with a reason a person can read.
schedule  working days 09:00-18:00 minus lunch and meetings, at most the person's focus hours a day, tasks in the
          given order (rules or a model), a task never before its own dependencies, chunks of at least 30 minutes.
model     the prompt for a language model that re-orders the tasks, and a strict reader of its JSON answer:
          an answer that is not usable falls back to the rules' order.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

SEVERITY = {"blocker": 100, "critical": 60, "major": 30, "minor": 10, "trivial": 3}
OPEN = ("todo", "in_progress", "review")
DAY_START, DAY_END, LUNCH = 9 * 60, 18 * 60, (13 * 60, 14 * 60)     # minutes since midnight, office wall clock
MIN_CHUNK = 30                                                       # a slot shorter than this is not worth a task
BUCKETS = ((90, "now"), (50, "next"), (20, "later"), (0, "someday"))
KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-[0-9]{1,6}$")    # a Jira key: PROJECT-123


def is_open(t: dict) -> bool:
    return t["status"] in OPEN


def dependents_of(tasks: list[dict]) -> dict[str, list[dict]]:
    """For every key: the open tasks that list it in depends_on (they wait for it)."""
    out: dict[str, list[dict]] = {}
    for t in tasks:
        if is_open(t):
            for d in t["depends_on"]:
                out.setdefault(d, []).append(t)
    return out


def priority(t: dict, today: date, waiting: list[dict], by_key: dict[str, dict]) -> dict:
    """Score, bucket and the reasons for them; blocked_by = dependencies that are still open."""
    score, reasons = SEVERITY[t["severity"]], [f"{t['severity']} severity"]
    if t["due"] is not None:
        days = (t["due"] - today).days
        if days < 0:
            score, reason = score + 80, f"overdue by {-days} day{'s' if days < -1 else ''}"
        elif days == 0:
            score, reason = score + 60, "due today"
        elif days <= 2:
            score, reason = score + 40, f"due in {days} day{'s' if days > 1 else ''}"
        elif days <= 5:
            score, reason = score + 20, f"due in {days} days"
        elif days <= 10:
            score, reason = score + 8, f"due in {days} days"
        else:
            reason = ""
        if reason:
            reasons.append(reason)
    if waiting:
        score += 15 * min(len(waiting), 3)
        reasons.append(f"blocks {len(waiting)} open task{'s' if len(waiting) > 1 else ''}")
        if any(w["severity"] in ("blocker", "critical") for w in waiting):
            score += 10
            reasons.append("unblocks critical work")
    if t["status"] == "in_progress":
        score += 10
        reasons.append("already started")
    elif t["status"] == "review":
        score += 5
        reasons.append("in review: little left")
    blocked_by = [d for d in t["depends_on"] if d in by_key and is_open(by_key[d])]
    if blocked_by:
        reasons.append("waits for " + ", ".join(blocked_by))
    bucket = next(name for floor, name in BUCKETS if score >= floor)
    return {"score": score, "bucket": bucket, "reasons": reasons, "blocked_by": blocked_by,
            "blocks": [w["key"] for w in waiting]}


def rank(tasks: list[dict], today: date) -> list[dict]:
    """Every task with its priority, most important first (score, then due date, then key)."""
    by_key, waiting = {t["key"]: t for t in tasks}, dependents_of(tasks)
    ranked = [t | priority(t, today, waiting.get(t["key"], []), by_key) for t in tasks]
    return sorted(ranked, key=rule_order_key)


def rule_order_key(t: dict) -> tuple:
    return (not is_open(t), -t["score"], t["due"] or date.max, t["key"])


# ------------------------------------------------------------------ schedule
def minutes(hours: float) -> int:
    """An estimate in whole quarters of an hour, at least one."""
    return max(15, round(float(hours) * 4) * 15)


def clock(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def working_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def busy_of(day: date, meetings: list[dict]) -> list[tuple[int, int, dict]]:
    """The day's meetings clipped to working hours, as (start, end, meeting) in minutes."""
    lo, hi = datetime.combine(day, time()), datetime.combine(day + timedelta(days=1), time())
    out = []
    for m in meetings:
        s, e = max(m["starts_at"], lo), min(m["ends_at"], hi)
        if s < e:
            a = max(DAY_START, s.hour * 60 + s.minute) if s > lo else DAY_START
            b = min(DAY_END, e.hour * 60 + e.minute) if e < hi else DAY_END
            if a < b:
                out.append((a, b, m))
    return sorted(out, key=lambda x: x[:2])


def free_slots(busy: list[tuple[int, int]]) -> list[tuple[int, int]]:
    slots, t = [], DAY_START
    for a, b in sorted(busy + [LUNCH]):
        if a > t:
            slots.append((t, min(a, DAY_END)))
        t = max(t, b)
    if t < DAY_END:
        slots.append((t, DAY_END))
    return [(a, b) for a, b in slots if b > a]


def schedule(order: list[dict], meetings: list[dict], capacity_hours: float, start: date, n_days: int,
             by_key: dict[str, dict], off: frozenset[date] = frozenset()) -> dict:
    """Fill n working days from `start` with the open tasks of `order` (in that order); days in `off` stay empty.
    Returns days, unscheduled, warnings. A task starts only after its own open dependencies are finished in this
    plan; a dependency owned by someone else does not hold it, but is reported."""
    todo = [t for t in order if is_open(t)]
    mine = {t["key"] for t in todo}
    left = {t["key"]: minutes(t["estimate_hours"]) for t in todo}
    finished: dict[str, tuple[date, int]] = {}
    budget_per_day = minutes(capacity_hours)
    days, warnings = [], []

    def ready(t: dict, now: tuple[date, int]) -> bool:
        return all(d not in mine or (d in finished and finished[d] <= now) for d in t["depends_on"])

    for day in working_days(start, n_days):
        busy = busy_of(day, meetings)
        if day in off:
            days.append({"date": day, "weekday": day.strftime("%A"), "off": True, "meetings": [], "items": [],
                         "meeting_minutes": 0, "focus_minutes": 0})
            if busy:
                warnings.append(f"{day}: day off, but {len(busy)} meeting(s) are booked; decline or delegate them")
            continue
        meeting_min = sum(b - a for a, b in merge([(a, b) for a, b, _ in busy]))
        budget, items = budget_per_day, []
        for a, b in free_slots([(a, b) for a, b, _ in busy]):
            t = a
            while t < b and budget > 0:
                room = min(b - t, budget)
                task = next((x for x in todo if left[x["key"]] > 0 and ready(x, (day, t))
                             and (left[x["key"]] <= room or room >= MIN_CHUNK)), None)
                if task is None:
                    break
                k = task["key"]
                chunk = min(left[k], room)
                if items and items[-1]["key"] == k and items[-1]["end_min"] == t:
                    items[-1]["end_min"] += chunk
                else:
                    items.append({"key": k, "title": task["title"], "severity": task["severity"],
                                  "start_min": t, "end_min": t + chunk})
                left[k] -= chunk
                t, budget = t + chunk, budget - chunk
                if left[k] == 0:
                    finished[k] = (day, t)
        focus = sum(i["end_min"] - i["start_min"] for i in items)
        days.append({
            "date": day, "weekday": day.strftime("%A"),
            "meetings": [{"id": m["id"], "title": m["title"], "start": clock(a), "end": clock(b)} for a, b, m in busy],
            "items": [{"key": i["key"], "title": i["title"], "severity": i["severity"], "start": clock(i["start_min"]),
                       "end": clock(i["end_min"]), "minutes": i["end_min"] - i["start_min"]} for i in items],
            "meeting_minutes": meeting_min, "focus_minutes": focus, "off": False,
        })
        if meeting_min >= 5 * 60:
            warnings.append(f"{day}: {meeting_min / 60:g} h of meetings leave little focus time")

    unscheduled = []
    for t in todo:
        k = t["key"]
        if left[k] > 0:
            own = [d for d in t["depends_on"] if d in mine and d not in finished]
            reason = (f"waits for {', '.join(own)}, which does not finish in this plan" if own and left[k] == minutes(
                t["estimate_hours"]) else f"{left[k] / 60:g} h do not fit in {n_days} working days")
            unscheduled.append({"key": k, "title": t["title"], "severity": t["severity"], "reason": reason})
        elif t["due"] is not None and finished[k][0] > t["due"]:
            warnings.append(f"{k} finishes on {finished[k][0]}, after its due date {t['due']}")
        for d in t["depends_on"]:
            dep = by_key.get(d)
            if dep is not None and d not in mine and is_open(dep):
                warnings.append(f"{k} waits for {d} ({dep['status']}, @{dep['assignee'] or 'unassigned'})")
    if unscheduled:
        hours = sum(left[u["key"]] for u in unscheduled) / 60
        warnings.append(f"{len(unscheduled)} task(s), {hours:g} h, do not fit in the next {n_days} working days")
    return {"days": days, "unscheduled": unscheduled, "warnings": warnings,
            "finishes": {k: v[0] for k, v in finished.items()}}


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


# ------------------------------------------------------------------ model
SYSTEM = (
    "You plan the work of one employee in a bank's IT department. You get their open Jira tasks and their meeting "
    "load. Decide the order in which they should work on the tasks so that what matters most gets done first: "
    "production incidents and outages, security and regulatory deadlines, then work that unblocks colleagues, then "
    "the rest. A task must come after the tasks it depends on. Follow the user's instruction when it is given. "
    "Answer with one JSON object and nothing else:\n"
    '{"order": ["KEY-1", "..."], "notes": {"KEY-1": "why it is here, one short sentence"}, '
    '"summary": "two or three sentences to the employee about the plan"}\n'
    "The order lists every task key exactly once.")


def prompt(employee: dict, ranked_open: list[dict], meeting_hours: dict[date, float], instruction: str,
           today: date) -> list[dict]:
    """meeting_hours: the plan's days and the hours of meetings on each."""
    lines = [f"Employee: {employee['name']} (@{employee['handle']}), {employee['role']}, team {employee['team']}; "
             f"{employee['capacity_hours']:g} focus hours a day. Today is {today:%A %Y-%m-%d}.",
             "Plan days and their meeting hours: " + ", ".join(f"{d:%A} {d} {h:g} h" for d, h in meeting_hours.items()),
             "", "Open tasks (rule score in brackets: severity, due date, what waits for it):"]
    for t in ranked_open:
        deps = f"; depends on {', '.join(t['depends_on'])}" if t["depends_on"] else ""
        due = f"; due {t['due']}" if t["due"] else ""
        desc = " ".join(t["description"].split())[:240]
        lines.append(f"- {t['key']} [{t['score']}] {t['title']} — {t['severity']}, {t['status']}, "
                     f"{float(t['estimate_hours']):g} h{due}{deps}. {desc}")
    lines += ["", f"Instruction: {instruction.strip() or 'none; use your judgement'}"]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


class BadAnswer(ValueError):
    """The model's answer is not a usable plan."""


def read_answer(text: str, open_keys: list[str], plan_days: list[date]) -> dict:
    """The model's order (unknown keys dropped, missing keys appended in the given order), notes, days off (only
    days of the plan) and summary."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise BadAnswer("the model did not answer with JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        raise BadAnswer("the model's JSON could not be read") from None
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list):
        raise BadAnswer("the model's answer has no order")
    known, seen, keys = set(open_keys), set(), []
    for k in order:
        k = str(k).strip().upper()
        if k in known and k not in seen:
            seen.add(k)
            keys.append(k)
    if not keys:
        raise BadAnswer("the model's order names none of the tasks")
    keys += [k for k in open_keys if k not in seen]
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
    notes = {str(k).upper(): str(v)[:300] for k, v in notes.items() if str(k).upper() in known and v}
    off = data.get("days_off") if isinstance(data.get("days_off"), list) else []
    days_off = sorted({d for d in plan_days if str(d) in {str(x).strip() for x in off}})
    summary = data.get("summary")
    return {"order": keys, "notes": notes, "days_off": days_off, "summary": str(summary)[:1500] if summary else ""}

