# expect: sql-built-from-strings
def get(conn, post_id):
    return conn.execute(f"SELECT * FROM content.posts WHERE id = {post_id}")
