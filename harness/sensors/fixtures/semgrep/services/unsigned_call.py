# expect: unsigned-service-call
import httpx


def get_post(post_id):
    return httpx.get(f"http://content:8000/posts/{post_id}").json()
