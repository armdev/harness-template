-- search keeps its own copy of the tags (from content.post.created) to filter by tag.
-- Events published before tags existed carry no tags field; the indexer stores '{}' for them.
ALTER TABLE search.documents ADD COLUMN tags text[] NOT NULL DEFAULT '{}';
CREATE INDEX documents_tags_idx ON search.documents USING gin (tags);
