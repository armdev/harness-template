"""Chat: a fixed retrieval pipeline (search → graph → content) and a model that answers citing [#id], streamed.

Holds with or without a reachable model: without one the answer lists the retrieved posts. So the tests check
the pipeline and the protocol, never the model's wording.
"""
import json
import uuid

from conftest import eventually


def word() -> str:
    return "zq" + uuid.uuid4().hex[:10]


def ask(api, *turns: str, **extra):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(turns)]
    return api.post("/api/chat", json={"messages": messages, **extra}, timeout=200)


def events(r) -> list[tuple[str, object]]:
    """Parse a text/event-stream body into (event, data) pairs."""
    out = []
    for block in r.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def post(api, author, title, body, tags):
    r = api.post("/api/posts", json={"title": title, "body": body, "author": author, "tags": tags})
    assert r.status_code == 201, r.text
    return r.json()


def test_answer_streams_sources_then_tokens_then_done_and_cites_only_sources(api, author):
    w, t = word(), "t" + uuid.uuid4().hex[:10]
    hit = post(api, author, f"About {w}", f"The {w} pipeline commits offsets after the write.", [t])
    neighbour = post(api, author + "-n", "A neighbour", "Shares only a tag with the hit.", [t])

    def ready():
        r = ask(api, f"What do we know about {w}?")
        if r.status_code != 200:
            return None
        ev = events(r)
        ids = {s["id"] for s in ev[0][1]}
        return {hit["id"], neighbour["id"]} <= ids and (r, ev)

    found = eventually(ready, timeout=40, interval=1)
    assert found, "the post and its graph neighbour never became sources"
    r, ev = found
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [e for e, _ in ev]
    assert names[0] == "sources" and names[-1] in ("done", "error") and names.count("sources") == 1
    assert set(names[1:-1]) <= {"token"} and "token" in names
    sources = {s["id"]: s for s in ev[0][1]}
    assert sources[hit["id"]]["via"] == "search"
    assert sources[neighbour["id"]]["via"] == "graph" and sources[neighbour["id"]]["near"] == hit["id"]
    assert sources[hit["id"]]["title"] == f"About {w}" and w in sources[hit["id"]]["snippet"]
    assert "body" not in sources[hit["id"]]
    answer = "".join(d["text"] for e, d in ev if e == "token")
    assert answer.strip()
    if names[-1] == "done":
        assert set(ev[-1][1]["citations"]) <= set(sources)


def test_a_question_matching_nothing_says_so_without_sources(api):
    ev = events(ask(api, f"Anything on {word()} {word()}?"))
    assert ev[0] == ("sources", []) and ev[-1] == ("done", {"citations": [], "model": None})
    assert "no posts" in "".join(d["text"] for e, d in ev if e == "token").lower()


def test_a_short_follow_up_reuses_the_previous_question(api, author):
    w = word()
    p = post(api, author, f"Notes on {w}", f"{w} was written by this author.", [])
    eventually(lambda: any(s["id"] == p["id"] for s in events(ask(api, f"Explain {w}"))[0][1]), timeout=30)
    ev = events(ask(api, f"Explain {w}", "It is a note.", "Who wrote it?"))
    assert p["id"] in {s["id"] for s in ev[0][1]}


def test_chat_validates_the_conversation(api):
    assert api.post("/api/chat", json={}).status_code == 422
    assert api.post("/api/chat", json={"messages": []}).status_code == 422
    assert ask(api, "Question?", "An answer, but no new question.").status_code == 422
    assert api.post("/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    assert ask(api, "x" * 4001).status_code == 422
    assert ask(api, "ok?", k=11).status_code == 422
