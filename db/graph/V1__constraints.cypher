// Graph schema for the `graph` service (Neo4j). Applied by the graph-init one-shot before the service starts;
// services own no schema statements (semgrep ddl-outside-migrations). Append new files; never edit an applied one.
CREATE CONSTRAINT post_id IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE;
CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE;
