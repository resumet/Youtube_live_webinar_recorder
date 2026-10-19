from dataclasses import dataclass
from enum import StrEnum


class BroadcastStatus(StrEnum):
    WAITING = "WAITING"
    LIVE_DETECTED = "LIVE_DETECTED"
    RECORDING = "RECORDING"
    FINALIZING = "FINALIZING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    MISSED_BUSY = "MISSED_BUSY"
    REPLAY_WAIT = "REPLAY_WAIT"
    REPLAY_DOWNLOADING = "REPLAY_DOWNLOADING"
    RECONNECTING = "RECONNECTING"
    INTERRUPTED = "INTERRUPTED"
    RECOVERING = "RECOVERING"
    ERROR = "ERROR"
    ERROR_RETRYABLE = "ERROR_RETRYABLE"
    CANCELLED = "CANCELLED"
    REPLAY_EXPIRED = "REPLAY_EXPIRED"


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    FINALIZING = "FINALIZING"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Quality(StrEnum):
    P720 = "720p"
    P1080 = "1080p"
    BEST = "best"


class RecordingMode(StrEnum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


TERMINAL_BROADCASTS = frozenset(
    {
        BroadcastStatus.COMPLETED,
        BroadcastStatus.CANCELLED,
        BroadcastStatus.REPLAY_EXPIRED,
    }
)
ACTIVE_SESSIONS = frozenset(
    {
        SessionStatus.CREATED,
        SessionStatus.RUNNING,
        SessionStatus.RECONNECTING,
        SessionStatus.FINALIZING,
        SessionStatus.VERIFYING,
    }
)

STATUS_LABELS = {
    BroadcastStatus.WAITING: "방송 대기",
    BroadcastStatus.LIVE_DETECTED: "라이브 감지",
    BroadcastStatus.RECORDING: "녹화 중",
    BroadcastStatus.FINALIZING: "파일 저장 중",
    BroadcastStatus.VERIFYING: "파일 검사 중",
    BroadcastStatus.COMPLETED: "완료",
    BroadcastStatus.MISSED_BUSY: "다른 방송 녹화로 건너뜀",
    BroadcastStatus.REPLAY_WAIT: "다시보기 대기",
    BroadcastStatus.REPLAY_DOWNLOADING: "다시보기 저장 중",
    BroadcastStatus.RECONNECTING: "재연결 중",
    BroadcastStatus.INTERRUPTED: "중단됨",
    BroadcastStatus.RECOVERING: "복구 중",
    BroadcastStatus.ERROR: "오류 확인 필요",
    BroadcastStatus.ERROR_RETRYABLE: "일시 오류 · 재시도 대기",
    BroadcastStatus.CANCELLED: "취소됨",
    BroadcastStatus.REPLAY_EXPIRED: "다시보기 확인 기한 만료",
}


@dataclass(frozen=True)
class Broadcast:
    id: str
    video_id: str
    original_url: str
    title: str
    channel_name: str
    thumbnail_url: str
    scheduled_start_at: str | None
    actual_start_at: str | None
    registered_at: str
    status: BroadcastStatus
    preferred_quality: Quality
    custom_filename: str
    last_polled_at: str | None
    next_check_at: str | None
    last_error_code: str | None
    poll_failures: int
    permission_confirmed: bool
    updated_at: str
    first_detected_at: str | None = None
    live_state: str = "unknown"


@dataclass(frozen=True)
class RecordingSession:
    id: str
    broadcast_id: str
    started_at: str
    ended_at: str | None
    status: SessionStatus
    mode: RecordingMode
    selected_quality: Quality
    actual_quality: str | None
    output_path: str | None
    duration_seconds: float | None
    size_bytes: int
    ffprobe_ok: bool
    failure_reason: str | None
    created_at: str
    updated_at: str
    work_directory: str | None = None
    coverage_note: str = ""
    from_start_attempted: bool = False
