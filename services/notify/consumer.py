"""Records one notification per content.post.created event (consumed by common.events.EventConsumer).

post_id is the primary key and the insert does nothing on conflict, so a redelivered event never notifies twice.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

INSERT = """
INSERT INTO notify.outbox (post_id, author, created_at)
VALUES (%(id)s, %(author)s, %(created_at)s)
ON CONFLICT (post_id) DO NOTHING
"""


def record_notification(pool: ConnectionPool, event: dict) -> None:
    with pool.connection() as conn:
        conn.execute(INSERT, event)
