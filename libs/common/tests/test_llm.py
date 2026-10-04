import json

import httpx
import pytest

from common.llm import ChatModel, ModelUnavailable, ThinkFilter, delta_text


def sse(*pieces: str) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
    return ("\n\n".join(lines + ["data: [DONE]"]) + "\n\n").encode()


def model(handler) -> ChatModel:
    return ChatModel("http://llm.test/v1", "m", api_key="k", transport=httpx.MockTransport(handler))


def test_stream_yields_the_text_pieces_and_sends_the_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(
            request.content)
        return httpx.Response(200, content=sse("Hel", "lo", "!"), headers={"content-type": "text/event-stream"})

    assert "".join(model(handler).stream([{"role": "user", "content": "hi"}])) == "Hello!"
    assert seen["url"] == "http://llm.test/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"]["stream"] is True and seen["body"]["model"] == "m"


def test_stream_stops_at_done_and_skips_noise():
    body = b": keep-alive\n\ndata: {not json}\n\n" + sse("a") + sse("never")
    assert list(model(lambda r: httpx.Response(200, content=body)).stream([])) == ["a"]


def test_error_status_and_unreachable_endpoint_raise_model_unavailable():
    with pytest.raises(ModelUnavailable, match="HTTP 401"):
        list(model(lambda r: httpx.Response(401, text="bad key")).stream([]))

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ModelUnavailable, match="ConnectError"):
        list(model(refuse).stream([]))


def test_unconfigured_model():
    assert not ChatModel("", "m").configured and ChatModel("http://x/v1", "m").configured


def test_delta_text():
    assert delta_text("data: [DONE]") is None
    assert delta_text("event: x") == "" and delta_text('data: {"choices": []}') == ""


@pytest.mark.parametrize("pieces", [
    ["<think>plan</think>Answer"],
    ["<thi", "nk>pl", "an</th", "ink>Ans", "wer"],
    ["<think>", "a", "</think>", "Answer"],
])
def test_think_filter_drops_reasoning_even_when_tags_are_split(pieces):
    f = ThinkFilter()
    assert "".join(f.feed(p) for p in pieces) + f.flush() == "Answer"


def test_think_filter_keeps_text_and_lone_angle_brackets():
    f = ThinkFilter()
    assert "".join(f.feed(p) for p in ["a < b", " and <t", "ag>"]) + f.flush() == "a < b and <tag>"
