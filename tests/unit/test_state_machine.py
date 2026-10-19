import pytest

from youtube_live_recorder.core.state_machine import (
    validate_broadcast_transition,
    validate_session_transition,
)
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.utils.errors import AppError


@pytest.mark.parametrize(
    "path",
    [
        [B.WAITING, B.LIVE_DETECTED, B.RECORDING, B.FINALIZING, B.VERIFYING, B.COMPLETED],
        [B.WAITING, B.LIVE_DETECTED, B.MISSED_BUSY, B.REPLAY_WAIT, B.REPLAY_DOWNLOADING],
        [B.RECORDING, B.RECONNECTING, B.RECORDING, B.INTERRUPTED, B.RECOVERING, B.REPLAY_WAIT],
        [B.WAITING, B.ERROR_RETRYABLE, B.WAITING, B.CANCELLED],
        [B.REPLAY_WAIT, B.REPLAY_EXPIRED],
    ],
)
def test_supported_broadcast_lifecycles(path):
    for current, target in zip(path, path[1:], strict=False):
        validate_broadcast_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (B.WAITING, B.COMPLETED),
        (B.RECORDING, B.COMPLETED),
        (B.COMPLETED, B.RECORDING),
        (B.CANCELLED, B.WAITING),
        (B.REPLAY_EXPIRED, B.ERROR),
        (B.WAITING, B.WAITING),
    ],
)
def test_rejects_false_completion_and_terminal_restart(current, target):
    with pytest.raises(AppError):
        validate_broadcast_transition(current, target)


def test_session_requires_finalize_and_verify():
    with pytest.raises(AppError):
        validate_session_transition(S.RUNNING, S.COMPLETE)
    validate_session_transition(S.RUNNING, S.FINALIZING)
    validate_session_transition(S.FINALIZING, S.VERIFYING)
    validate_session_transition(S.VERIFYING, S.COMPLETE)
