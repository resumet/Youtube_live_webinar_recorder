from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureResult,
    LiveState,
    MediaInspection,
)
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import to_iso, utc_now


class Metadata:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        state = next(self.states)
        if isinstance(state, Exception):
            raise state
        return BroadcastMetadata(
            url[-11:],
            "테스트 방송",
            "채널",
            "",
            state,
            actual_start_at=to_iso(datetime(2026, 10, 18, 15, 30, tzinfo=UTC)),
        )


class Capture:
    def __init__(self, *, hold=False, error=None, user_stop=False):
        self.hold, self.error, self.user_stop = hold, error, user_stop
        self.requests = []

    def capture(self, request, stop):
        self.requests.append(request)
        if self.hold:
            stop.wait(10)
        if self.user_stop:
            stop.set()
        return CaptureResult(
            1 if self.error else 0, (), stop.is_set(), request.from_start, self.error
        )


class Finalize:
    def __init__(self, *, fail=False):
        self.fail = fail

    def finalize(self, sources, folder, name):
        if self.fail:
            raise AppError(ErrorCode.VERIFY_FAILED)
        path = folder / name
        path.write_bytes(b"fixture-media")
        return MediaInspection(path, True, 3.5, 1000, "h264", "aac", 720)


def setup_manager(repository, tmp_path, metadata, capture=None, finalizer=None):
    return RecordingManager(
        repository,
        Settings(tmp_path, min_free_bytes=0, max_reconnect_attempts=0),
        metadata,
        capture or Capture(),
        finalizer or Finalize(),
    )


def add(repository, identifier="Abc_123-xYz"):
    return repository.add_broadcast("https://youtu.be/" + identifier, permission_confirmed=True)


def wait_manager(manager):
    if manager.future:
        manager.future.result(timeout=10)


def test_simultaneous_live_uses_registration_order_and_marks_busy(repository, tmp_path):
    first, second = add(repository), add(repository, "Xyz_987-aBc")
    metadata = Metadata([LiveState.LIVE, LiveState.LIVE])
    manager = setup_manager(repository, tmp_path, metadata, Capture(hold=True))
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        assert repository.active_session().broadcast_id == first.id
        assert repository.get_broadcast(second.id).status == B.MISSED_BUSY
        assert len(repository.list_sessions()) == 1
    finally:
        manager.shutdown()


def test_scheduled_poll_waits_sixty_seconds(repository, tmp_path):
    item = add(repository)
    metadata = Metadata([LiveState.UPCOMING, LiveState.UPCOMING])
    manager = setup_manager(repository, tmp_path, metadata)
    scheduler = Scheduler(repository, metadata, manager)
    now = utc_now() + timedelta(seconds=1)
    try:
        scheduler.tick(now)
        scheduler.tick(now + timedelta(seconds=59))
        assert metadata.calls == 1
        assert repository.get_broadcast(item.id).status == B.WAITING
        scheduler.tick(now + timedelta(seconds=60))
        assert metadata.calls == 2
    finally:
        manager.shutdown()


def test_shutdown_during_metadata_fetch_cannot_start_recording(repository, tmp_path):
    add(repository)
    stop = Event()

    class ClosingMetadata:
        def fetch(self, url):
            stop.set()
            return BroadcastMetadata("Abc_123-xYz", "종료 중", "", "", LiveState.LIVE)

    metadata = ClosingMetadata()
    manager = setup_manager(repository, tmp_path, metadata)
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1), stop=stop)
        assert repository.active_session() is None
        assert repository.list_sessions() == []
    finally:
        manager.shutdown()


def test_stop_accepting_blocks_late_start(repository, tmp_path):
    item = add(repository)
    repository.transition(item.id, B.LIVE_DETECTED)
    manager = setup_manager(repository, tmp_path, Metadata([]))
    try:
        manager.stop_accepting()
        with pytest.raises(AppError):
            manager.start(item.id)
        assert repository.active_session() is None
    finally:
        manager.shutdown()


@pytest.mark.parametrize("fail", [False, True])
def test_cancel_during_metadata_fetch_cannot_resurrect_broadcast(repository, tmp_path, fail):
    item = add(repository)

    class CancellingMetadata:
        def fetch(self, url):
            repository.transition(item.id, B.CANCELLED)
            if fail:
                raise AppError(ErrorCode.NETWORK_DISCONNECTED)
            return BroadcastMetadata("Abc_123-xYz", "취소 방송", "", "", LiveState.LIVE)

    metadata = CancellingMetadata()
    manager = setup_manager(repository, tmp_path, metadata)
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        assert repository.get_broadcast(item.id).status == B.CANCELLED
        assert repository.list_sessions() == []
    finally:
        manager.shutdown()


def test_network_error_is_backoff_not_completion(repository, tmp_path):
    item = add(repository)
    metadata = Metadata([AppError(ErrorCode.NETWORK_DISCONNECTED)])
    manager = setup_manager(repository, tmp_path, metadata)
    now = utc_now() + timedelta(seconds=1)
    try:
        Scheduler(repository, metadata, manager, jitter=lambda a, b: 0).tick(now)
        item = repository.get_broadcast(item.id)
        assert item.status == B.ERROR_RETRYABLE
        assert item.next_check_at == to_iso(now + timedelta(seconds=120))
        assert repository.list_sessions() == []
    finally:
        manager.shutdown()


def test_ended_requires_two_confirmations_and_valid_file(repository, tmp_path):
    item = add(repository)
    metadata = Metadata([LiveState.LIVE, LiveState.WAS_LIVE, LiveState.WAS_LIVE])
    manager = setup_manager(repository, tmp_path, metadata)
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        wait_manager(manager)
        session = repository.list_sessions()[0]
        assert session.status == S.COMPLETE and session.ffprobe_ok
        assert session.actual_quality == "720p"
        assert "2026-10-19_테스트 방송" in session.output_path
        assert repository.get_broadcast(item.id).status == B.COMPLETED
        assert not repository.list_broadcasts() and repository.active_session() is None
    finally:
        manager.shutdown()


@pytest.mark.parametrize(
    "last", [LiveState.UNKNOWN, LiveState.LIVE, AppError(ErrorCode.NETWORK_DISCONNECTED)]
)
def test_one_ended_response_or_http_failure_cannot_complete(repository, tmp_path, last):
    item = add(repository)
    metadata = Metadata([LiveState.LIVE, LiveState.WAS_LIVE, last])
    manager = setup_manager(repository, tmp_path, metadata)
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        wait_manager(manager)
        assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
        assert repository.list_sessions()[0].status == S.PARTIAL
        assert repository.list_sessions()[0].ffprobe_ok
    finally:
        manager.shutdown()


def test_manual_stop_saves_partial_and_does_not_restart(repository, tmp_path):
    item = add(repository)
    metadata = Metadata([LiveState.LIVE])
    manager = setup_manager(repository, tmp_path, metadata, Capture(user_stop=True))
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        wait_manager(manager)
        assert repository.get_broadcast(item.id).status == B.CANCELLED
        assert repository.list_sessions()[0].status == S.PARTIAL
        assert repository.list_sessions()[0].ffprobe_ok
    finally:
        manager.shutdown()


def test_failed_verification_never_reports_complete(repository, tmp_path):
    item = add(repository)
    metadata = Metadata([LiveState.LIVE])
    manager = setup_manager(repository, tmp_path, metadata, finalizer=Finalize(fail=True))
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        wait_manager(manager)
        assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
        assert repository.list_sessions()[0].status == S.FAILED
        assert not repository.list_sessions()[0].ffprobe_ok
        assert repository.active_session() is None
    finally:
        manager.shutdown()


def test_dvr_specific_failure_falls_back_to_edge_and_keeps_partial(repository, tmp_path):
    class FallbackCapture(Capture):
        def capture(self, request, stop):
            self.requests.append(request)
            return CaptureResult(
                1 if request.from_start else 0,
                (),
                False,
                request.from_start,
                ErrorCode.DVR_UNAVAILABLE if request.from_start else None,
            )

    item = add(repository)
    metadata = Metadata([LiveState.LIVE, LiveState.WAS_LIVE, LiveState.WAS_LIVE])
    capture = FallbackCapture()
    manager = setup_manager(repository, tmp_path, metadata, capture)
    try:
        Scheduler(repository, metadata, manager).tick(utc_now() + timedelta(seconds=1))
        wait_manager(manager)
        assert [request.from_start for request in capture.requests] == [True, False]
        assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
        assert repository.list_sessions()[0].status == S.PARTIAL
    finally:
        manager.shutdown()
