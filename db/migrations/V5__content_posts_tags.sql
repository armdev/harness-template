-- Optional tags on posts. Backward compatible: existing rows and writers that do not send tags get '{}'.
-- (A NOT NULL column with a constant default is added without rewriting the table.)
ALTER TABLE content.posts
    ADD COLUMN tags text[] NOT NULL DEFAULT '{}',
    ADD CONSTRAINT posts_tags_max CHECK (cardinality(tags) <= 5);
