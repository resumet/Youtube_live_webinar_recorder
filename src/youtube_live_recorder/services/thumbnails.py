import urllib.request
from urllib.parse import urlsplit


def fetch_thumbnail(url: str) -> bytes:
    def allowed(address: str) -> bool:
        parsed = urlsplit(address)
        host = parsed.hostname or ""
        return parsed.scheme == "https" and (host == "i.ytimg.com" or host.endswith(".ytimg.com"))

    if not allowed(url):
        return b""
    request = urllib.request.Request(url, headers={"User-Agent": "YouTubeLiveRecorder"})
    with urllib.request.urlopen(request, timeout=8) as response:
        if not allowed(response.url) or not response.headers.get("Content-Type", "").startswith(
            "image/"
        ):
            return b""
        data = response.read(2 * 1024 * 1024 + 1)
        return data if len(data) <= 2 * 1024 * 1024 else b""
