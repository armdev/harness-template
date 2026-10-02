"""gateway: the public HTTP API. Holds no data; every call goes to an internal service, signed as `gateway`."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from common.service_auth import SignedClient
from common.telemetry import create_app

log = logging.getLogger(__name__)
clients: dict[str, SignedClient] = {}


@asynccontextmanager
async def lifespan(_app):
    clients["content"] = SignedClient(os.environ["CONTENT_URL"])
    clients["search"] = SignedClient(os.environ["SEARCH_URL"])
    yield
    for c in clients.values():
        c.close()


app = create_app("gateway", lifespan=lifespan)


async def forward(service: str, method: str, path: str, **kw) -> Response:
    try:
        r = await run_in_threadpool(clients[service].request, method, path, **kw)
    except httpx.HTTPError as e:
        log.warning("upstream %s unavailable: %s", service, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} unavailable") from None
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


@app.post("/api/posts", status_code=201)
async def create_post(request: Request) -> Response:
    return await forward("content", "POST", "/posts", content=await request.body(),
                         headers={"Content-Type": "application/json"})


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int) -> Response:
    return await forward("content", "GET", f"/posts/{post_id}")


@app.get("/api/search")
async def search(q: str = Query(min_length=1, max_length=200), author: str | None = None,
                 limit: int = Query(10, ge=1, le=50)) -> Response:
    params = {"q": q, "limit": limit} | ({"author": author} if author else {})
    return await forward("search", "GET", "/search", params=params)
