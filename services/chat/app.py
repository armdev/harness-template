"""chat: answers questions from the posts with a fixed retrieval pipeline and a language model.

search (posts matching the question's words) → graph (their closest neighbours: shared tags, same author)
→ content (full text) → model (answer citing [#id]), streamed as server-sent events:

  event: sources  data: [{id, title, author, tags, via: "search"|"graph", snippet}]   (once, first)
  event: token    data: {"text": "..."}                                                (the answer, piece by piece)
  event: done     data: {"citations": [id...], "model": "<name>" | null}              (once, last)
  event: error    data: {"detail": "..."}                                              (model failed mid-answer)

Without a reachable model (CHAT_LLM_URL empty or down) the answer lists the retrieved posts instead.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from common.llm import ChatModel, ModelUnavailable, ThinkFilter
from common.service_auth import SignedClient, require_caller
from common.telemetry import create_app
from rag import NO_SOURCES, build_messages, citations, event, fallback_answer, retrieval_words, search_query

log = logging.getLogger(__name__)
clients: dict[str, SignedClient] = {}
model = ChatModel(os.environ.get("CHAT_LLM_URL", ""), os.environ.get("CHAT_MODEL", "qwen3:8b"),
                  api_key=os.environ.get("CHAT_LLM_API_KEY", "not-needed"))
GRAPH_SEEDS, GRAPH_PER_SEED, GRAPH_MAX = 3, 2, 3      # neighbours of the 3 best hits, 2 each, at most 3 in total


@asynccontextmanager
async def lifespan(_app):
    for name in ("search", "graph", "content"):
        clients[name] = SignedClient(os.environ[f"{name.upper()}_URL"])
    yield
    for c in clients.values():
        c.close()
    model.close()


app = create_app("chat", lifespan=lifespan)
auth = require_caller()


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=20)
    k: int = Field(5, ge=1, le=10, description="posts to retrieve by search (the graph adds up to 3 more)")

    @field_validator("messages")
    @classmethod
    def ends_with_a_question(cls, v: list[Message]) -> list[Message]:
        if v[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        return v


def call(service: str, path: str, **params) -> httpx.Response:
    """Search is required: without it there is nothing to answer from (502)."""
    try:
        return clients[service].get(path, params=params)
    except httpx.HTTPError as e:
        log.warning("upstream %s unavailable: %s", service, type(e).__name__)
        raise HTTPException(status_code=502, detail=f"{service} unavailable") from None


def optional(service: str, path: str, **params) -> httpx.Response | None:
    """Graph neighbours and single posts only enrich the answer: on trouble, answer without them."""
    try:
        r = clients[service].get(path, params=params)
    except httpx.HTTPError as e:
        log.warning("%s unavailable, answering without it: %s", service, type(e).__name__)
        return None
    return r if r.status_code == 200 else None


def retrieve(user_turns: list[str], k: int) -> list[dict]:
    """The posts the answer may use: search hits first, then graph neighbours of the best hits, with full text."""
    words = retrieval_words(user_turns)
    if not words:
        return []
    r = call("search", "/search", q=search_query(words), limit=k)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"search answered {r.status_code}")
    found = [{"id": h["id"], "via": "search"} for h in r.json()["hits"]]
    seen = {f["id"] for f in found}
    added = 0
    for hit in found[:GRAPH_SEEDS]:
        r = optional("graph", f"/related/{hit['id']}", limit=GRAPH_PER_SEED)
        if r is None:                                  # not in the graph yet, or graph down: the hit still counts
            continue
        for rel in r.json()["related"]:
            if rel["id"] not in seen and added < GRAPH_MAX:
                found.append({"id": rel["id"], "via": "graph", "near": hit["id"]})
                seen.add(rel["id"])
                added += 1
    sources = []
    for f in found:
        r = optional("content", f"/posts/{f['id']}")
        if r is not None:
            p = r.json()
            sources.append({**f, "title": p["title"], "author": p["author"], "tags": p["tags"], "body": p["body"]})
    return sources


def answer(history: list[dict], sources: list[dict]) -> Iterator[str]:
    yield event("sources", [{k: v for k, v in s.items() if k != "body"} | {"snippet": s["body"][:240]}
                            for s in sources])
    if not sources:
        yield event("token", {"text": NO_SOURCES})
        yield event("done", {"citations": [], "model": None})
        return
    if not model.configured:
        yield from degrade(sources, "CHAT_LLM_URL is not set")
        return
    think, text = ThinkFilter(), []
    try:
        for piece in model.stream(build_messages(history, sources)):
            out = think.feed(piece)
            if not text:
                out = out.lstrip()
            if out:
                text.append(out)
                yield event("token", {"text": out})
        if rest := think.flush():
            text.append(rest)
            yield event("token", {"text": rest})
    except ModelUnavailable as e:
        log.warning("model unavailable: %s", e)
        if not text:
            yield from degrade(sources, "the model is unavailable")
            return
        yield event("error", {"detail": "the model stopped answering"})
    if not text:                                       # e.g. a reasoning model spent its budget inside <think>
        yield from degrade(sources, "the model returned no answer")
        return
    full = "".join(text)
    yield event("done", {"citations": citations(full, sources), "model": model.model})


def degrade(sources: list[dict], reason: str) -> Iterator[str]:
    text = fallback_answer(sources, reason)
    yield event("token", {"text": text})
    yield event("done", {"citations": citations(text, sources), "model": None})


@app.post("/chat")
def chat(body: ChatIn, _caller: str = Depends(auth)) -> StreamingResponse:
    history = [m.model_dump() for m in body.messages]
    sources = retrieve([m.content for m in body.messages if m.role == "user"], body.k)
    log.info("chat: %d sources (%d from the graph)", len(sources), sum(s["via"] == "graph" for s in sources))
    return StreamingResponse(answer(history, sources), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
