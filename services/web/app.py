"""web (rag-web): the portal. Serves the browser client and forwards its /api calls to the gateway.

Holds no data; every /api call goes to the gateway's public API, signed as `web` like any service-to-service call.
Same origin for the page and its API, so the browser needs no CORS.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from common.service_auth import SignedClient
from common.telemetry import create_app

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024                       # a post is far smaller; anything bigger is not a client of this portal
FORWARDED_HEADERS = ("content-type",)          # the request id travels by itself (SignedClient)
gateway: dict[str, SignedClient] = {}


@asynccontextmanager
async def lifespan(_app):
    gateway["client"] = SignedClient(os.environ["GATEWAY_URL"], timeout=15)
    yield
    gateway["client"].close()


app = create_app("web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.api_route("/api/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def api(path: str, request: Request) -> Response:
    if ".." in path.split("/"):
        raise HTTPException(status_code=404, detail="not found")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="request body too large")
    headers = {h: request.headers[h] for h in FORWARDED_HEADERS if h in request.headers}
    try:
        r = await run_in_threadpool(gateway["client"].request, request.method, f"/api/{path}",
                                    params=request.query_params, content=body or None, headers=headers)
    except httpx.HTTPError as e:
        log.warning("gateway unavailable: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="gateway unavailable") from None
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))

