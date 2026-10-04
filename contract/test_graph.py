"""Knowledge graph: posts linked through their authors and tags (service `graph`, Neo4j).

The graph is built from content.post.created events, so every read waits with `eventually`. Tags are made unique
per test: the graph is shared by every test that ever ran against this stack.
"""
import uuid

from conftest import eventually


def tag() -> str:
    return "t" + uuid.uuid4().hex[:10]


def post(api, author, title, tags=()):
    r = api.post("/api/posts", json={"title": title, "body": "Graph contract.", "author": author, "tags": list(tags)})
    assert r.status_code == 201, r.text
    return r.json()


def related(api, post_id, **params):
    return api.get(f"/api/posts/{post_id}/related", params=params)


def test_related_posts_are_ranked_by_shared_tags_and_author(api, author):
    a, b, c = tag(), tag(), tag()
    origin = post(api, author, "Origin", [a, b])
    two_tags = post(api, author + "-x", "Shares two tags", [a, b, c])
    one_tag = post(api, author + "-y", "Shares one tag", [b])
    same_author = post(api, author, "Same author, no tags")
    unrelated = post(api, author + "-z", "Unrelated", [c])

    def ready():
        r = related(api, origin["id"])
        return r.status_code == 200 and len(r.json()["related"]) >= 3 and r.json()

    body = eventually(ready)
    assert body, "the graph did not link the posts in time"
    ids = [x["id"] for x in body["related"]]
    assert body["post_id"] == origin["id"]
    assert ids[0] == two_tags["id"]                                     # two shared tags rank first
    assert set(ids) == {two_tags["id"], one_tag["id"], same_author["id"]}
    assert unrelated["id"] not in ids and origin["id"] not in ids
    first = body["related"][0]
    assert sorted(first["shared_tags"]) == sorted([a, b]) and first["same_author"] is False
    assert first["score"] == 2 and first["author"] == author + "-x" and first["title"] == "Shares two tags"
    by_id = {x["id"]: x for x in body["related"]}
    assert by_id[same_author["id"]]["same_author"] is True and by_id[same_author["id"]]["shared_tags"] == []


def test_related_respects_limit(api, author):
    a = tag()
    origin = post(api, author, "Origin", [a])
    for n in range(3):
        post(api, f"{author}-{n}", f"Neighbour {n}", [a])
    assert eventually(lambda: len(related(api, origin["id"]).json().get("related", [])) == 3)
    assert len(related(api, origin["id"], limit=2).json()["related"]) == 2


def test_related_of_an_unknown_post_is_404(api):
    assert related(api, 999_999_999).status_code == 404


def test_related_validates_parameters(api):
    assert related(api, 1, limit=0).status_code == 422
    assert related(api, 1, limit=51).status_code == 422
    assert api.get("/api/posts/not-a-number/related").status_code == 422


def test_tag_neighbourhood_counts_posts_and_co_occurring_tags(api, author):
    a, b, c = tag(), tag(), tag()
    post(api, author, "One", [a, b])
    post(api, author, "Two", [a, b])
    post(api, author, "Three", [a, c])

    def ready():
        r = api.get(f"/api/tags/{a}")
        return r.status_code == 200 and r.json()["posts"] == 3 and r.json()

    body = eventually(ready)
    assert body, "the graph did not count the tag's posts in time"
    assert body["tag"] == a
    assert body["related"] == [{"tag": b, "together": 2}, {"tag": c, "together": 1}]


def test_unknown_tag_is_404_and_invalid_tag_is_422(api):
    assert api.get(f"/api/tags/{tag()}").status_code == 404
    assert api.get("/api/tags/Not_Valid").status_code == 422
