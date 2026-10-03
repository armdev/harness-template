"""notify records one notification per new post (from content.post.created), listed through the gateway."""
from conftest import eventually


def test_new_post_creates_one_notification(api, author):
    post = api.post("/api/posts", json={"title": "Notify me", "body": "Please.", "author": author}).json()

    def recorded():
        r = api.get("/api/notifications", params={"author": author})
        return r.json()["notifications"] if r.status_code == 200 else None

    notes = eventually(recorded)
    assert notes, "no notification recorded within the timeout"
    assert notes == [{"post_id": post["id"], "author": author, "created_at": notes[0]["created_at"]}]
    assert notes[0]["created_at"][:19] == post["created_at"][:19]


def test_notifications_are_newest_first_and_limited(api, author):
    ids = [api.post("/api/posts", json={"title": f"N{i}", "body": "b", "author": author}).json()["id"]
           for i in range(3)]

    def all_three():
        notes = api.get("/api/notifications", params={"author": author}).json()["notifications"]
        return notes if len(notes) == 3 else None

    assert [n["post_id"] for n in eventually(all_three)] == list(reversed(ids))
    limited = api.get("/api/notifications", params={"author": author, "limit": 1}).json()["notifications"]
    assert [n["post_id"] for n in limited] == [ids[-1]]


def test_unknown_author_has_no_notifications(api, author):
    r = api.get("/api/notifications", params={"author": author})
    assert r.status_code == 200
    assert r.json() == {"author": author, "notifications": []}


def test_notifications_validate_parameters(api, author):
    assert api.get("/api/notifications").status_code == 422
    assert api.get("/api/notifications", params={"author": "no spaces allowed"}).status_code == 422
    assert api.get("/api/notifications", params={"author": author, "limit": 51}).status_code == 422
