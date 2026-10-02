# expect: tls-verification-disabled
import httpx


def fetch(url):
    return httpx.Client(verify=False).get(url)
