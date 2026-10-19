import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import BroadcastStatus, Quality, RecordingMode
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.utils.errors import AppError, ErrorCode

URL = "https://youtu.be/Abc_123-xYz"


def register(repository, suffix="Abc_123-xYz"):
    return repository.add_broadcast(f"https://youtu.be/{suffix}", permission_confirmed=True)


def test_permission_required(repository):
    with pytest.raises(AppError) as error:
        repository.add_broadcast(URL, permission_confirmed=False)
    assert error.value.code == ErrorCode.PERMISSION_REQUIRED
    assert repository.list_broadcasts() == []


def test_deduplicates_by_id_not_url_and_allows_reregistration(repository):
    first = register(repository)
    with pytest.raises(AppError) as error:
        repository.add_broadcast("https://youtube.com/live/Abc_123-xYz", permission_confirmed=True)
    assert error.value.code == ErrorCode.DUPLICATE_BROADCAST
    repository.transition(first.id, BroadcastStatus.CANCELLED)
    second = register(repository)
    assert first.id != second.id
    assert len(repository.list_broadcasts()) == 1
    assert len(repository.list_broadcasts(include_terminal=True)) == 2


def test_settings_and_queue_survive_new_connection(repository, database):
    item = repository.add_broadcast(
        URL, permission_confirmed=True, quality=Quality.P720, custom_filename="한글 방송"
    )
    repository.set_setting("save_folder", "D:/녹화/강의")
    other = Database(database.path)
    other.initialize()
    restored = Repository(other)
    assert restored.get_setting("save_folder") == "D:/녹화/강의"
    assert restored.get_broadcast(item.id) == item


def test_concurrent_registration_has_one_winner(database):
    def attempt(_):
        try:
            register(Repository(database))
            return "registered"
        except AppError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("registered") == 1
    assert results.count(ErrorCode.DUPLICATE_BROADCAST) == 7


def test_two_workers_cannot_claim_two_recordings(repository, database):
    items = [register(repository, "Abc_123-xYz"), register(repository, "Xyz_987-aBc")]
    for item in items:
        repository.transition(item.id, BroadcastStatus.LIVE_DETECTED)

    def attempt(item):
        try:
            return Repository(database).claim_session(item.id, RecordingMode.LIVE)
        except AppError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, items))
    assert results.count(ErrorCode.BUSY_SINGLE_SLOT) == 1
    assert sum(hasattr(result, "broadcast_id") for result in results) == 1
    assert repository.active_session() is not None
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM recording_sessions").fetchone()[0] == 1


def test_cancel_does_not_release_running_slot(repository):
    item = register(repository)
    repository.transition(item.id, BroadcastStatus.LIVE_DETECTED)
    session = repository.claim_session(item.id, RecordingMode.LIVE)
    with pytest.raises(AppError):
        repository.transition(item.id, BroadcastStatus.CANCELLED)
    assert repository.active_session().id == session.id
    assert repository.get_broadcast(item.id).status == BroadcastStatus.RECORDING


def test_slot_claim_rolls_back_on_invalid_state(repository, database):
    item = register(repository)
    with pytest.raises(AppError):
        repository.claim_session(item.id, RecordingMode.LIVE)
    assert repository.active_session() is None
    assert repository.get_broadcast(item.id).status == BroadcastStatus.WAITING


def test_sql_constraint_rejects_unverified_complete(repository, database):
    item = register(repository)
    repository.transition(item.id, BroadcastStatus.LIVE_DETECTED)
    session = repository.claim_session(item.id, RecordingMode.LIVE)
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as connection:
        connection.execute(
            "UPDATE recording_sessions SET status='COMPLETE' WHERE id=?", (session.id,)
        )
    assert repository.active_session().id == session.id


def test_broadcast_cannot_complete_without_verified_session(repository, database):
    item = register(repository)
    with database.transaction() as connection:
        connection.execute("UPDATE broadcasts SET status='VERIFYING' WHERE id=?", (item.id,))
    with pytest.raises(AppError):
        repository.transition(item.id, BroadcastStatus.COMPLETED)


def test_bad_setting_json_uses_default(repository, database):
    with database.transaction() as connection:
        connection.execute("INSERT INTO app_settings VALUES ('broken','{','now')")
    assert repository.get_setting("broken", "기본값") == "기본값"


def test_event_redacts_urls(repository, database):
    repository.add_event("network", "오류 https://example.test/video?token=secret")
    with database.connect() as connection:
        message = connection.execute("SELECT message FROM app_events").fetchone()[0]
    assert "secret" not in message
    assert "[URL 숨김]" in message
