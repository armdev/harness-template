"""content: owns posts. Writes to its own schema as content_svc and announces each new post on Kafka."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from confluent_kafka import Producer
from fastapi import Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, StringConstraints

from common.service_auth import require_caller
from common.telemetry import create_app

log = logging.getLogger(__name__)
TOPIC = os.environ.get("POST_CREATED_TOPIC", "content.post.created")

pool = ConnectionPool(os.environ.get("DB_DSN", ""), open=False, kwargs={"row_factory": dict_row})
producer: Producer | None = None


@asynccontextmanager
async def lifespan(_app):
    global producer
    pool.open(wait=True, timeout=30)
    producer = Producer({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP"], "acks": "all",
                         "enable.idempotence": True, "client.id": "content"})
    yield
    producer.flush(10)
    pool.close()


app = create_app("content", lifespan=lifespan)
auth = require_caller()


AUTHOR_PATTERN = r"^[A-Za-z0-9._-]+$"
MAX_ID = 2**63 - 1                  # ids are bigint; a larger cursor is a client error, not a 500
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    author: str = Field(min_length=1, max_length=64, pattern=AUTHOR_PATTERN)
    tags: list[Tag] = Field(default_factory=list, max_length=5)


class Post(PostIn):
    id: int
    created_at: datetime


class AuthorPosts(BaseModel):
    author: str
    posts: list[Post]


@app.post("/posts", status_code=201, response_model=Post)
def create_post(post: PostIn, caller: str = Depends(auth)) -> Post:
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO content.posts (title, body, author, tags) VALUES (%s, %s, %s, %s) RETURNING id, created_at",
            (post.title, post.body, post.author, post.tags),
        ).fetchone()
    created = Post(**post.model_dump(), **row)
    producer.produce(TOPIC, key=str(created.id), value=created.model_dump_json())
    remaining = producer.flush(5)
    if remaining:
        log.error("post %s stored but its event was not acknowledged by Kafka", created.id)
    log.info("post %s created (caller %s)", created.id, caller)
    return created


@app.get("/posts/{post_id}", response_model=Post)
def get_post(post_id: int, _caller: str = Depends(auth)) -> Post:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT id, title, body, author, tags, created_at FROM content.posts WHERE id = %s", (post_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return Post(**row)


@app.get("/posts", response_model=AuthorPosts)
def list_posts(author: str = Query(min_length=1, max_length=64, pattern=AUTHOR_PATTERN),
               limit: int = Query(20, ge=1, le=50),
               before: int | None = Query(None, ge=1, le=MAX_ID, description="next page: posts with an id below this"),
               _caller: str = Depends(auth)) -> AuthorPosts:
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, author, tags, created_at FROM content.posts
             WHERE author = %(author)s AND (%(before)s::bigint IS NULL OR id < %(before)s)
             ORDER BY id DESC LIMIT %(limit)s
            """,
            {"author": author, "before": before, "limit": limit},
        ).fetchall()
    return AuthorPosts(author=author, posts=[Post(**r) for r in rows])
