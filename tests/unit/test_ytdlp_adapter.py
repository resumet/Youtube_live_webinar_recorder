from pathlib import Path

import pytest

from youtube_live_recorder.data.models import Quality
from youtube_live_recorder.services.interfaces import CaptureRequest, LiveState
from youtube_live_recorder.services.process_runner import ProcessResult
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import (
    YtdlpAdapter,
    classify_error,
    parse_metadata,
    quality_selector,
)
from youtube_live_recorder.utils.errors import AppError, ErrorCode


class FixtureRunner:
    def __init__(self, result):
        self.result = result
        self.args = []

    def run(self, args, **kwargs):
        self.args = args
        return self.result


def test_scheduled_metadata_works_without_download_formats():
    info = {
        "id": "Abc_123-xYz",
        "title": "예정된 방송",
        "live_status": "is_upcoming",
        "release_timestamp": 1792371600,
        "availability": "public",
    }
    # yt-dlp 실제 live_status는 is_upcoming이다.
    metadata = parse_metadata(info, "Abc_123-xYz")
    assert metadata.state == LiveState.UPCOMING
    assert metadata.scheduled_start_at and metadata.actual_start_at is None


@pytest.mark.parametrize(
    "extra",
    [
        {"has_drm": True},
        {"availability": "needs_auth"},
        {"availability": "private"},
        {"id": "Other_12-xY"},
    ],
)
def test_restricted_or_wrong_video_rejected(extra):
    with pytest.raises(AppError):
        parse_metadata({"id": "Abc_123-xYz", **extra}, "Abc_123-xYz")


def test_unknown_state_is_not_an_ended_broadcast():
    assert parse_metadata({"id": "Abc_123-xYz"}, "Abc_123-xYz").state == LiveState.UNKNOWN


def test_metadata_errors_are_classified_and_never_return_success():
    runner = FixtureRunner(ProcessResult(1, "", "HTTP Error 429: Too Many Requests"))
    tools = Toolchain(Path("ffmpeg"), Path("ffprobe"), Path("deno"))
    with pytest.raises(AppError) as error:
        YtdlpAdapter(tools, runner).fetch("https://youtu.be/Abc_123-xYz")
    assert error.value.code == ErrorCode.RATE_LIMITED


def test_capture_argv_isolated_from_machine_settings(tmp_path):
    tools = Toolchain(Path("ffmpeg"), Path("ffprobe"), Path("deno"))
    args = YtdlpAdapter(tools).capture_args(
        CaptureRequest("https://youtu.be/Abc_123-xYz?si=tracking", Quality.P720, tmp_path, True)
    )
    assert {
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--live-from-start",
        "--abort-on-unavailable-fragments",
    } <= set(args)
    assert args[-1] == "https://www.youtube.com/watch?v=Abc_123-xYz"
    assert "--cookies" not in args and "--allow-unplayable-formats" not in args
    assert args[args.index("--format") + 1] == "bv[height<=720]+ba/b[height<=720]"


def test_quality_caps_have_no_unbounded_fallback():
    assert quality_selector(Quality.P1080) == "bv[height<=1080]+ba/b[height<=1080]"
    assert quality_selector(Quality.BEST) == "bv+ba/b"


def test_actual_ytdlp_selector_falls_back_to_lower_available_resolution():
    import yt_dlp

    formats = [
        {
            "format_id": "v480",
            "ext": "mp4",
            "height": 480,
            "vcodec": "avc1",
            "acodec": "none",
            "url": "https://example.test/v480",
        },
        {
            "format_id": "v1080",
            "ext": "mp4",
            "height": 1080,
            "vcodec": "avc1",
            "acodec": "none",
            "url": "https://example.test/v1080",
        },
        {
            "format_id": "audio",
            "ext": "m4a",
            "vcodec": "none",
            "acodec": "mp4a",
            "url": "https://example.test/audio",
        },
    ]
    with yt_dlp.YoutubeDL({"quiet": True}) as downloader:
        selector = downloader.build_format_selector(quality_selector(Quality.P720))
        selected = list(
            selector({"formats": formats, "has_merged_format": False, "incomplete_formats": False})
        )
    assert len(selected) == 1
    assert selected[0]["requested_formats"][0]["format_id"] == "v480"
    assert selected[0]["requested_formats"][1]["format_id"] == "audio"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Private video. Sign in", ErrorCode.STREAM_UNAVAILABLE),
        ("This live event will begin in 2 hours", ErrorCode.STREAM_NOT_LIVE),
        ("Connection timed out", ErrorCode.NETWORK_DISCONNECTED),
    ],
)
def test_error_mapping(text, code):
    assert classify_error(text) == code
