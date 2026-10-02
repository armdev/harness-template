from conftest import eventually


def test_new_post_becomes_searchable(api, author):
    post = api.post("/api/posts", json={"title": "Flyway placeholders", "author": author,
                                        "body": "Role passwords reach migrations through placeholders."}).json()

    def found():
        hits = api.get("/api/search", params={"q": "placeholders", "author": author}).json()["hits"]
        return [h for h in hits if h["id"] == post["id"]]

    hits = eventually(found)
    assert hits, "post was not indexed within the timeout"
    assert hits[0]["title"] == "Flyway placeholders" and hits[0]["author"] == author
    assert hits[0]["score"] > 0


def test_title_match_ranks_above_body_match(api, author):
    body_only = api.post("/api/posts", json={"title": "Unrelated", "body": "a note about migrations",
                                             "author": author}).json()
    in_title = api.post("/api/posts", json={"title": "Migrations", "body": "how schema changes ship",
                                            "author": author}).json()

    def ranked():
        hits = api.get("/api/search", params={"q": "migrations", "author": author}).json()["hits"]
        return [h["id"] for h in hits] if len(hits) == 2 else None

    assert eventually(ranked) == [in_title["id"], body_only["id"]]


def test_search_response_shape(api):
    r = api.get("/api/search", params={"q": "zzzz-no-such-term"})
    assert r.status_code == 200
    assert r.json() == {"query": "zzzz-no-such-term", "hits": []}


def test_search_validates_parameters(api):
    assert api.get("/api/search").status_code == 422
    assert api.get("/api/search", params={"q": "x", "limit": 0}).status_code == 422
    assert api.get("/api/search", params={"q": "x", "limit": 51}).status_code == 422
