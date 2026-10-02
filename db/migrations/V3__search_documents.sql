CREATE SCHEMA search;
GRANT USAGE ON SCHEMA search TO search_svc;

-- search keeps its own copy, built from content.post.created events; it never reads content.*
CREATE TABLE search.documents (
    post_id  bigint PRIMARY KEY,
    title    text NOT NULL,
    body     text NOT NULL,
    author   text NOT NULL,
    tsv      tsvector GENERATED ALWAYS AS (
                 setweight(to_tsvector('english', title), 'A') || setweight(to_tsvector('english', body), 'B')
             ) STORED
);
CREATE INDEX documents_tsv_idx ON search.documents USING gin (tsv);
CREATE INDEX documents_author_idx ON search.documents (author);

GRANT SELECT, INSERT, UPDATE ON search.documents TO search_svc;
