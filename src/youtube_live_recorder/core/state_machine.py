from youtube_live_recorder.data.models import TERMINAL_BROADCASTS
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.utils.errors import AppError, ErrorCode

BROADCAST_TRANSITIONS = {
    B.WAITING: {B.LIVE_DETECTED, B.REPLAY_WAIT},
    B.LIVE_DETECTED: {B.RECORDING, B.MISSED_BUSY},
    B.RECORDING: {B.FINALIZING, B.RECONNECTING, B.INTERRUPTED},
    B.FINALIZING: {B.VERIFYING, B.INTERRUPTED},
    B.VERIFYING: {B.COMPLETED, B.REPLAY_WAIT, B.INTERRUPTED},
    B.MISSED_BUSY: {B.REPLAY_WAIT},
    B.REPLAY_WAIT: {B.REPLAY_DOWNLOADING, B.REPLAY_EXPIRED},
    B.REPLAY_DOWNLOADING: {B.FINALIZING, B.REPLAY_WAIT, B.INTERRUPTED},
    B.RECONNECTING: {B.RECORDING, B.FINALIZING, B.REPLAY_WAIT, B.INTERRUPTED},
    B.INTERRUPTED: {B.RECOVERING},
    B.RECOVERING: {B.RECORDING, B.REPLAY_WAIT, B.FINALIZING, B.VERIFYING},
    B.ERROR: {B.WAITING, B.REPLAY_WAIT, B.RECOVERING},
    B.ERROR_RETRYABLE: {B.WAITING, B.LIVE_DETECTED, B.REPLAY_WAIT, B.RECOVERING},
}

SESSION_TRANSITIONS = {
    S.CREATED: {S.RUNNING, S.FAILED, S.CANCELLED},
    S.RUNNING: {S.RECONNECTING, S.FINALIZING, S.FAILED},
    S.RECONNECTING: {S.RUNNING, S.FINALIZING, S.PARTIAL, S.FAILED},
    S.FINALIZING: {S.VERIFYING, S.PARTIAL, S.FAILED},
    S.VERIFYING: {S.COMPLETE, S.PARTIAL, S.FAILED},
}


def validate_broadcast_transition(current: B, target: B) -> None:
    allowed = BROADCAST_TRANSITIONS.get(current, set())
    if current not in TERMINAL_BROADCASTS:
        allowed = allowed | {B.ERROR, B.ERROR_RETRYABLE, B.CANCELLED}
    if target not in allowed:
        raise AppError(ErrorCode.INVALID_STATE, f"{current} → {target}")


def validate_session_transition(current: S, target: S) -> None:
    if target not in SESSION_TRANSITIONS.get(current, set()):
        raise AppError(ErrorCode.INVALID_STATE, f"{current} → {target}")
