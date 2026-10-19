import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from youtube_live_recorder.utils.errors import AppError, ErrorCode

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


@dataclass(frozen=True)
class VideoURL:
    video_id: str
    canonical_url: str


def parse_video_url(raw: str) -> VideoURL:
    """정확한 호스트와 경로만 허용한다. 채널·검색·재생목록은 허용하지 않는다."""
    text = raw.strip()
    try:
        if any(ord(char) < 32 for char in text) or "\\" in text:
            raise ValueError
        url = urlsplit(text)
        if url.scheme not in {"http", "https"} or url.username or url.password or url.port:
            raise ValueError
        host = (url.hostname or "").lower()
        parts = url.path.strip("/").split("/")
        if host == "youtu.be" and len(parts) == 1:
            video_id = parts[0]
        elif host in YOUTUBE_HOSTS and url.path == "/watch":
            values = parse_qs(url.query, keep_blank_values=True).get("v", [])
            if len(values) != 1:
                raise ValueError
            video_id = values[0]
        elif host in YOUTUBE_HOSTS and len(parts) == 2 and parts[0] == "live":
            video_id = parts[1]
        else:
            raise ValueError
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError
    except ValueError:
        raise AppError(ErrorCode.INVALID_URL) from None
    return VideoURL(video_id, f"https://www.youtube.com/watch?v={video_id}")
