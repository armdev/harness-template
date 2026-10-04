"""web (rag-web): the portal. Serves the browser client and forwards its /api calls to the gateway.

Holds no data; every /api call goes to the gateway's public API, signed as `web` like any service-to-service call,
and the answer is relayed as it arrives (the chat answer streams as server-sent events).
Same origin for the page and its API, so the browser needs no CORS.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from common.relay import relay
from common.service_auth import SignedClient
from common.telemetry import create_app

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024                       # a post is far smaller; anything bigger is not a client of this portal
FORWARDED_HEADERS = ("content-type",)          # the request id travels by itself (SignedClient)
gateway: dict[str, SignedClient] = {}


@asynccontextmanager
async def lifespan(_app):
    gateway["client"] = SignedClient(os.environ["GATEWAY_URL"], timeout=15)
    yield
    gateway["client"].close()
    await gateway["client"].aclose()


app = create_app("web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def read_limited(request: Request) -> bytes:
    """The request body, refused (413) as soon as it is known to exceed MAX_BODY: never buffered whole first."""
    too_large = HTTPException(status_code=413, detail="request body too large")
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise too_large
    return bytes(body)


@app.api_route("/api/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def api(path: str, request: Request) -> Response:
    if ".." in path.split("/"):
        raise HTTPException(status_code=404, detail="not found")
    body = await read_limited(request)
    headers = {h: request.headers[h] for h in FORWARDED_HEADERS if h in request.headers}
    return await relay(gateway["client"], request.method, f"/api/{path}", service="gateway",
                       params=request.query_params, content=body or None, headers=headers)

