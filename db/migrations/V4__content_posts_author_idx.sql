-- GET /posts?author= lists one author's posts newest first: serve it from an index, not a table scan.
CREATE INDEX posts_author_created_idx ON content.posts (author, created_at DESC, id DESC);
