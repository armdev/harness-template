CREATE SCHEMA content;
GRANT USAGE ON SCHEMA content TO content_svc;

CREATE TABLE content.posts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       text        NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    body        text        NOT NULL,
    author      text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT ON content.posts TO content_svc;
