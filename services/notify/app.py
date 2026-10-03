"""notify: records a notification for every new post (a stand-in for sending an e-mail) from
content.post.created, and lists them for the gateway."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial

from fastapi import Depends, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from common.events import EventConsumer
from common.service_auth import require_caller
from common.telemetry import create_app
from consumer import record_notification

log = logging.getLogger(__name__)

pool = ConnectionPool(os.environ.get("DB_DSN", ""), open=False, kwargs={"row_factory": dict_row})
notifier: EventConsumer | None = None


@asynccontextmanager
async def lifespan(_app):
    global notifier
    pool.open(wait=True, timeout=30)
    notifier = EventConsumer(os.environ.get("POST_CREATED_TOPIC", "content.post.created"),
                             partial(record_notification, pool),
                             bootstrap=os.environ["KAFKA_BOOTSTRAP"], group_id="notify", name="notifier")
    notifier.start()
    yield
    notifier.stop()
    pool.close()


app = create_app("notify", lifespan=lifespan)
auth = require_caller()


class Notification(BaseModel):
    post_id: int
    author: str
    created_at: datetime


class Outbox(BaseModel):
    author: str
    notifications: list[Notification]


@app.get("/outbox", response_model=Outbox)
def outbox(author: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
           limit: int = Query(20, ge=1, le=50), _caller: str = Depends(auth)) -> Outbox:
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT post_id, author, created_at FROM notify.outbox
             WHERE author = %s ORDER BY created_at DESC, post_id DESC LIMIT %s
            """,
            (author, limit),
        ).fetchall()
    return Outbox(author=author, notifications=[Notification(**r) for r in rows])
