"""rag-web: the portal serves its browser client and forwards /api/* to the gateway, unchanged."""
import httpx
import pytest
from conftest import WEB_URL


@pytest.fixture(scope="module")
def web():
    with httpx.Client(base_url=WEB_URL, timeout=10) as c:
        yield c


def test_portal_serves_its_client(web):
    r = web.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "rag-web" in r.text and "/static/app.js" in r.text
    for asset in ("/static/app.js", "/static/graph.js", "/static/style.css"):
        assert web.get(asset).status_code == 200, asset


def test_portal_forwards_reads_and_writes_to_the_gateway(web, api, author):
    created = web.post("/api/posts", json={"title": "Through the portal", "body": "Proxied.", "author": author,
                                          "tags": ["portal"]})
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    assert web.get(f"/api/posts/{post_id}").json() == api.get(f"/api/posts/{post_id}").json()
    assert web.get("/api/posts", params={"author": author}).json()["posts"][0]["id"] == post_id


def test_portal_passes_gateway_errors_through(web):
    assert web.get("/api/posts/999999999").status_code == 404
    assert web.post("/api/posts", json={"title": ""}).status_code == 422
    assert web.get("/api/search").status_code == 422


def test_portal_forwards_only_the_api(web):
    assert web.get("/api/../docs").status_code == 404
    assert web.get("/docs").status_code == 404
    assert web.delete("/api/posts/1").status_code == 405


def test_portal_refuses_an_oversized_body_with_413(web):
    assert web.post("/api/posts", content=b"x" * (64 * 1024 + 1),
                    headers={"content-type": "application/json"}).status_code == 413
