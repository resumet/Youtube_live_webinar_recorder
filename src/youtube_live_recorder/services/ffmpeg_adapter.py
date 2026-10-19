import os
from pathlib import Path

from youtube_live_recorder.services.ffprobe_adapter import FFprobeAdapter
from youtube_live_recorder.services.interfaces import MediaInspection
from youtube_live_recorder.services.process_runner import ProcessRunner
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.filenames import reservation_marker, reserve_output


class FFmpegAdapter:
    def __init__(
        self, executable: Path, verifier: FFprobeAdapter, runner: ProcessRunner | None = None
    ) -> None:
        self.executable, self.verifier = executable, verifier
        self.runner = runner or ProcessRunner()

    def finalize(self, sources: tuple[Path, ...], folder: Path, name: str) -> MediaInspection:
        inspections = [self.verifier.inspect(path, require_mp4=False) for path in sources]
        combined = [item for item in inspections if item.valid]
        args = [str(self.executable), "-hide_banner", "-loglevel", "warning", "-nostdin", "-n"]
        if combined:
            best = max(
                combined, key=lambda item: (item.duration_seconds, item.height, item.size_bytes)
            )
            args += ["-i", str(best.path), "-map", "0:v:0", "-map", "0:a:0"]
        else:
            video = [item for item in inspections if item.video_codec]
            audio = [item for item in inspections if item.audio_codec]
            if not video or not audio:
                raise AppError(ErrorCode.FINALIZE_FAILED, "영상 또는 음성 조각을 찾을 수 없습니다.")
            v = max(video, key=lambda item: item.size_bytes)
            a = max(audio, key=lambda item: item.size_bytes)
            args += ["-i", str(v.path), "-i", str(a.path), "-map", "0:v:0", "-map", "1:a:0"]
        output = reserve_output(folder, name)
        staging = output.with_name(output.stem + ".finalizing.mp4")
        try:
            result = self.runner.run(
                [
                    *args,
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(staging),
                ],
                timeout=None,
            )
            if result.return_code:
                raise AppError(ErrorCode.FINALIZE_FAILED)
            inspection = self.verifier.inspect(staging)
            if not inspection.valid:
                raise AppError(ErrorCode.VERIFY_FAILED, inspection.reason)
            # 같은 볼륨에서 검사 완료 후 publish. 원본 조각은 삭제하지 않는다.
            if os.name == "nt":
                os.rename(staging, output)  # Windows rename은 기존 대상을 덮어쓰지 않는다.
            else:
                os.link(staging, output)
                staging.unlink()
            return MediaInspection(
                output,
                True,
                inspection.duration_seconds,
                inspection.size_bytes,
                inspection.video_codec,
                inspection.audio_codec,
                inspection.height,
            )
        finally:
            reservation_marker(output).unlink(missing_ok=True)
