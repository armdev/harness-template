"""graph: a knowledge graph of posts, authors and tags in Neo4j, built from content.post.created.

Complements search (full text, Postgres): search finds posts by their words, graph by their relations.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from functools import partial

from fastapi import Depends, HTTPException, Path, Query
from neo4j import GraphDatabase
from pydantic import BaseModel

from common.events import EventConsumer
from common.service_auth import require_caller
from common.telemetry import create_app
from graph import index_post, overview, related, tag_neighbourhood, tagged_posts

log = logging.getLogger(__name__)

TAG_PATTERN = r"^[a-z0-9-]{1,32}$"
driver = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://neo4j:7687"),
                              auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))
consumer: EventConsumer | None = None


@asynccontextmanager
async def lifespan(_app):
    global consumer
    driver.verify_connectivity()
    consumer = EventConsumer(os.environ.get("POST_CREATED_TOPIC", "content.post.created"), partial(index_post, driver),
                             bootstrap=os.environ["KAFKA_BOOTSTRAP"], group_id="graph", name="grapher")
    consumer.start()
    yield
    consumer.stop()
    driver.close()


app = create_app("graph", lifespan=lifespan)
auth = require_caller()


class RelatedPost(BaseModel):
    id: int
    title: str
    author: str
    score: int
    shared_tags: list[str]
    same_author: bool


class Related(BaseModel):
    post_id: int
    related: list[RelatedPost]


class CoTag(BaseModel):
    tag: str
    together: int


class TagNeighbourhood(BaseModel):
    tag: str
    posts: int
    related: list[CoTag]


class TaggedPost(BaseModel):
    id: int
    title: str
    author: str


class TaggedPosts(BaseModel):
    tag: str
    posts: list[TaggedPost]


class TagCount(BaseModel):
    tag: str
    posts: int


class AuthorCount(BaseModel):
    author: str
    posts: int


class TagLink(BaseModel):
    source: str
    target: str
    together: int


class Overview(BaseModel):
    posts: int
    authors: int
    tags: int
    top_tags: list[TagCount]
    top_authors: list[AuthorCount]
    tag_links: list[TagLink]


@app.get("/related/{post_id}", response_model=Related)
def related_posts(post_id: int, limit: int = Query(10, ge=1, le=50), _caller: str = Depends(auth)) -> Related:
    found = related(driver, post_id, limit)
    if found is None:
        raise HTTPException(status_code=404, detail="post not in the graph (unknown, or not indexed yet)")
    return Related(post_id=post_id, related=[RelatedPost(**r) for r in found])


@app.get("/tags/{tag}", response_model=TagNeighbourhood)
def tag(tag: str = Path(pattern=TAG_PATTERN), limit: int = Query(10, ge=1, le=50),
        _caller: str = Depends(auth)) -> TagNeighbourhood:
    found = tag_neighbourhood(driver, tag, limit)
    if found is None:
        raise HTTPException(status_code=404, detail="unknown tag")
    return TagNeighbourhood(**found)


@app.get("/tags/{tag}/posts", response_model=TaggedPosts)
def posts_of_tag(tag: str = Path(pattern=TAG_PATTERN), limit: int = Query(20, ge=1, le=50),
                 _caller: str = Depends(auth)) -> TaggedPosts:
    found = tagged_posts(driver, tag, limit)
    if found is None:
        raise HTTPException(status_code=404, detail="unknown tag")
    return TaggedPosts(tag=tag, posts=[TaggedPost(**r) for r in found])


@app.get("/overview", response_model=Overview)
def graph_overview(limit: int = Query(10, ge=1, le=50), _caller: str = Depends(auth)) -> Overview:
    return Overview(**overview(driver, limit))
