"""Relay a service's response to our caller while it is still arriving, e.g. a chat answer as server-sent events.

  return await relay(clients["chat"], "POST", "/chat", service="chat", json=body)

A `text/event-stream` answer is passed through chunk by chunk; any other answer is read and returned whole, status
and body unchanged. The upstream is reached through a SignedClient, so the call is signed like every other.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, Response
from fastapi.responses import StreamingResponse

from common.service_auth import SignedClient

log = logging.getLogger(__name__)
STREAM_TIMEOUT = httpx.Timeout(10.0, read=180.0)    # a model may think for a while between two pieces of an answer


async def relay(client: SignedClient, method: str, path: str, service: str, **kw) -> Response:
    cm = client.astream(method, path, timeout=STREAM_TIMEOUT, **kw)
    try:
        upstream = await cm.__aenter__()
    except httpx.HTTPError as e:
        log.warning("upstream %s unavailable: %s", service, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} unavailable") from None
    media = upstream.headers.get("content-type", "application/json")
    if not media.startswith("text/event-stream"):
        try:
            body = await upstream.aread()
        except httpx.HTTPError as e:
            log.warning("upstream %s broke off: %s", service, type(e).__name__)
            raise HTTPException(status_code=502, detail=f"{service} unavailable") from None
        finally:
            await cm.__aexit__(None, None, None)
        return Response(content=body, status_code=upstream.status_code, media_type=media)

    async def chunks():
        try:
            async for chunk in upstream.aiter_bytes():   # decoded: we do not forward content-encoding
                yield chunk
        except httpx.HTTPError as e:
            log.warning("upstream %s stream broke off: %s", service, type(e).__name__)
        finally:                                          # also when our client disconnects (the task is cancelled)
            await cm.__aexit__(None, None, None)

    return StreamingResponse(chunks(), status_code=upstream.status_code, media_type=media,
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
