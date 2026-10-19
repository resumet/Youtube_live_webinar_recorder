import pytest

from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.urls import parse_video_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=Abc_123-xYz",
        "https://youtube.com/live/Abc_123-xYz?si=ignored",
        "https://youtu.be/Abc_123-xYz?t=15",
        " https://m.youtube.com/watch?v=Abc_123-xYz&feature=share ",
        "http://YOUTUBE.COM/watch?v=Abc_123-xYz#fragment",
    ],
)
def test_normalizes_supported_urls(url):
    result = parse_video_url(url)
    assert result.video_id == "Abc_123-xYz"
    assert result.canonical_url == "https://www.youtube.com/watch?v=Abc_123-xYz"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "Abc_123-xYz",
        "youtube.com/watch?v=Abc_123-xYz",
        "https://youtube.com.evil.test/watch?v=Abc_123-xYz",
        "https://youtube.com@evil.test/watch?v=Abc_123-xYz",
        "https://evil.test@youtube.com/watch?v=Abc_123-xYz",
        "https://youtube.com:8080/watch?v=Abc_123-xYz",
        "https://youtube.com:bad/watch?v=Abc_123-xYz",
        "file:///watch?v=Abc_123-xYz",
        "https://youtube.com/playlist?list=Abc_123-xYz",
        "https://youtube.com/@channel/live",
        "https://youtu.be/Abc_123-xYz/extra",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/watch?v=Abc_123-xYz&v=Other_12-xY",
        "https://youtube.com/watch?v=",
        "https://youtube.com/watch?v=Abc_123-xYz%20",
        "https://you\ntube.com/watch?v=Abc_123-xYz",
        "https://youtube.com\\@evil.test/watch?v=Abc_123-xYz",
    ],
)
def test_rejects_ambiguous_or_unsafe_urls(url):
    with pytest.raises(AppError) as error:
        parse_video_url(url)
    assert error.value.code == ErrorCode.INVALID_URL
