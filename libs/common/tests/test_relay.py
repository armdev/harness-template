import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.keygen import ensure_key
from common.relay import relay
from common.service_auth import SignedClient

SSE = b"event: token\ndata: {\"text\": \"hi\"}\n\nevent: done\ndata: {}\n\n"


def app_relaying_to(handler, tmp_path) -> TestClient:
    ensure_key(tmp_path, "web")
    upstream = SignedClient("http://up.test", identity="web", key_path=tmp_path / "web" / "private.pem",
                            transport=httpx.MockTransport(handler))
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def proxy(path: str):
        return await relay(upstream, "POST", f"/{path}", service="up", json={"q": 1})

    return TestClient(app)


def test_event_stream_is_passed_through_and_the_call_is_signed(tmp_path):
    seen = {}

    def handler(request):
        seen["caller"] = request.headers.get("x-caller")
        return httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})

    r = app_relaying_to(handler, tmp_path).post("/chat")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.content == SSE and seen["caller"] == "web"


def test_other_answers_keep_status_and_body(tmp_path):
    r = app_relaying_to(lambda req: httpx.Response(422, json={"detail": "bad"}), tmp_path).post("/chat")
    assert r.status_code == 422 and r.json() == {"detail": "bad"}


def test_unreachable_upstream_is_502(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    r = app_relaying_to(refuse, tmp_path).post("/chat")
    assert r.status_code == 502 and r.json()["detail"] == "up unavailable"
