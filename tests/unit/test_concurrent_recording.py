from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event

import pytest

from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.scheduler import Scheduler
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.migrations import MIGRATIONS
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import RecordingMode
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.interfaces import (
    BroadcastMetadata,
    CaptureResult,
    LiveState,
    MediaInspection,
)
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import utc_now


def register(repo, index):
    return repo.add_broadcast(
        f"https://youtu.be/Test{index:07}",
        permission_confirmed=True,
        custom_filename=f"방송{index}",
    )


class LocalStreams:
    def __init__(self, count):
        self.entered = {f"Test{index:07}": Event() for index in range(count)}
        self.stops = {}

    def fetch(self, url):
        return BroadcastMetadata(url[-11:], "동시 시험", "채널", "", LiveState.LIVE)

    def capture(self, request, stop):
        identifier = request.url[-11:]
        request.work_directory.mkdir(parents=True)
        source = request.work_directory / "capture.ts"
        source.write_bytes(b"media")
        self.stops[identifier] = stop
        self.entered[identifier].set()
        assert stop.wait(15), "동시 녹화 테스트 종료 시간 초과"
        return CaptureResult(0, (source,), True, request.from_start)

    def finalize(self, sources, folder, name):
        target = folder / name
        target.write_bytes(sources[0].read_bytes())
        return MediaInspection(target, True, 2, 5, "h264", "aac", 720)


def test_five_live_streams_overlap_and_stop_is_isolated(repository, tmp_path):
    streams = LocalStreams(6)
    items = [register(repository, i) for i in range(6)]
    manager = RecordingManager(
        repository, Settings(tmp_path, min_free_bytes=0), streams, streams, streams
    )
    scheduler = Scheduler(repository, streams, manager)
    now = utc_now() + timedelta(seconds=1)
    try:
        scheduler.tick(now)
        assert all(streams.entered[item.video_id].wait(3) for item in items[:5])
        assert len(repository.active_sessions()) == 5
        assert repository.get_broadcast(items[5].id).status == B.LIVE_DETECTED
        assert not streams.entered[items[5].video_id].is_set()
        first = next(s for s in repository.active_sessions() if s.broadcast_id == items[0].id)
        manager.stop(expected_session_id=first.id)
        manager.tasks[first.id].future.result(5)
        assert repository.get_broadcast(items[0].id).status == B.CANCELLED
        assert all(not streams.stops[item.video_id].is_set() for item in items[1:5])
        assert not manager.freeze_if_idle()
        scheduler.tick(now + timedelta(seconds=60))
        assert streams.entered[items[5].video_id].wait(3)
        assert len(repository.active_sessions()) == 5
        # 지연된 UI 중지 요청이 새 작업에 영향을 주지 않는다.
        manager.stop(expected_session_id=first.id)
        assert not streams.stops[items[5].video_id].is_set()
    finally:
        manager.shutdown()
    assert not repository.active_sessions()
    assert all(repository.get_broadcast(i.id).status == B.ERROR_RETRYABLE for i in items[1:])
    assert all(Path(s.output_path).is_file() for s in repository.list_sessions())


def test_folder_and_limit_changes_apply_to_new_sessions(repository, tmp_path):
    old, new = tmp_path / "기존", tmp_path / "새 저장소"
    streams = LocalStreams(3)
    items = [register(repository, i) for i in range(3)]
    for item in items:
        repository.transition(item.id, B.LIVE_DETECTED)
    manager = RecordingManager(
        repository, Settings(old, min_free_bytes=0), streams, streams, streams
    )
    try:
        first = manager.start(items[0].id)
        assert streams.entered[items[0].video_id].wait(3)
        with manager.lock:
            manager.settings = replace(manager.settings, save_folder=new)
        second = manager.start(items[1].id)
        assert streams.entered[items[1].video_id].wait(3)
        with manager.lock:
            manager.settings = replace(manager.settings, max_concurrent_recordings=1)
        with pytest.raises(AppError) as error:
            manager.start(items[2].id)
        assert error.value.code == ErrorCode.RECORDING_LIMIT
        assert len(repository.active_sessions()) == 2
        manager.stop(expected_session_id=first.id)
        manager.tasks[first.id].future.result(5)
        assert Path(repository.get_session(first.id).output_path).parent == old
        assert not streams.stops[items[1].video_id].is_set()
        manager.stop(expected_session_id=second.id)
        manager.tasks[second.id].future.result(5)
        assert Path(repository.get_session(second.id).output_path).parent == new
        assert manager.freeze_if_idle()
    finally:
        manager.shutdown()


def test_atomic_capacity_and_duplicate_claims(repository, database):
    items = [register(repository, i) for i in range(12)]
    for item in items:
        repository.transition(item.id, B.LIVE_DETECTED)

    def claim(item):
        try:
            return Repository(database).claim_session(item.id, RecordingMode.LIVE)
        except AppError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(claim, items))
    assert results.count(ErrorCode.RECORDING_LIMIT) == 7
    assert len(repository.active_sessions()) == 5
    with pytest.raises(AppError) as error:
        repository.claim_session(repository.active_sessions()[0].broadcast_id, RecordingMode.LIVE)
    assert error.value.code == ErrorCode.INVALID_STATE
    assert database.check_integrity()


@pytest.mark.parametrize("value", [0, 11, True, "5", None, 1.5])
def test_corrupt_recording_limit_recovers_default(repository, value):
    repository.set_setting("max_concurrent_recordings", value)
    assert Settings.load(repository).max_concurrent_recordings == 5
    assert repository.get_setting("max_concurrent_recordings") == 5


def test_v3_migration_preserves_existing_data_and_adds_capacity(tmp_path):
    database = Database(tmp_path / "old.db")
    with database.transaction() as connection:
        for version in range(1, 4):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
        connection.execute("PRAGMA user_version=3")
    repo = Repository(database)
    repo.set_setting("save_folder", str(tmp_path))
    first = register(repo, 0)
    repo.transition(first.id, B.LIVE_DETECTED)
    previous = repo.claim_session(first.id, RecordingMode.LIVE, save_folder=tmp_path)
    database.initialize()
    assert repo.get_session(previous.id) == previous
    assert Settings.load(repo).save_folder == tmp_path
    second = register(repo, 1)
    repo.transition(second.id, B.LIVE_DETECTED)
    repo.claim_session(second.id, RecordingMode.LIVE)
    assert len(repo.active_sessions()) == 2
    assert database.check_integrity()
