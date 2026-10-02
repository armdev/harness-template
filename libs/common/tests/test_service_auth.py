import json
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from common.keygen import ensure_key
from common.service_auth import AuthError, SignedClient, Verifier


@pytest.fixture()
def keys(tmp_path):
    for name in ("gateway", "search", "intruder"):
        ensure_key(tmp_path, name)
    return tmp_path


def make_app(keys, trusted):
    from common.service_auth import require_caller

    app = FastAPI()
    auth = require_caller(Verifier(trusted, keys / "public"))

    @app.post("/posts")
    def create(payload: dict, caller: str = Depends(auth)):
        return {"caller": caller, "payload": payload}

    @app.get("/search")
    def search(q: str, caller: str = Depends(auth)):
        return {"caller": caller, "q": q}

    return app


def client_for(keys, app, identity):
    tc = TestClient(app, base_url="http://callee")
    return SignedClient("http://callee", identity=identity, key_path=keys / identity / "private.pem",
                        transport=tc._transport)


def test_trusted_caller_is_accepted(keys):
    c = client_for(keys, make_app(keys, {"gateway"}), "gateway")
    r = c.post("/posts", json={"title": "t"})
    assert r.status_code == 200, r.text
    assert r.json() == {"caller": "gateway", "payload": {"title": "t"}}


def test_query_string_is_signed(keys):
    c = client_for(keys, make_app(keys, {"gateway"}), "gateway")
    r = c.get("/search", params={"q": "kafka topics"})
    assert r.status_code == 200 and r.json()["q"] == "kafka topics"


def test_untrusted_caller_is_forbidden(keys):
    c = client_for(keys, make_app(keys, {"gateway"}), "search")
    assert c.post("/posts", json={}).status_code == 403


def test_unsigned_request_is_unauthenticated(keys):
    tc = TestClient(make_app(keys, {"gateway"}))
    assert tc.post("/posts", json={}).status_code == 401


def test_identity_spoofing_fails(keys):
    # intruder signs with its own key but claims to be gateway
    c = client_for(keys, make_app(keys, {"gateway"}), "intruder")
    c.identity = "gateway"
    assert c.post("/posts", json={}).status_code == 401


def test_tampered_body_fails(keys):
    v = Verifier({"gateway"}, keys / "public")
    from cryptography.hazmat.primitives import serialization

    from common.service_auth import sign

    key = serialization.load_pem_private_key((keys / "gateway" / "private.pem").read_bytes(), None)
    headers = {**sign(key, "POST", "/posts", b'{"a":1}'), "X-Caller": "gateway"}
    assert v.verify("POST", "/posts", headers, b'{"a":1}') == "gateway"
    with pytest.raises(AuthError) as e:
        v.verify("POST", "/posts", headers, json.dumps({"a": 2}).encode())
    assert e.value.status == 401


def test_stale_timestamp_fails(keys):
    v = Verifier({"gateway"}, keys / "public", max_skew=60)
    from cryptography.hazmat.primitives import serialization

    from common.service_auth import sign

    key = serialization.load_pem_private_key((keys / "gateway" / "private.pem").read_bytes(), None)
    headers = {**sign(key, "GET", "/x", b"", now=time.time() - 120), "X-Caller": "gateway"}
    with pytest.raises(AuthError):
        v.verify("GET", "/x", headers, b"")


def test_keygen_is_idempotent(tmp_path):
    assert ensure_key(tmp_path, "content") is True
    before = (tmp_path / "content" / "private.pem").read_bytes()
    assert ensure_key(tmp_path, "content") is False
    assert (tmp_path / "content" / "private.pem").read_bytes() == before
