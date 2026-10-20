from dataclasses import replace
from datetime import timedelta
from threading import Event

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.archive_downloads import ArchiveDownloads
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.recovery_manager import RecoveryManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import Quality, RecordingMode
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.download_progress import DownloadProgress
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureResult,
    LiveState,
    MediaInspection,
)
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import from_iso, to_iso, utc_now

URL = "https://youtube.com/live/Abc_123-xYz?t=600"


class Media:
    def __init__(self, state=LiveState.WAS_LIVE, *, hold=False):
        self.state, self.hold = state, hold
        self.requests = []
        self.entered = Event()
        self.verifier = self

    def fetch(self, url):
        return BroadcastMetadata(
            url[-11:],
            "종료영상",
            "시험 채널",
            "",
            self.state,
            actual_start_at=to_iso(utc_now() - timedelta(days=365)),
        )

    def capture(self, request, stop):
        self.requests.append(request)
        request.work_directory.mkdir(parents=True)
        source = request.work_directory / "capture.mp4"
        source.write_bytes(b"media")
        self.entered.set()
        if self.hold:
            assert stop.wait(10)
        return CaptureResult(0, (source,), stop.is_set(), request.from_start)

    def inspect(self, path):
        return MediaInspection(path, path.exists(), 120, 5, "h264", "aac", 720)

    def finalize(self, sources, folder, name):
        target = folder / name
        target.write_bytes(b"media")
        return self.inspect(target)


def register(repository, media, url=URL):
    return ArchiveDownloads(repository, media).register(
        url, permission_confirmed=True, quality=Quality.P720, custom_filename="종료영상"
    )


def recorder(repository, tmp_path, media, limit=5):
    return RecordingManager(
        repository,
        Settings(tmp_path, min_free_bytes=0, max_concurrent_recordings=limit),
        media,
        media,
        media,
    )


def test_replay_retry_resets_transfer_bytes_without_counting_preserved_partial_file(
    repository,
    tmp_path,
):
    class ReconnectingMedia(Media):
        def capture(self, request, stop):
            assert manager.progress_snapshot() == {}
            result = super().capture(request, stop)
            progress = DownloadProgress(100, 200, 50, 10, 10, True, False, 0)
            request.on_progress(progress)
            assert list(manager.progress_snapshot().values()) == [progress]
            if len(self.requests) == 1:
                return replace(result, return_code=1, error_code=ErrorCode.NETWORK_DISCONNECTED)
            request.on_progress(
                replace(progress, downloaded_bytes=200, percent=100, transfer_finished=True)
            )
            return result

    media = ReconnectingMedia()
    manager = RecordingManager(
        repository,
        Settings(tmp_path, min_free_bytes=0, max_reconnect_attempts=1),
        media,
        media,
        media,
        retry_wait=lambda *_: False,
        jitter=lambda *_: 0,
    )
    try:
        item = register(repository, media)
        session = manager.start(item.id, RecordingMode.REPLAY)
        manager.future.result(10)
        assert len(media.requests) == 2
        assert repository.get_session(session.id).status == S.COMPLETE
        assert manager.progress_snapshot()[session.id].downloaded_bytes == 200
        assert all((request.work_directory / "capture.mp4").exists() for request in media.requests)
    finally:
        manager.shutdown()


@pytest.mark.parametrize(
    "state", [LiveState.LIVE, LiveState.UPCOMING, LiveState.NOT_LIVE, LiveState.UNKNOWN]
)
def test_reject_non_ended_live_without_creating_queue(repository, state):
    with pytest.raises(AppError) as error:
        register(repository, Media(state))
    assert error.value.code == ErrorCode.ENDED_LIVE_REQUIRED
    assert repository.list_broadcasts(include_terminal=True) == []


def test_permission_checked_before_network_and_duplicate_is_atomic(repository):
    class NoNetwork:
        def fetch(self, url):
            pytest.fail("권한 확인 전 네트워크 요청")

    with pytest.raises(AppError) as error:
        ArchiveDownloads(repository, NoNetwork()).register(URL, permission_confirmed=False)
    assert error.value.code == ErrorCode.PERMISSION_REQUIRED
    item = register(repository, Media())
    with pytest.raises(AppError) as error:
        register(repository, Media())
    assert error.value.code == ErrorCode.DUPLICATE_BROADCAST
    assert len(repository.list_broadcasts()) == 1
    assert ReplayStore(repository).get(item.id)["deadline_at"] is None


def test_old_archive_downloads_whole_replay_and_can_download_again(repository, tmp_path):
    media = Media()
    item = register(repository, media)
    manager = recorder(repository, tmp_path, media)
    try:
        Scheduler(repository, media, manager).tick(utc_now() + timedelta(days=2))
        manager.future.result(5)
        session = repository.list_sessions()[0]
        assert session.mode == RecordingMode.REPLAY and session.status == S.COMPLETE
        assert session.ffprobe_ok and session.duration_seconds == 120
        assert not session.from_start_attempted
        assert [request.from_start for request in media.requests] == [False]
        assert media.requests[0].url == "https://www.youtube.com/watch?v=Abc_123-xYz"
        assert repository.get_broadcast(item.id).status == B.COMPLETED
        assert register(repository, media).id != item.id
    finally:
        manager.shutdown()


def test_processing_poll_and_restart_keep_manual_intent_without_expiry(repository, tmp_path):
    media = Media(LiveState.POST_LIVE)
    item = register(repository, media)
    manager = recorder(repository, tmp_path, media)
    now = utc_now() + timedelta(seconds=1)
    try:
        Scheduler(repository, media, manager).tick(now)
        job = ReplayStore(repository).get(item.id)
        assert job["deadline_at"] is None
        assert from_iso(job["next_check_at"]) == now + timedelta(seconds=60)
        assert not media.requests
        reopened_db = Database(repository.database.path)
        reopened_db.initialize()
        reopened = Repository(reopened_db)
        assert reopened.get_broadcast(item.id).archive_download
        media.state = LiveState.WAS_LIVE
        Scheduler(reopened, media, manager).tick(now + timedelta(days=3))
        manager.future.result(5)
        assert reopened.get_broadcast(item.id).status == B.COMPLETED
    finally:
        manager.shutdown()


def test_shared_capacity_and_user_stop_never_restarts_cancelled_download(repository, tmp_path):
    media = Media(hold=True)
    first = register(repository, media)
    second = register(repository, media, "https://youtu.be/Xyz_987-aBc")
    manager = recorder(repository, tmp_path, media, limit=1)
    scheduler = Scheduler(repository, media, manager)
    try:
        scheduler.tick(utc_now() + timedelta(seconds=1))
        assert media.entered.wait(3)
        active = repository.active_session()
        assert active.broadcast_id == first.id
        assert repository.get_broadcast(second.id).status == B.REPLAY_WAIT
        assert (
            not manager.preempt_replay()
        )  # 사용자 다운로드를 새 라이브 때문에 중간에 버리지 않는다.
        manager.stop(expected_session_id=active.id)
        manager.tasks[active.id].future.result(5)
        assert repository.get_broadcast(first.id).status == B.CANCELLED
        scheduler.tick(utc_now() + timedelta(seconds=2))
        assert repository.active_session().broadcast_id == second.id
        assert len(repository.list_sessions()) == 2
    finally:
        manager.shutdown()


@pytest.mark.parametrize("shutdown", [False, True])
def test_recovery_and_retry_cannot_switch_download_into_live_mode(repository, tmp_path, shutdown):
    media = Media(hold=shutdown)
    item = register(repository, media)
    manager = recorder(repository, tmp_path, media)
    try:
        if shutdown:
            manager.start(item.id, RecordingMode.REPLAY)
            assert media.entered.wait(3)
            manager.shutdown()
            assert repository.get_broadcast(item.id).status == B.ERROR_RETRYABLE
        else:
            repository.claim_session(item.id, RecordingMode.REPLAY, save_folder=tmp_path)
        RecoveryManager(repository, manager.settings, media).run()
        if not shutdown:
            repository.transition(item.id, B.ERROR)
            repository.retry_broadcast(item.id)
            assert repository.get_broadcast(item.id).status == B.REPLAY_WAIT
    finally:
        manager.shutdown()
    media.hold = False
    restarted = recorder(repository, tmp_path, media)
    try:
        Scheduler(repository, media, restarted).tick(utc_now() + timedelta(seconds=61))
        restarted.future.result(5)
        assert repository.get_broadcast(item.id).status == B.COMPLETED
        assert all(s.mode == RecordingMode.REPLAY for s in repository.list_sessions())
        assert all(not r.from_start for r in media.requests)
    finally:
        restarted.shutdown()


def test_existing_live_and_manual_download_share_available_slots(repository, tmp_path):
    media = Media(hold=True)
    live = repository.add_broadcast("https://youtu.be/Xyz_987-aBc", permission_confirmed=True)
    repository.transition(live.id, B.LIVE_DETECTED)
    archive = register(repository, media)
    manager = recorder(repository, tmp_path, media)
    try:
        manager.start(live.id)
        manager.settings = replace(manager.settings, max_concurrent_recordings=2)
        Scheduler(repository, media, manager).replays.tick(utc_now() + timedelta(seconds=1))
        assert len(repository.active_sessions()) == 2
        assert repository.get_broadcast(archive.id).status == B.REPLAY_DOWNLOADING
    finally:
        manager.shutdown()
