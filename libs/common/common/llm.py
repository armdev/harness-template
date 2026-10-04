"""Chat completions from an OpenAI-compatible endpoint: Ollama, vLLM, OpenAI, or Anthropic's OpenAI-compatible API.

A model is an external dependency, not a service of this system: plain HTTP(S) with an API key, never signed.

  model = ChatModel(os.environ["CHAT_LLM_URL"], model="qwen3:8b")
  for text in model.stream([{"role": "user", "content": "hi"}]):
      ...

`stream` raises ModelUnavailable when the endpoint cannot be reached or refuses the request; callers decide how
to degrade. ThinkFilter removes the <think>…</think> reasoning that some models (qwen3, deepseek-r1) put in the text.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx


class ModelUnavailable(Exception):
    """The model endpoint is unreachable, timed out, or answered with an error status."""


class ChatModel:
    def __init__(self, base_url: str, model: str, api_key: str = "not-needed", timeout: float = 180.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url, self.model = base_url.rstrip("/"), model
        self._http = httpx.Client(base_url=self.base_url or "http://unset.invalid", transport=transport,
                                  timeout=httpx.Timeout(timeout, connect=5.0),
                                  headers={"Authorization": f"Bearer {api_key}"})

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def stream(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 1024) -> Iterator[str]:
        """Yield the answer's text as the model produces it."""
        req = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
               "stream": True}
        try:
            with self._http.stream("POST", "/chat/completions", json=req) as r:
                if r.status_code != 200:
                    r.read()
                    raise ModelUnavailable(f"HTTP {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    text = delta_text(line)
                    if text is None:
                        break
                    if text:
                        yield text
        except httpx.HTTPError as e:
            raise ModelUnavailable(f"{type(e).__name__} calling {self.base_url}") from e

    def close(self) -> None:
        self._http.close()


def delta_text(line: str) -> str | None:
    """Text of one server-sent line of a streamed completion; '' for anything else, None at [DONE]."""
    if not line.startswith("data:"):
        return ""
    data = line[5:].strip()
    if data == "[DONE]":
        return None
    try:
        chunk = json.loads(data)
    except ValueError:
        return ""
    choices = chunk.get("choices") or [{}]
    return (choices[0].get("delta") or {}).get("content") or ""


class ThinkFilter:
    """Drops <think>…</think> from a stream of text pieces, also when a tag is split across pieces."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buf, self._inside = "", False

    def feed(self, piece: str) -> str:
        self._buf += piece
        out = []
        while True:
            tag = self.CLOSE if self._inside else self.OPEN
            i = self._buf.find(tag)
            if i < 0:
                break
            if not self._inside:
                out.append(self._buf[:i])
            self._buf, self._inside = self._buf[i + len(tag):], not self._inside
        keep = next((k for k in range(min(len(tag) - 1, len(self._buf)), 0, -1) if tag.startswith(self._buf[-k:])), 0)
        ready, self._buf = self._buf[:len(self._buf) - keep], self._buf[len(self._buf) - keep:]
        if not self._inside:
            out.append(ready)
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = ("" if self._inside else self._buf), ""
        return rest
