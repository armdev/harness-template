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

RELATED = """
MATCH (p:Post {id: $id})<-[:WROTE]-(a:Author)
CALL (p, a) {
  MATCH (p)-[:TAGGED]->(t:Tag)<-[:TAGGED]-(o:Post)
  RETURN o, t.name AS tag
  UNION ALL
  MATCH (a)-[:WROTE]->(o:Post) WHERE o <> p
  RETURN o, null AS tag
}
WITH a, o, collect(DISTINCT tag) AS shared
MATCH (oa:Author)-[:WROTE]->(o)
WITH o, oa, shared, oa = a AS same_author
WITH o, oa, shared, same_author, size(shared) + CASE WHEN same_author THEN 1 ELSE 0 END AS score
RETURN o.id AS id, o.title AS title, oa.name AS author, shared AS shared_tags, same_author, score
ORDER BY score DESC, id DESC
LIMIT $limit
"""

TAG_POSTS = "MATCH (t:Tag {name: $tag}) OPTIONAL MATCH (t)<-[:TAGGED]-(p:Post) RETURN count(p) AS posts"

CO_TAGS = """
MATCH (:Tag {name: $tag})<-[:TAGGED]-(p:Post)-[:TAGGED]->(o:Tag)
RETURN o.name AS tag, count(p) AS together
ORDER BY together DESC, tag
LIMIT $limit
"""

TAGGED_POSTS = """
MATCH (:Tag {name: $tag})<-[:TAGGED]-(p:Post)<-[:WROTE]-(a:Author)
RETURN p.id AS id, p.title AS title, a.name AS author
ORDER BY id DESC
LIMIT $limit
"""

COUNTS = """
CALL { MATCH (p:Post) RETURN count(p) AS posts }
CALL { MATCH (a:Author) RETURN count(a) AS authors }
CALL { MATCH (t:Tag) RETURN count(t) AS tags }
RETURN posts, authors, tags
"""

TOP_TAGS = """
MATCH (t:Tag)<-[:TAGGED]-(p:Post)
RETURN t.name AS tag, count(p) AS posts
ORDER BY posts DESC, tag
LIMIT $limit
"""

TOP_AUTHORS = """
MATCH (a:Author)-[:WROTE]->(p:Post)
RETURN a.name AS author, count(p) AS posts
ORDER BY posts DESC, author
LIMIT $limit
"""

TAG_LINKS = """
MATCH (a:Tag)<-[:TAGGED]-(p:Post)-[:TAGGED]->(b:Tag)
WHERE a.name IN $tags AND b.name IN $tags AND a.name < b.name
RETURN a.name AS source, b.name AS target, count(p) AS together
ORDER BY together DESC, source, target
"""


def index_post(driver: Driver, event: dict) -> None:
    """EventConsumer handler. KeyError (missing field) = malformed event: skipped. Driver errors = retried."""
    params = {"id": event["id"], "title": event["title"], "author": event["author"],
              "created_at": str(event.get("created_at", "")), "tags": list(event.get("tags") or [])}
    driver.execute_query(INDEX_POST, params)


def related(driver: Driver, post_id: int, limit: int) -> list[dict] | None:
    """Posts linked to `post_id` through shared tags or its author, best first; None if the post is not in the graph.

    score = shared tags + 1 if by the same author; ties: newest (highest id) first. Ranked and limited in Neo4j, so a
    tag carried by thousands of posts costs one aggregation there, not thousands of rows here.
    """
    if not driver.execute_query(POST_EXISTS, {"id": post_id}).records:
        return None
    rows = driver.execute_query(RELATED, {"id": post_id, "limit": limit}).records
    return [{**r.data(), "shared_tags": sorted(r["shared_tags"])} for r in rows]


def tag_neighbourhood(driver: Driver, tag: str, limit: int) -> dict | None:
    """How many posts carry `tag` and which tags appear with it; None if the tag is unknown."""
    rows = driver.execute_query(TAG_POSTS, {"tag": tag}).records
    if not rows or rows[0]["posts"] == 0:
        return None
    co = driver.execute_query(CO_TAGS, {"tag": tag, "limit": limit}).records
    return {"tag": tag, "posts": rows[0]["posts"], "related": [r.data() for r in co]}


def tagged_posts(driver: Driver, tag: str, limit: int) -> list[dict] | None:
    """The newest posts carrying `tag`; None if the tag is unknown."""
    rows = [r.data() for r in driver.execute_query(TAGGED_POSTS, {"tag": tag, "limit": limit}).records]
    return rows or None


def overview(driver: Driver, limit: int) -> dict:
    """Size of the graph, its `limit` biggest tags and authors, and how often those tags appear together."""
    counts = driver.execute_query(COUNTS).records[0].data()
    top_tags = [r.data() for r in driver.execute_query(TOP_TAGS, {"limit": limit}).records]
    top_authors = [r.data() for r in driver.execute_query(TOP_AUTHORS, {"limit": limit}).records]
    names = [t["tag"] for t in top_tags]
    links = [r.data() for r in driver.execute_query(TAG_LINKS, {"tags": names}).records] if names else []
    return {**counts, "top_tags": top_tags, "top_authors": top_authors, "tag_links": links}
