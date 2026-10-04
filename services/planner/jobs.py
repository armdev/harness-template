"""Model work on a CPU: one generation at a time, in order, never twice for the same question.

A CPU runs one generation fastest when it has every core; two at once take longer than one after the other. So model
calls go through one worker thread (a queue), identical requests waiting in it share one job, and a finished model
answer is kept (LRU) by the fingerprint of everything the model saw, so asking the same thing again over the same
data costs nothing. Jobs are kept in memory: a restart forgets them (a client then simply asks again).
"""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


def fingerprint(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class Cache:
    """A small thread-safe LRU of model answers."""

    def __init__(self, size: int = 256):
        self.size, self._items, self._lock = size, OrderedDict(), threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


class Job:
    def __init__(self, key: str, work: Callable[[], Any], about: dict):
        self.id, self.key, self.work, self.about = uuid.uuid4().hex, key, work, about
        self.status, self.result, self.error = "queued", None, None
        self.created, self.started, self.finished = time.time(), None, None
        self.done = threading.Event()

    def view(self, position: int | None) -> dict:
        now = time.time()
        out = {"id": self.id, "status": self.status, **self.about,
               "waited_seconds": round((self.started or now) - self.created, 1),
               "running_seconds": round((self.finished or now) - self.started, 1) if self.started else 0.0}
        if self.status == "queued":
            out["position"] = position
        if self.status == "done":
            out["result"] = self.result
        if self.status == "failed":
            out["error"] = self.error
        return out


class Jobs:
    """One worker, first in first out; a job with the same key as a waiting or running one is that job.

    `errors`: the exceptions a job may end with (reported as `failed`). Anything else is a bug: the job is marked
    failed, the worker thread dies with the traceback in the log, and a new worker takes the next job."""

    def __init__(self, errors: tuple[type[BaseException], ...] = (), keep: int = 500):
        self.errors, self.keep, self._jobs, self._order = errors, keep, {}, []
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="model-worker", daemon=True)
            self._worker.start()

    def submit(self, key: str, work: Callable[[], Any], about: dict | None = None) -> Job:
        with self._lock:
            for job in self._jobs.values():
                if job.key == key and job.status in ("queued", "running"):
                    return job
            job = self._remember(Job(key, work, about or {}))
            self._ensure_worker()
        self._queue.put(job)
        return job

    def completed(self, result: Any, about: dict | None = None) -> Job:
        """A job whose answer is already known (a cache hit): done at once, never queued."""
        job = Job("", lambda: result, about or {})
        job.status, job.result, job.started = "done", result, job.created
        job.finished = job.created
        job.done.set()
        with self._lock:
            return self._remember(job)

    def _remember(self, job: Job) -> Job:
        self._jobs[job.id] = job
        self._order.append(job.id)
        while len(self._order) > self.keep:                     # forget the oldest finished jobs
            old = self._jobs.get(self._order[0])
            if old is not None and old.status in ("queued", "running"):
                break
            self._jobs.pop(self._order.pop(0), None)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def position(self, job: Job) -> int | None:
        """1 = next to run."""
        with self._lock:
            waiting = [j for j in (self._jobs[i] for i in self._order if i in self._jobs) if j.status == "queued"]
        return waiting.index(job) + 1 if job in waiting else None

    def counts(self) -> dict:
        with self._lock:
            states = [j.status for j in self._jobs.values()]
        return {s: states.count(s) for s in ("queued", "running", "done", "failed")}

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            job.status, job.started = "running", time.time()
            try:
                job.result, job.status = job.work(), "done"
            except self.errors as e:
                job.error, job.status = f"{type(e).__name__}: {e}", "failed"
            finally:
                if job.status == "running":                       # a bug: this thread dies with the traceback
                    job.error, job.status = "internal error (see the planner's log)", "failed"
                    with self._lock:                               # and a new worker takes the next job
                        self._worker = None
                        self._ensure_worker()
                job.finished = time.time()
                job.done.set()
