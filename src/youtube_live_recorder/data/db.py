import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from youtube_live_recorder.data.migrations import MIGRATIONS, SCHEMA_VERSION


class Database:
    """각 작업마다 연결을 열어 Qt/작업 스레드 간 sqlite 연결을 공유하지 않는다."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
        with self.transaction() as connection:
            current = connection.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    "새 버전에서 생성한 데이터입니다. 최신 프로그램을 사용해 주세요."
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[version]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {version}")

    def check_integrity(self) -> bool:
        with self.connect() as connection:
            ok = connection.execute("PRAGMA quick_check").fetchall()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            return [row[0] for row in ok] == ["ok"] and not foreign_keys
