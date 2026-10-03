"""Optional tags on posts: stored with the post, returned everywhere, filterable in search."""
import pytest
from conftest import eventually


def post(api, author, **extra):
    return api.post("/api/posts", json={"title": "Tagged", "body": "A post about pipelines.", "author": author} | extra)


def test_tags_are_stored_and_returned(api, author):
    created = post(api, author, tags=["kafka", "flyway"]).json()
    assert created["tags"] == ["kafka", "flyway"]
    assert api.get(f"/api/posts/{created['id']}").json()["tags"] == ["kafka", "flyway"]
    listed = api.get("/api/posts", params={"author": author}).json()["posts"]
    assert listed[0]["tags"] == ["kafka", "flyway"]


def test_posts_without_tags_have_an_empty_list(api, author):
    created = post(api, author).json()
    assert created["tags"] == []
    assert api.get(f"/api/posts/{created['id']}").json()["tags"] == []


@pytest.mark.parametrize("tags", [
    ["a", "b", "c", "d", "e", "f"],      # more than 5
    ["Kafka"],                           # upper case
    [""],                                # empty
    ["x" * 33],                          # longer than 32
    ["two words"],                       # space
    ["under_score"],                     # only a-z, 0-9 and -
    "kafka",                             # not a list
])
def test_invalid_tags_are_rejected(api, author, tags):
    assert post(api, author, tags=tags).status_code == 422


def test_search_filters_by_tag(api, author):
    tagged = post(api, author, title="Event pipelines", tags=["kafka"]).json()
    plain = post(api, author, title="Event pipelines").json()

    def both_indexed():
        hits = api.get("/api/search", params={"q": "pipelines", "author": author}).json()["hits"]
        return len(hits) == 2

    assert eventually(both_indexed), "posts were not indexed within the timeout"
    hits = api.get("/api/search", params={"q": "pipelines", "author": author, "tag": "kafka"}).json()["hits"]
    assert [h["id"] for h in hits] == [tagged["id"]]
    assert hits[0]["tags"] == ["kafka"]
    unfiltered = api.get("/api/search", params={"q": "pipelines", "author": author}).json()["hits"]
    assert {h["id"] for h in unfiltered} == {tagged["id"], plain["id"]}


def test_search_validates_tag(api):
    assert api.get("/api/search", params={"q": "x", "tag": "Not A Tag"}).status_code == 422
