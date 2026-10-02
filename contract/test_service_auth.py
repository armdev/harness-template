"""Internal services accept only signed calls from their TRUSTED_CALLERS."""
import httpx
from conftest import CONTENT_URL


def test_unsigned_call_to_internal_service_is_rejected():
    r = httpx.get(f"{CONTENT_URL}/posts/1", timeout=5)
    assert r.status_code == 401


def test_forged_caller_header_is_rejected():
    r = httpx.get(f"{CONTENT_URL}/posts/1", timeout=5,
                  headers={"X-Caller": "gateway", "X-Timestamp": "0", "X-Signature": "AAAA"})
    assert r.status_code == 401


def test_health_and_metrics_are_open():
    assert httpx.get(f"{CONTENT_URL}/healthz", timeout=5).status_code == 200
    assert "http_requests_total" in httpx.get(f"{CONTENT_URL}/metrics", timeout=5).text
