# expect: ddl-outside-migrations
def setup(conn):
    conn.execute("CREATE TABLE content.tags (id bigint primary key)")
