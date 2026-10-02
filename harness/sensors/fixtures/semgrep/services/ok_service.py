# expect: clean
import logging
import os

from common.service_auth import SignedClient

log = logging.getLogger(__name__)
content = SignedClient(os.environ.get("CONTENT_URL", "http://content:8000"))


def get_post(conn, post_id):
    log.info("loading post %s", post_id)
    row = conn.execute("SELECT id, title FROM content.posts WHERE id = %s", (post_id,)).fetchone()
    return row or content.get(f"/posts/{post_id}").json()
