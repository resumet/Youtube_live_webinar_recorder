from dataclasses import dataclass
from pathlib import Path

from youtube_live_recorder.data.models import (
    ACTIVE_SESSIONS,
    RecordingMode,
    RecordingSession,
    SessionStatus,
)
from youtube_live_recorder.utils.time import from_iso, utc_now


@dataclass(frozen=True)
class Notification:
    title: str
    text: str
    folder: Path | None = None


class NotificationTracker:
    def __init__(self):
        self.started_at = utc_now()
        self.seen: dict[str, SessionStatus] = {}

    def update(self, sessions: tuple[RecordingSession, ...]) -> list[Notification]:
        notices = []
        for item in reversed(sessions):
            previous = self.seen.get(item.id)
            if previous == item.status:
                continue
            self.seen[item.id] = item.status
            if previous is None and from_iso(item.started_at) < self.started_at:
                continue
            if previous is None and item.status in ACTIVE_SESSIONS:
                notices.append(
                    Notification(
                        "다시보기 저장을 시작했습니다", "공개된 다시보기를 저장하고 있습니다."
                    )
                    if item.mode == RecordingMode.REPLAY
                    else Notification("녹화를 시작했습니다", "라이브 방송을 저장하고 있습니다.")
                )
            elif (
                item.status in {SessionStatus.COMPLETE, SessionStatus.PARTIAL} and item.output_path
            ):
                notices.append(
                    Notification(
                        "녹화 저장 완료"
                        if item.status == SessionStatus.COMPLETE
                        else "부분 녹화 저장 완료",
                        "알림을 누르면 저장 폴더를 엽니다.",
                        Path(item.output_path).parent,
                    )
                )
            elif item.status == SessionStatus.FAILED:
                notices.append(
                    Notification(
                        "녹화 확인이 필요합니다",
                        "임시 파일을 보존했습니다. 녹화 기록을 확인해 주세요.",
                    )
                )
        return notices
