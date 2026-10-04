-- GET /posts?author= now pages by id (before=<id>, ORDER BY id DESC): an index on (author, id) serves every page.
CREATE INDEX posts_author_id_idx ON content.posts (author, id DESC);
