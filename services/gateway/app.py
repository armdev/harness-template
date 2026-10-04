"""gateway: the public HTTP API. Holds no data; every call goes to an internal service, signed as `gateway`."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Body, HTTPException, Path, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from common.service_auth import SignedClient
from common.telemetry import create_app

log = logging.getLogger(__name__)
clients: dict[str, SignedClient] = {}


@asynccontextmanager
async def lifespan(_app):
    clients["content"] = SignedClient(os.environ["CONTENT_URL"])
    clients["search"] = SignedClient(os.environ["SEARCH_URL"])
    clients["notify"] = SignedClient(os.environ["NOTIFY_URL"])
    clients["graph"] = SignedClient(os.environ["GRAPH_URL"])
    yield
    for c in clients.values():
        c.close()


app = create_app("gateway", lifespan=lifespan, description=(
    "Public API of air-harness. Every call is forwarded, signed as `gateway`, to the service that owns the data. "
    "The contract suite in `contract/` is the specification of this API."))

POST_EXAMPLE = {"title": "Hello air-harness", "body": "My first post, searchable in a second.", "author": "me",
                "tags": ["intro"]}


async def forward(service: str, method: str, path: str, **kw) -> Response:
    try:
        r = await run_in_threadpool(clients[service].request, method, path, **kw)
    except httpx.HTTPError as e:
        log.warning("upstream %s unavailable: %s", service, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} unavailable") from None
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.post("/api/posts", status_code=201, summary="Create a post (validated and stored by content)")
async def create_post(post: dict = Body(examples=[POST_EXAMPLE])) -> Response:  # noqa: B008 — FastAPI idiom
    return await forward("content", "POST", "/posts", json=post)


@app.get("/api/posts", summary="List one author's posts, newest first")
async def list_posts(author: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
                     limit: int = Query(20, ge=1, le=50)) -> Response:
    return await forward("content", "GET", "/posts", params={"author": author, "limit": limit})


@app.get("/api/posts/{post_id}", summary="Read a post")
async def get_post(post_id: int) -> Response:
    return await forward("content", "GET", f"/posts/{post_id}")


@app.get("/api/search", summary="Full-text search over posts (indexed asynchronously via Kafka)")
async def search(q: str = Query(min_length=1, max_length=200), author: str | None = None,
                 tag: str | None = Query(None, pattern=r"^[a-z0-9-]{1,32}$"),
                 limit: int = Query(10, ge=1, le=50)) -> Response:
    params = {"q": q, "limit": limit} | ({"author": author} if author else {}) | ({"tag": tag} if tag else {})
    return await forward("search", "GET", "/search", params=params)


@app.get("/api/notifications", summary="Notifications recorded for an author's posts, newest first")
async def notifications(author: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
                        limit: int = Query(20, ge=1, le=50)) -> Response:
    return await forward("notify", "GET", "/outbox", params={"author": author, "limit": limit})


@app.get("/api/posts/{post_id}/related",
         summary="Posts related through shared tags or the same author (knowledge graph)")
async def related_posts(post_id: int, limit: int = Query(10, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", f"/related/{post_id}", params={"limit": limit})


@app.get("/api/tags/{tag}", summary="A tag in the knowledge graph: how many posts carry it, which tags appear with it")
async def tag_neighbourhood(tag: str = Path(pattern=r"^[a-z0-9-]{1,32}$"),
                            limit: int = Query(10, ge=1, le=50)) -> Response:
    return await forward("graph", "GET", f"/tags/{tag}", params={"limit": limit})
