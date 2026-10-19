import sqlite3

import pytest

from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.migrations import MIGRATIONS, SCHEMA_VERSION


def test_schema_is_idempotent_with_wal_and_foreign_keys(database):
    database.initialize()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert {
            "broadcasts",
            "recording_sessions",
            "recording_segments",
            "replay_jobs",
            "app_settings",
            "app_events",
        } <= names
    assert database.check_integrity()


def test_transaction_rolls_back(database):
    with pytest.raises(RuntimeError), database.transaction() as connection:
        connection.execute("INSERT INTO app_settings VALUES ('test','1','now')")
        raise RuntimeError("실패 주입")
    with database.connect() as connection:
        assert connection.execute("SELECT * FROM app_settings").fetchall() == []


def test_failed_migration_is_atomic(tmp_path, monkeypatch):
    database = Database(tmp_path / "app.db")
    monkeypatch.setitem(MIGRATIONS, 1, ("CREATE TABLE temporary_test(id TEXT)", "INVALID SQL"))
    with pytest.raises(sqlite3.OperationalError):
        database.initialize()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='temporary_test'"
        ).fetchall()


def test_future_database_not_downgraded(database):
    with database.connect() as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="최신 프로그램"):
        database.initialize()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
