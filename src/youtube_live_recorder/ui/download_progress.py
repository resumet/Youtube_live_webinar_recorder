from dataclasses import dataclass

from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.services.download_progress import DownloadProgress
from youtube_live_recorder.ui.formatting import duration, size_label


@dataclass(frozen=True)
class ProgressDisplay:
    percent: str = "—"
    amount: str = "계산 중"
    remaining: str = "대기 중"
    speed: str = "—"
    value: float | None = None


def progress_display(item, session, progress: DownloadProgress | None) -> ProgressDisplay:
    if session and session.status == S.COMPLETE:
        return ProgressDisplay("100%", size_label(session.size_bytes), "완료", value=100)
    if not session and item.status in {B.CANCELLED, B.ERROR, B.REPLAY_EXPIRED}:
        return ProgressDisplay(
            amount="—", remaining="취소됨" if item.status == B.CANCELLED else "중지됨"
        )
    if not session or item.status == B.REPLAY_WAIT:
        return ProgressDisplay()
    processing = session.status in {S.FINALIZING, S.VERIFYING}
    transferring = item.status == B.REPLAY_DOWNLOADING and session.status == S.RUNNING
    remaining = (
        "파일 검사 중"
        if session.status == S.VERIFYING
        else "파일 정리 중"
        if processing
        else "재연결 대기"
        if session.status == S.RECONNECTING
        else "준비 중"
        if session.status == S.CREATED
        else "중지됨"
    )
    if progress is None:
        return ProgressDisplay(
            amount=size_label(session.size_bytes) if session.size_bytes else "계산 중",
            remaining="계산 중" if transferring else remaining,
        )
    percent = f"{progress.percent:.1f}%" if progress.percent is not None else "계산 중"
    total = (
        ("약 " if progress.estimated else "") + size_label(progress.total_bytes)
        if progress.total_bytes is not None
        else "계산 중"
    )
    amount = f"{size_label(progress.downloaded_bytes)} / {total}"
    speed = "—"
    if transferring:
        if progress.transfer_finished:
            remaining = "파일 정리 중"
        elif progress.is_stale():
            remaining = "재계산 중"
        else:
            remaining = (
                f"약 {duration(max(1, progress.eta_seconds))}"
                if progress.eta_seconds is not None
                else "계산 중"
            )
            if progress.speed_bytes_per_second:
                speed = size_label(int(progress.speed_bytes_per_second)) + "/초"
    return ProgressDisplay(percent, amount, remaining, speed, progress.percent)
