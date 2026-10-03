"""Keeps search.documents in step with content.post.created (consumed by common.events.EventConsumer).

The upsert makes redelivery harmless; events published before tags existed carry no tags field.
"""
from __future__ import annotations

from psycopg_pool import ConnectionPool

UPSERT = """
INSERT INTO search.documents (post_id, title, body, author, tags)
VALUES (%(id)s, %(title)s, %(body)s, %(author)s, %(tags)s)
ON CONFLICT (post_id) DO UPDATE
   SET title = EXCLUDED.title, body = EXCLUDED.body, author = EXCLUDED.author, tags = EXCLUDED.tags
"""


def index_post(pool: ConnectionPool, event: dict) -> None:
    event.setdefault("tags", [])
    with pool.connection() as conn:
        conn.execute(UPSERT, event)
