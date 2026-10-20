import json
import logging
from datetime import UTC, datetime
from threading import Event

from youtube_live_recorder.data.models import Quality
from youtube_live_recorder.services.download_progress import (
    PLAN_TEMPLATE,
    PROGRESS_TEMPLATE,
    ProgressTracker,
)
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureRequest,
    CaptureResult,
    LiveState,
)
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.logging import redact
from youtube_live_recorder.utils.time import to_iso
from youtube_live_recorder.utils.urls import parse_video_url

LOGGER = logging.getLogger(__name__)


def classify_error(text: str) -> ErrorCode:
    lowered = text.lower()
    if "requested format is not available" in lowered:
        return ErrorCode.FORMAT_UNAVAILABLE
    if "live-from-start" in lowered and any(
        word in lowered for word in ("not supported", "not available", "no formats")
    ):
        return ErrorCode.DVR_UNAVAILABLE
    if any(word in lowered for word in ("429", "too many requests", "rate limit")):
        return ErrorCode.RATE_LIMITED
    if any(
        word in lowered
        for word in (
            "private video",
            "sign in",
            "members-only",
            "members only",
            "not available",
            "video unavailable",
            "removed",
            "copyright",
            "drm",
            "403",
            "login required",
            "not a bot",
            "age-restricted",
        )
    ):
        return ErrorCode.STREAM_UNAVAILABLE
    if "will begin" in lowered or "not currently live" in lowered:
        return ErrorCode.STREAM_NOT_LIVE
    return ErrorCode.NETWORK_DISCONNECTED


def quality_selector(quality: Quality) -> str:
    height = {Quality.P720: 720, Quality.P1080: 1080}.get(quality)
    cap = f"[height<={height}]" if height else ""
    # 상한보다 큰 영상으로 몰래 폴백하지 않는다. 동률이면 아래 정렬에서 H.264를 선호한다.
    return f"bv{cap}+ba/b{cap}"


def _timestamp(value) -> str | None:
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        try:
            return to_iso(datetime.fromtimestamp(value, UTC))
        except (ValueError, OverflowError, OSError):
            return None
    return None


def parse_metadata(info: dict, expected_id: str) -> BroadcastMetadata:
    if info.get("id") != expected_id or info.get("_type", "video") != "video":
        raise AppError(ErrorCode.STREAM_UNAVAILABLE, "요청한 방송과 조회 결과가 다릅니다.")
    if info.get("has_drm") or info.get("availability") not in {None, "public", "unlisted"}:
        raise AppError(ErrorCode.STREAM_UNAVAILABLE)
    raw_state = info.get("live_status")
    state = LiveState(raw_state) if raw_state in LiveState else LiveState.UNKNOWN
    release = _timestamp(info.get("release_timestamp"))
    return BroadcastMetadata(
        video_id=expected_id,
        title=str(info.get("title") or "방송 제목 확인 중"),
        channel_name=str(info.get("channel") or info.get("uploader") or ""),
        thumbnail_url=str(info.get("thumbnail") or ""),
        state=state,
        scheduled_start_at=release if state == LiveState.UPCOMING else None,
        actual_start_at=release
        if state in {LiveState.LIVE, LiveState.WAS_LIVE, LiveState.POST_LIVE}
        else None,
    )


class YtdlpAdapter:
    def __init__(self, tools: Toolchain, runner: ProcessRunner | None = None) -> None:
        self.tools = tools
        self.runner = runner or ProcessRunner()

    def base_args(self) -> list[str]:
        return [
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-remote-components",
            "--no-cache-dir",
            "--no-playlist",
            "--no-wait-for-video",
            "--no-colors",
            "--socket-timeout",
            "15",
            "--retries",
            "3",
            "--fragment-retries",
            "3",
            "--extractor-retries",
            "2",
            "--no-js-runtimes",
            "--js-runtimes",
            f"{self.tools.javascript_kind}:{self.tools.javascript}",
            "--ffmpeg-location",
            str(self.tools.ffmpeg.parent),
        ]

    def fetch(self, url: str) -> BroadcastMetadata:
        parsed = parse_video_url(url)
        result = self.runner.run(
            [
                *self.base_args(),
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                "--ignore-no-formats-error",
                "--",
                parsed.canonical_url,
            ],
            kind="ytdlp",
            timeout=45,
        )
        if result.return_code or result.timed_out:
            code = classify_error(result.stderr)
            LOGGER.warning("방송 조회 실패: %s", code)
            raise AppError(code)
        try:
            info = json.loads(result.stdout)
            if not isinstance(info, dict):
                raise ValueError
        except ValueError:
            raise AppError(
                ErrorCode.NETWORK_DISCONNECTED, "조회 응답 형식을 확인할 수 없습니다."
            ) from None
        return parse_metadata(info, parsed.video_id)

    def capture_args(self, request: CaptureRequest) -> list[str]:
        url = parse_video_url(request.url).canonical_url
        progress_args = (
            [
                "--progress",
                "--progress-delta",
                "1",
                "--print",
                PLAN_TEMPLATE,
                "--progress-template",
                PROGRESS_TEMPLATE,
            ]
            if request.on_progress
            else []
        )
        return [
            *self.base_args(),
            *progress_args,
            "--newline",
            "--no-warnings",
            "--no-overwrites",
            "--continue",
            "--keep-video",
            "--no-mtime",
            "--abort-on-unavailable-fragments",
            "--format",
            quality_selector(request.quality),
            "--format-sort",
            "res,vcodec:h264,acodec:aac",
            "--merge-output-format",
            "mkv",
            "--no-simulate",
            "--print",
            "before_dl:YLR_FORMAT %(height)j",
            "--hls-use-mpegts",
            "--downloader-args",
            "ffmpeg_i:-rw_timeout 15000000",
            "--fixup",
            "never",
            "--live-from-start" if request.from_start else "--no-live-from-start",
            "--output",
            str(request.work_directory.resolve() / "capture.%(ext)s"),
            "--",
            url,
        ]

    def capture(self, request: CaptureRequest, stop: Event) -> CaptureResult:
        request.work_directory.mkdir(parents=True, exist_ok=True)
        video_id = parse_video_url(request.url).video_id
        tracker = ProgressTracker(request.on_progress) if request.on_progress else None

        def line(name: str, value: str) -> None:
            if tracker and tracker.feed(value):
                return
            if name == "stdout" and value.startswith("YLR_FORMAT ") and request.on_quality:
                try:
                    height = json.loads(value.removeprefix("YLR_FORMAT ").strip())
                    if isinstance(height, int) and height > 0:
                        request.on_quality(height)
                except (ValueError, TypeError):
                    pass
            # 진행 출력도 무한히 파일에 누적하지 않는다. stderr 오류만 분리하여 보관한다.
            if name == "stderr" and value.strip():
                LOGGER.info(
                    "녹화 도구: %s", redact(value.strip()).replace(video_id, "[영상 ID 숨김]")
                )

        result = self.runner.run(
            self.capture_args(request),
            kind="ytdlp",
            timeout=None,
            stop=stop,
            on_line=line,
            output_limit=128 * 1024,
        )
        files = tuple(
            sorted(
                path
                for path in request.work_directory.iterdir()
                if path.is_file()
                and path.suffix.lower() in {".mp4", ".m4a", ".webm", ".mkv", ".ts", ".part"}
            )
        )
        return CaptureResult(
            result.return_code,
            files,
            result.stopped,
            request.from_start,
            classify_error(result.stderr) if result.return_code else None,
            result.forced,
        )
