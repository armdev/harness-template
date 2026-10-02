"""Signed service-to-service calls (Ed25519).

The caller signs   METHOD \\n PATH[?QUERY] \\n UNIX-TIMESTAMP \\n SHA256-HEX(body)   with its private key and
sends X-Caller, X-Timestamp and X-Signature. The callee accepts a request only when the caller is listed in
its TRUSTED_CALLERS, the caller's public key is in KEYS_DIR/public/<caller>.pem, the signature verifies and
the timestamp is within MAX_CLOCK_SKEW seconds.

  client = SignedClient(os.environ["CONTENT_URL"])        # caller side; identity = SERVICE_NAME
  @app.get("/x", dependencies=[Depends(require_caller())]) # callee side
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from functools import lru_cache
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import HTTPException, Request

from common.telemetry import REQUEST_ID_HEADER, request_id

HEADER_CALLER, HEADER_TS, HEADER_SIG = "X-Caller", "X-Timestamp", "X-Signature"


def keys_dir() -> Path:
    return Path(os.environ.get("KEYS_DIR", "/run/keys"))


def canonical(method: str, target: str, timestamp: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), target, timestamp, hashlib.sha256(body).hexdigest())).encode()


def sign(key: Ed25519PrivateKey, method: str, target: str, body: bytes, now: float | None = None) -> dict[str, str]:
    ts = str(int(time.time() if now is None else now))
    sig = key.sign(canonical(method, target, ts, body))
    return {HEADER_TS: ts, HEADER_SIG: base64.b64encode(sig).decode()}


class AuthError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


class Verifier:
    def __init__(self, trusted: set[str], public_dir: Path, max_skew: int = 60):
        self.trusted, self.public_dir, self.max_skew = trusted, public_dir, max_skew

    @lru_cache(maxsize=64)  # noqa: B019 — one Verifier per process; keys never change while it runs
    def _public_key(self, caller: str) -> Ed25519PublicKey:
        key = serialization.load_pem_public_key((self.public_dir / f"{caller}.pem").read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError(f"{caller}: not an Ed25519 key")
        return key

    def verify(self, method: str, target: str, headers: dict[str, str], body: bytes, now: float | None = None) -> str:
        """Return the authenticated caller, or raise AuthError (401 unauthenticated, 403 not trusted)."""
        h = {k.lower(): v for k, v in headers.items()}
        caller, ts, sig = (h.get(x.lower()) for x in (HEADER_CALLER, HEADER_TS, HEADER_SIG))
        if not (caller and ts and sig):
            raise AuthError(401, "missing signature headers")
        if caller not in self.trusted:
            raise AuthError(403, f"caller '{caller}' is not in TRUSTED_CALLERS")
        try:
            if abs((time.time() if now is None else now) - int(ts)) > self.max_skew:
                raise AuthError(401, "timestamp outside the allowed clock skew")
            self._public_key(caller).verify(base64.b64decode(sig), canonical(method, target, ts, body))
        except AuthError:
            raise
        except (InvalidSignature, ValueError, OSError):
            raise AuthError(401, "invalid signature") from None
        return caller


def trusted_from_env() -> set[str]:
    return {c.strip() for c in os.environ.get("TRUSTED_CALLERS", "").split(",") if c.strip()}


def require_caller(verifier: Verifier | None = None):
    """FastAPI dependency: authenticate the signed caller; returns its service name."""
    v = verifier or Verifier(trusted_from_env(), keys_dir() / "public",
                             int(os.environ.get("MAX_CLOCK_SKEW", "60")))

    async def dependency(request: Request) -> str:
        target = request.scope.get("raw_path", request.url.path.encode()).decode()
        if request.url.query:
            target += "?" + request.url.query
        try:
            caller = v.verify(request.method, target, dict(request.headers), await request.body())
        except AuthError as e:
            raise HTTPException(status_code=e.status, detail=e.reason) from None
        request.state.caller = caller
        return caller

    return dependency


class SignedClient:
    """httpx client that signs every request as this service (SERVICE_NAME) and forwards the request id."""

    def __init__(self, base_url: str, identity: str | None = None, key_path: Path | None = None,
                 timeout: float = 5.0, transport: httpx.BaseTransport | None = None):
        self.identity = identity or os.environ["SERVICE_NAME"]
        path = key_path or keys_dir() / "self" / "private.pem"
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{path}: not an Ed25519 private key")
        self._key = key
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                  event_hooks={"request": [self._sign]})

    def _sign(self, request: httpx.Request) -> None:
        body = request.read()
        request.headers.update(sign(self._key, request.method, request.url.raw_path.decode(), body))
        request.headers[HEADER_CALLER] = self.identity
        if rid := request_id.get():
            request.headers[REQUEST_ID_HEADER] = rid

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        return self._http.request(method, url, **kw)

    def get(self, url: str, **kw) -> httpx.Response:
        return self._http.get(url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self._http.post(url, **kw)

    def close(self) -> None:
        self._http.close()
