from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.recovery_manager import RecoveryManager
from youtube_live_recorder.core.replay_watcher import ReplayWatcher
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import RecordingMode
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureResult,
    LiveState,
    MediaInspection,
)
from youtube_live_recorder.services.power import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, PowerManager
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import from_iso, utc_now


def add(repo, identifier="Abc_123-xYz", state=B.LIVE_DETECTED):
    item = repo.add_broadcast("https://youtu.be/" + identifier, permission_confirmed=True)
    repo.transition(item.id, state)
    return item


class Metadata:
    def __init__(self, *states, default=LiveState.LIVE):
        self.states = list(states)
        self.default, self.calls = default, 0

    def fetch(self, url):
        self.calls += 1
        state = self.states.pop(0) if self.states else self.default
        if isinstance(state, Exception):
            raise state
        return BroadcastMetadata(url[-11:], "테스트", "채널", "", state)


class Finalizer:
    def __init__(self):
        self.calls = []
        self.verifier = self

    def inspect(self, path):
        valid = path.is_file() and path.read_bytes() == b"media"
        return MediaInspection(path, valid, 2, 5, "h264", "aac", 720)

    def finalize(self, sources, folder, name):
        if not sources or not any(self.inspect(p).valid for p in sources):
            raise AppError(ErrorCode.FINALIZE_FAILED)
        self.calls.append(tuple(sources))
        target = folder / name
        target.write_bytes(b"media")
        return self.inspect(target)


class Capture:
    def __init__(self, errors=(), hold=False, media=True):
        self.errors = list(errors)
        self.requests = []
        self.hold, self.media = hold, media
        self.entered = Event()

    def capture(self, request, stop):
        self.requests.append(request)
        request.work_directory.mkdir(parents=True)
        path = request.work_directory / "capture.ts"
        if self.media:
            path.write_bytes(b"media")
        self.entered.set()
        if self.hold:
            assert stop.wait(5), "테스트가 녹화를 중지하지 못했습니다."
        error = self.errors.pop(0) if self.errors else None
        return CaptureResult(
            1 if error else 0,
            (path,) if self.media else (),
            stop.is_set(),
            request.from_start,
            error,
        )


def manager(repo, folder, metadata, capture, **kwargs):
    return RecordingManager(
        repo,
        Settings(folder, min_free_bytes=0, max_reconnect_attempts=2, max_concurrent_recordings=1),
        metadata,
        capture,
        Finalizer(),
        confirmation_seconds=0,
        jitter=lambda *_: 0,
        **kwargs,
    )


def test_reconnection_preserves_separate_parts_and_never_claims_complete(repository, tmp_path):
    item = add(repository)
    capture = Capture([ErrorCode.NETWORK_DISCONNECTED, None])
    metadata = Metadata(LiveState.LIVE, LiveState.WAS_LIVE, LiveState.WAS_LIVE)
    delays = []
    recorder = manager(
        repository,
        tmp_path,
        metadata,
        capture,
        retry_wait=lambda stop, delay: delays.append(delay) or False,
    )
    try:
        session = recorder.start(item.id)
        recorder.future.result(5)
        result = repository.get_session(session.id)
        segments = repository.list_segments(session.id)
        assert result.status == S.PARTIAL and result.ffprobe_ok
        assert result.duration_seconds == 4 and result.size_bytes == 10
        assert len({s["final_path"] for s in segments}) == 2
        assert all(Path(s["final_path"]).exists() for s in segments)
        assert all(Path(s["temporary_path"]).joinpath("capture.ts").exists() for s in segments)
        assert [r.from_start for r in capture.requests] == [True, False]
        assert delays == [15]
        assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
        assert ReplayStore(repository).get(item.id)["deadline_at"]
    finally:
        recorder.shutdown()


def test_retry_limit_opens_circuit_and_keeps_replay_queue(repository, tmp_path):
    item = add(repository)
    capture = Capture([ErrorCode.NETWORK_DISCONNECTED] * 3)
    delays = []
    recorder = manager(
        repository,
        tmp_path,
        Metadata(),
        capture,
        retry_wait=lambda stop, delay: delays.append(delay) or False,
    )
    try:
        recorder.start(item.id)
        recorder.future.result(5)
        assert len(capture.requests) == 3 and delays == [15, 30]
        assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
        job = ReplayStore(repository).get(item.id)
        assert job["deadline_at"] is None  # 아직 진행 중인 방송의 기한을 미리 시작하지 않는다.
        assert from_iso(job["next_check_at"]) > utc_now()
        Scheduler(repository, Metadata(), recorder).tick()
        assert len(capture.requests) == 3
    finally:
        recorder.shutdown()


def test_disk_low_during_capture_preserves_file_and_is_not_user_cancel(repository, tmp_path):
    item = add(repository)
    capture = Capture(hold=True)

    def disk(folder, minimum, *, create=False):
        if not create:
            raise AppError(ErrorCode.DISK_LOW)
        return 1234

    recorder = manager(
        repository, tmp_path, Metadata(), capture, storage_check=disk, disk_interval=0.01
    )
    try:
        session = recorder.start(item.id)
        recorder.future.result(5)
        assert repository.get_session(session.id).status == S.PARTIAL
        item = repository.get_broadcast(item.id)
        assert item.status == B.ERROR and item.last_error_code == ErrorCode.DISK_LOW
        assert len(capture.requests) == 1
    finally:
        recorder.shutdown()


def test_stop_without_media_still_cancels_instead_of_auto_retry(repository, tmp_path):
    item = add(repository)
    capture = Capture(hold=True, media=False)
    recorder = manager(repository, tmp_path, Metadata(), capture)
    try:
        recorder.start(item.id)
        assert capture.entered.wait(2)
        recorder.stop()
        recorder.future.result(5)
        assert repository.get_broadcast(item.id).status == B.CANCELLED
        assert repository.list_sessions()[0].status == S.FAILED
    finally:
        recorder.shutdown()


def test_replay_window_uses_end_observation_and_survives_restart(repository, tmp_path):
    item = add(repository, state=B.REPLAY_WAIT)
    capture = Capture()
    metadata = Metadata(LiveState.LIVE, LiveState.POST_LIVE)
    recorder = manager(repository, tmp_path, metadata, capture)
    start = datetime(2026, 10, 19, tzinfo=UTC)
    try:
        watcher = ReplayWatcher(repository, metadata, recorder)
        watcher.tick(start)
        assert ReplayStore(repository).get(item.id)["deadline_at"] is None
        watcher.tick(start + timedelta(minutes=29))
        assert metadata.calls == 1
        watcher.tick(start + timedelta(hours=30))  # 방송이 하루 넘게 진행된 경우
        deadline = ReplayStore(repository).get(item.id)["deadline_at"]
        assert from_iso(deadline) == start + timedelta(hours=54)
        restarted = ReplayWatcher(repository, metadata, recorder)
        restarted.tick(start + timedelta(hours=54))
        assert repository.get_broadcast(item.id).status == B.REPLAY_EXPIRED
        assert ReplayStore(repository).get(item.id)["deadline_at"] == deadline
        assert not capture.requests and metadata.calls == 2
    finally:
        recorder.shutdown()


def test_replay_creates_separate_file_and_complete_job(repository, tmp_path):
    item = add(repository, state=B.REPLAY_WAIT)
    live_file = tmp_path / "기존 라이브.mp4"
    live_file.write_bytes(b"untouched")
    metadata, capture = Metadata(default=LiveState.WAS_LIVE), Capture()
    recorder = manager(repository, tmp_path, metadata, capture)
    try:
        ReplayWatcher(repository, metadata, recorder).tick(utc_now())
        recorder.future.result(5)
        assert repository.get_broadcast(item.id).status == B.COMPLETED
        session = repository.list_sessions()[0]
        assert session.mode == RecordingMode.REPLAY and session.status == S.COMPLETE
        assert "다시보기" in session.output_path
        assert live_file.read_bytes() == b"untouched"
        assert ReplayStore(repository).get(item.id)["status"] == "COMPLETE"
    finally:
        recorder.shutdown()


def test_live_preempts_replay_without_marking_live_missed(repository, tmp_path):
    replay = add(repository, state=B.REPLAY_WAIT)
    ReplayStore(repository).ensure(replay.id, "시험")
    live = add(repository, "Xyz_987-aBc")
    capture = Capture(hold=True)
    recorder = manager(repository, tmp_path, Metadata(), capture)
    scheduler = Scheduler(repository, Metadata(), recorder)
    try:
        recorder.start(replay.id, RecordingMode.REPLAY)
        assert capture.entered.wait(2)
        scheduler.tick(utc_now() + timedelta(seconds=1))
        recorder.future.result(5)
        assert repository.get_broadcast(replay.id).status == B.REPLAY_WAIT
        assert repository.get_broadcast(live.id).status == B.LIVE_DETECTED
        capture.entered.clear()
        scheduler.tick(utc_now() + timedelta(seconds=2))
        assert capture.entered.wait(2)
        assert repository.active_session().broadcast_id == live.id
        recorder.stop()
        recorder.future.result(5)
        assert len(capture.requests) == 2
    finally:
        recorder.shutdown()


@pytest.mark.parametrize("has_file", [True, False])
def test_recovery_preserves_originals_and_releases_stale_slot(repository, tmp_path, has_file):
    item = add(repository)
    session = repository.claim_session(item.id, RecordingMode.LIVE)
    work = tmp_path / ".ylr-work" / session.id
    work.mkdir(parents=True)
    repository.set_session_state(session.id, S.RUNNING, work_directory=str(work))
    repository.add_segment(session.id, 0, str(work))
    if has_file:
        (work / "capture.ts").write_bytes(b"media")
    recovery = RecoveryManager(repository, Settings(tmp_path), Finalizer())
    recovery.run()
    assert repository.active_session() is None
    recovered = repository.get_session(session.id)
    assert recovered.status == (S.PARTIAL if has_file else S.FAILED)
    assert repository.get_broadcast(item.id).status == B.ERROR_RETRYABLE
    assert recovered.ffprobe_ok is has_file
    if has_file:
        assert Path(recovered.output_path).exists() and (work / "capture.ts").exists()
    before = list(tmp_path.glob("*.mp4"))
    recovery.run()
    assert list(tmp_path.glob("*.mp4")) == before


def test_power_requests_system_only_and_releases_same_thread():
    flags = []
    power = PowerManager(lambda value: flags.append(value) or ES_CONTINUOUS)
    power.set_required(True)
    power.set_required(True)
    power.close()
    assert flags == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS]


def test_recovered_broadcast_resumes_live_without_replacing_earlier_part(repository, tmp_path):
    item = add(repository)
    old = repository.claim_session(item.id, RecordingMode.LIVE)
    work = tmp_path / ".ylr-work" / old.id
    work.mkdir(parents=True)
    (work / "capture.ts").write_bytes(b"media")
    repository.set_session_state(old.id, S.RUNNING, work_directory=str(work))
    repository.add_segment(old.id, 0, str(work))
    RecoveryManager(repository, Settings(tmp_path), Finalizer()).run()
    recovered_path = Path(repository.get_session(old.id).output_path)
    capture = Capture(hold=True)
    metadata = Metadata()
    recorder = manager(repository, tmp_path, metadata, capture)
    try:
        Scheduler(repository, metadata, recorder).tick(utc_now() + timedelta(seconds=1))
        assert capture.entered.wait(2)
        assert not capture.requests[0].from_start
        assert repository.active_session().id != old.id
        recorder.stop()
        recorder.future.result(5)
        assert recovered_path.read_bytes() == b"media"
        assert len(repository.list_sessions()) == 2
    finally:
        recorder.shutdown()


def test_replay_full_retry_can_complete_but_keeps_failed_attempt(repository, tmp_path):
    item = add(repository, state=B.REPLAY_WAIT)
    ReplayStore(repository).ensure(item.id, "다시보기")
    capture = Capture([ErrorCode.NETWORK_DISCONNECTED, None])
    recorder = manager(repository, tmp_path, Metadata(), capture, retry_wait=lambda *_: False)
    try:
        session = recorder.start(item.id, RecordingMode.REPLAY)
        recorder.future.result(5)
        result = repository.get_session(session.id)
        assert result.status == S.COMPLETE and result.duration_seconds == 2
        assert len(repository.list_segments(session.id)) == 2
        assert len(list(tmp_path.glob("*.mp4"))) == 2
    finally:
        recorder.shutdown()


def test_manual_error_retry_cannot_extend_existing_replay_deadline(repository):
    item = add(repository, state=B.REPLAY_WAIT)
    jobs = ReplayStore(repository)
    now = utc_now()
    jobs.ensure(item.id, "방송 종료", now)
    jobs.checked(item.id, now, ended=True)
    deadline = jobs.get(item.id)["deadline_at"]
    repository.transition(item.id, B.ERROR)
    repository.retry_broadcast(item.id)
    assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
    assert jobs.get(item.id)["deadline_at"] == deadline


def test_disk_low_while_remux_does_not_leave_slot_stuck(repository, tmp_path):
    item = add(repository)
    recorder = manager(repository, tmp_path, Metadata(), Capture([ErrorCode.NETWORK_DISCONNECTED]))

    class NoRoom:
        def finalize(self, *_):
            raise AppError(ErrorCode.DISK_LOW)

    recorder.finalizer = NoRoom()
    try:
        recorder.start(item.id)
        recorder.future.result(5)
        assert repository.active_session() is None
        assert repository.get_broadcast(item.id).status == B.ERROR
        assert repository.list_sessions()[0].status == S.FAILED
    finally:
        recorder.shutdown()
