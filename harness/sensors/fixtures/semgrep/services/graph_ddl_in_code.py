# expect: ddl-outside-migrations
# Seeded defect: Neo4j schema created by a service instead of db/graph/*.cypher (applied by graph-init).
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "x"))


def startup():
    driver.execute_query("CREATE CONSTRAINT post_id IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE")
