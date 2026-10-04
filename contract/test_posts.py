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


def test_list_by_author_returns_newest_first(api, author):
    ids = [new_post(api, author, title=f"Post {i}").json()["id"] for i in range(3)]
    r = api.get("/api/posts", params={"author": author})
    assert r.status_code == 200
    body = r.json()
    assert body["author"] == author
    assert [p["id"] for p in body["posts"]] == list(reversed(ids))
    assert body["posts"][0] == api.get(f"/api/posts/{ids[-1]}").json()


def test_list_by_author_only_returns_that_author(api, author):
    mine = new_post(api, author).json()["id"]
    new_post(api, author + "-other")
    posts = api.get("/api/posts", params={"author": author}).json()["posts"]
    assert [p["id"] for p in posts] == [mine]


def test_list_by_author_respects_limit(api, author):
    ids = [new_post(api, author).json()["id"] for _ in range(3)]
    posts = api.get("/api/posts", params={"author": author, "limit": 2}).json()["posts"]
    assert [p["id"] for p in posts] == [ids[2], ids[1]]


def test_list_by_unknown_author_is_empty(api, author):
    r = api.get("/api/posts", params={"author": author})
    assert r.status_code == 200
    assert r.json() == {"author": author, "posts": []}


def test_list_validates_parameters(api, author):
    assert api.get("/api/posts").status_code == 422                                  # author is required
    assert api.get("/api/posts", params={"author": "not an author!"}).status_code == 422
    assert api.get("/api/posts", params={"author": author, "limit": 0}).status_code == 422
    assert api.get("/api/posts", params={"author": author, "limit": 51}).status_code == 422


def test_list_by_author_pages_with_the_before_cursor(api, author):
    ids = [new_post(api, author, title=f"Page {i}").json()["id"] for i in range(5)]
    newest_first = ids[::-1]

    def page(**params):
        r = api.get("/api/posts", params={"author": author, "limit": 2, **params})
        assert r.status_code == 200, r.text
        return [p["id"] for p in r.json()["posts"]]

    first = page()
    second = page(before=first[-1])
    third = page(before=second[-1])
    assert first + second + third == newest_first
    assert page(before=third[-1]) == []


def test_list_validates_the_before_cursor(api, author):
    for bad in (0, -1, "x"):
        assert api.get("/api/posts", params={"author": author, "before": bad}).status_code == 422


def test_a_cursor_beyond_any_id_is_422_not_500(api, author):
    assert api.get("/api/posts", params={"author": author, "before": 2**64}).status_code == 422
