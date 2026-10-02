def new_post(api, author, **overrides):
    payload = {"title": "Signed calls", "body": "Every internal call is signed with Ed25519.", "author": author}
    return api.post("/api/posts", json=payload | overrides)


def test_create_returns_the_stored_post(api, author):
    r = new_post(api, author)
    assert r.status_code == 201
    post = r.json()
    assert isinstance(post["id"], int)
    assert post["title"] == "Signed calls" and post["author"] == author
    assert post["created_at"]


def test_get_returns_what_was_created(api, author):
    created = new_post(api, author).json()
    r = api.get(f"/api/posts/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_unknown_post_is_404(api):
    assert api.get("/api/posts/987654321").status_code == 404


def test_ids_are_unique(api, author):
    ids = {new_post(api, author).json()["id"] for _ in range(3)}
    assert len(ids) == 3


def test_invalid_posts_are_rejected(api, author):
    assert new_post(api, author, title="").status_code == 422
    assert new_post(api, author, body="").status_code == 422
    assert new_post(api, author, title="x" * 201).status_code == 422
    assert new_post(api, "not an author!").status_code == 422
