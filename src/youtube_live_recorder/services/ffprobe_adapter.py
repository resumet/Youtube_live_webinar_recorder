import json
import math
from pathlib import Path

from youtube_live_recorder.services.interfaces import MediaInspection
from youtube_live_recorder.services.process_runner import ProcessRunner


class FFprobeAdapter:
    def __init__(self, executable: Path, runner: ProcessRunner | None = None) -> None:
        self.executable = executable
        self.runner = runner or ProcessRunner()

    def inspect(self, path: Path, *, require_mp4: bool = True) -> MediaInspection:
        try:
            size = path.stat().st_size
        except OSError:
            return MediaInspection(path, False, 0, 0, reason="파일을 읽을 수 없습니다.")
        result = self.runner.run(
            [
                str(self.executable),
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path.resolve()),
            ],
            timeout=30,
        )
        try:
            info = json.loads(result.stdout)
            streams = info.get("streams", [])
            video = next(
                (
                    s
                    for s in streams
                    if s.get("codec_type") == "video"
                    and not s.get("disposition", {}).get("attached_pic")
                ),
                {},
            )
            audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
            duration = float(info.get("format", {}).get("duration", 0))
            formats = info.get("format", {}).get("format_name", "").split(",")
            valid = (
                result.return_code == 0
                and not result.timed_out
                and size > 0
                and math.isfinite(duration)
                and duration > 0
                and bool(video)
                and bool(audio)
                and (not require_mp4 or "mp4" in formats)
            )
            return MediaInspection(
                path,
                valid,
                duration if math.isfinite(duration) else 0,
                size,
                str(video.get("codec_name", "")),
                str(audio.get("codec_name", "")),
                int(video.get("height", 0)),
                "" if valid else "영상·음성·길이·컨테이너 기본 검사를 통과하지 못했습니다.",
            )
        except (ValueError, TypeError, AttributeError):
            return MediaInspection(path, False, 0, size, reason="검사 결과를 읽을 수 없습니다.")
