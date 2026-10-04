"""The knowledge graph: (:Author)-[:WROTE]->(:Post)-[:TAGGED]->(:Tag), built from content.post.created.

Writes are MERGEs on unique keys (constraints in db/graph), so a redelivered event changes nothing.
"""
from __future__ import annotations

from neo4j import Driver

INDEX_POST = """
MERGE (a:Author {name: $author})
MERGE (p:Post {id: $id})
SET p.title = $title, p.created_at = $created_at
MERGE (a)-[:WROTE]->(p)
WITH p
UNWIND $tags AS name
MERGE (t:Tag {name: name})
MERGE (p)-[:TAGGED]->(t)
"""

POST_EXISTS = "MATCH (p:Post {id: $id}) RETURN p.id AS id"

SHARED_TAGS = """
MATCH (p:Post {id: $id})-[:TAGGED]->(t:Tag)<-[:TAGGED]-(o:Post)<-[:WROTE]-(oa:Author)
RETURN o.id AS id, o.title AS title, oa.name AS author, collect(t.name) AS shared_tags
"""

SAME_AUTHOR = """
MATCH (p:Post {id: $id})<-[:WROTE]-(a:Author)-[:WROTE]->(o:Post)
WHERE o <> p
RETURN o.id AS id, o.title AS title, a.name AS author
"""

TAG_POSTS = "MATCH (t:Tag {name: $tag}) OPTIONAL MATCH (t)<-[:TAGGED]-(p:Post) RETURN count(p) AS posts"

CO_TAGS = """
MATCH (:Tag {name: $tag})<-[:TAGGED]-(p:Post)-[:TAGGED]->(o:Tag)
RETURN o.name AS tag, count(p) AS together
ORDER BY together DESC, tag
LIMIT $limit
"""


def index_post(driver: Driver, event: dict) -> None:
    """EventConsumer handler. KeyError (missing field) = malformed event: skipped. Driver errors = retried."""
    params = {"id": event["id"], "title": event["title"], "author": event["author"],
              "created_at": str(event.get("created_at", "")), "tags": list(event.get("tags") or [])}
    driver.execute_query(INDEX_POST, params)


def rank(shared: list[dict], same_author: list[dict], limit: int) -> list[dict]:
    """One entry per related post: score = shared tags + 1 if by the same author; ties: newest (highest id) first."""
    found: dict[int, dict] = {}
    for r in shared:
        found[r["id"]] = {**r, "shared_tags": sorted(r["shared_tags"]), "same_author": False}
    for r in same_author:
        found.setdefault(r["id"], {**r, "shared_tags": []})["same_author"] = True
    for r in found.values():
        r["score"] = len(r["shared_tags"]) + (1 if r["same_author"] else 0)
    return sorted(found.values(), key=lambda r: (-r["score"], -r["id"]))[:limit]


def related(driver: Driver, post_id: int, limit: int) -> list[dict] | None:
    """Posts linked to `post_id` through shared tags or its author; None if the post is not in the graph."""
    if not driver.execute_query(POST_EXISTS, {"id": post_id}).records:
        return None
    shared = [r.data() for r in driver.execute_query(SHARED_TAGS, {"id": post_id}).records]
    same = [r.data() for r in driver.execute_query(SAME_AUTHOR, {"id": post_id}).records]
    return rank(shared, same, limit)


def tag_neighbourhood(driver: Driver, tag: str, limit: int) -> dict | None:
    """How many posts carry `tag` and which tags appear with it; None if the tag is unknown."""
    rows = driver.execute_query(TAG_POSTS, {"tag": tag}).records
    if not rows or rows[0]["posts"] == 0:
        return None
    co = driver.execute_query(CO_TAGS, {"tag": tag, "limit": limit}).records
    return {"tag": tag, "posts": rows[0]["posts"], "related": [r.data() for r in co]}
