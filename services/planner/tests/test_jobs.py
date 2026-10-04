"""The model worker: one job at a time in order, identical jobs shared, failures reported, answers cached."""
import threading

import pytest

from jobs import Cache, Jobs, fingerprint


def test_jobs_run_one_at_a_time_in_order_and_identical_ones_are_shared():
    gate, started, ran, running = threading.Event(), threading.Event(), [], []

    def work(name):
        def run():
            running.append(name)
            started.set()
            assert len(running) - len(ran) == 1          # never two at once
            gate.wait(5)
            ran.append(name)
            return name
        return run

    jobs = Jobs()
    a = jobs.submit("a", work("a"))
    assert started.wait(5) and a.status == "running"
    b = jobs.submit("b", work("b"))
    assert jobs.submit("b", work("b-again")) is b
    assert jobs.position(b) == 1 and b.view(1)["status"] == "queued" and b.view(1)["position"] == 1
    gate.set()
    assert b.done.wait(5) and a.done.wait(5)
    assert ran == ["a", "b"] and b.view(None)["result"] == "b" and b.status == "done"
    assert jobs.counts()["done"] == 2


def test_expected_errors_fail_the_job_and_the_worker_goes_on():
    jobs = Jobs(errors=(ValueError,))

    def boom():
        raise ValueError("no data")

    bad = jobs.submit("x", boom)
    assert bad.done.wait(5) and bad.status == "failed" and bad.view(None)["error"] == "ValueError: no data"
    good = jobs.submit("y", lambda: 42)
    assert good.done.wait(5) and good.result == 42


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_an_unexpected_error_fails_the_job_and_a_new_worker_takes_the_next():
    jobs = Jobs()
    first_worker = jobs._worker

    def bug():
        raise KeyError("bug")

    bad = jobs.submit("x", bug)
    first_worker.join(5)                                  # it died with the traceback (reported, not swallowed)
    assert not first_worker.is_alive()
    assert bad.done.wait(5) and bad.status == "failed" and "internal error" in bad.error
    good = jobs.submit("y", lambda: "ok")
    assert good.done.wait(5) and good.result == "ok"


def test_completed_jobs_are_done_at_once_and_old_jobs_are_forgotten():
    jobs = Jobs(keep=3)
    first = jobs.completed({"plan": 1}, {"handle": "ann"})
    view = first.view(None)
    assert first.done.is_set() and view["status"] == "done"
    assert view["handle"] == "ann" and view["result"] == {"plan": 1}
    for i in range(3):
        jobs.completed(i)
    assert jobs.get(first.id) is None


def test_cache_is_lru():
    c = Cache(size=2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and len(c) == 2


@pytest.mark.parametrize("a,b,same", [((1, "x"), (1, "x"), True), ((1, "x"), (1, "y"), False)])
def test_fingerprint(a, b, same):
    assert (fingerprint(*a) == fingerprint(*b)) is same
