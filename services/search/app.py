"""search: full-text search over posts. Builds its own index from content.post.created events."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from common.service_auth import require_caller
from common.telemetry import create_app
from indexer import Indexer

log = logging.getLogger(__name__)

pool = ConnectionPool(os.environ.get("DB_DSN", ""), open=False, kwargs={"row_factory": dict_row})
indexer: Indexer | None = None


@asynccontextmanager
async def lifespan(_app):
    global indexer
    pool.open(wait=True, timeout=30)
    indexer = Indexer(pool, os.environ["KAFKA_BOOTSTRAP"],
                      os.environ.get("POST_CREATED_TOPIC", "content.post.created"))
    indexer.start()
    yield
    indexer.stop()
    pool.close()


app = create_app("search", lifespan=lifespan)
auth = require_caller()


class Hit(BaseModel):
    id: int
    title: str
    author: str
    tags: list[str]
    score: float


class Results(BaseModel):
    query: str
    hits: list[Hit]


@app.get("/search", response_model=Results)
def search(q: str = Query(min_length=1, max_length=200), author: str | None = None,
           tag: str | None = Query(None, pattern=r"^[a-z0-9-]{1,32}$"),
           limit: int = Query(10, ge=1, le=50), _caller: str = Depends(auth)) -> Results:
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT post_id AS id, title, author, tags, ts_rank_cd(tsv, query) AS score
              FROM search.documents, websearch_to_tsquery('english', %(q)s) AS query
             WHERE tsv @@ query AND (%(author)s::text IS NULL OR author = %(author)s)
               AND (%(tag)s::text IS NULL OR %(tag)s = ANY (tags))
             ORDER BY score DESC, post_id DESC
             LIMIT %(limit)s
            """,
            {"q": q, "author": author, "tag": tag, "limit": limit},
        ).fetchall()
    return Results(query=q, hits=[Hit(**r) for r in rows])
