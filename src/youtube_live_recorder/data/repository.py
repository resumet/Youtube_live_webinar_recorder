import json
import sqlite3
from typing import Any
from uuid import uuid4

from youtube_live_recorder.core.state_machine import validate_broadcast_transition
from youtube_live_recorder.data.db import Database
from youtube_live_recorder.data.models import (
    Broadcast,
    BroadcastStatus,
    Quality,
    RecordingMode,
    RecordingSession,
    SessionStatus,
)
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.logging import redact
from youtube_live_recorder.utils.time import to_iso, utc_now
from youtube_live_recorder.utils.urls import parse_video_url

_ACTIVE_SQL = "('CREATED','RUNNING','RECONNECTING','FINALIZING','VERIFYING')"
_TERMINAL_SQL = "('COMPLETED','CANCELLED','REPLAY_EXPIRED')"


def _broadcast(row: sqlite3.Row) -> Broadcast:
    values = dict(row)
    values["status"] = BroadcastStatus(values["status"])
    values["preferred_quality"] = Quality(values["preferred_quality"])
    values["permission_confirmed"] = bool(values["permission_confirmed"])
    return Broadcast(**values)


def _session(row: sqlite3.Row) -> RecordingSession:
    values = dict(row)
    values["status"] = SessionStatus(values["status"])
    values["mode"] = RecordingMode(values["mode"])
    values["selected_quality"] = Quality(values["selected_quality"])
    values["ffprobe_ok"] = bool(values["ffprobe_ok"])
    return RecordingSession(**values)


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_broadcast(
        self,
        url: str,
        *,
        permission_confirmed: bool,
        quality: Quality = Quality.P1080,
        custom_filename: str = "",
    ) -> Broadcast:
        parsed = parse_video_url(url)
        quality = Quality(quality)
        if permission_confirmed is not True:
            raise AppError(ErrorCode.PERMISSION_REQUIRED)
        now, identifier = to_iso(utc_now()), str(uuid4())
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO broadcasts
                    (id,video_id,original_url,registered_at,status,preferred_quality,
                     custom_filename,permission_confirmed,next_check_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        parsed.video_id,
                        parsed.canonical_url,
                        now,
                        BroadcastStatus.WAITING,
                        quality,
                        custom_filename,
                        1,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "broadcasts.video_id" in str(exc):
                raise AppError(ErrorCode.DUPLICATE_BROADCAST) from None
            raise
        return self.get_broadcast(identifier)

    def get_broadcast(self, identifier: str) -> Broadcast:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM broadcasts WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError("등록한 방송을 찾을 수 없습니다.")
        return _broadcast(row)

    def list_broadcasts(self, *, include_terminal: bool = False) -> list[Broadcast]:
        condition = "" if include_terminal else f"WHERE status NOT IN {_TERMINAL_SQL}"
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM broadcasts {condition} ORDER BY registered_at, rowid"
            ).fetchall()
        return [_broadcast(row) for row in rows]

    def transition(self, identifier: str, target: BroadcastStatus) -> Broadcast:
        target = BroadcastStatus(target)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM broadcasts WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise KeyError("등록한 방송을 찾을 수 없습니다.")
            validate_broadcast_transition(BroadcastStatus(row["status"]), target)
            if target == BroadcastStatus.COMPLETED:
                verified = connection.execute(
                    "SELECT id FROM recording_sessions WHERE broadcast_id=? AND status='COMPLETE'",
                    (identifier,),
                ).fetchone()
                if not verified:
                    raise AppError(ErrorCode.INVALID_STATE, "검증된 녹화 파일이 없습니다.")
            if target == BroadcastStatus.CANCELLED:
                active = connection.execute(
                    f"SELECT id FROM recording_sessions WHERE broadcast_id=? "
                    f"AND status IN {_ACTIVE_SQL}",
                    (identifier,),
                ).fetchone()
                if active:
                    raise AppError(ErrorCode.INVALID_STATE, "먼저 녹화를 안전하게 중지해야 합니다.")
            connection.execute(
                "UPDATE broadcasts SET status=?, updated_at=? WHERE id=?",
                (target, to_iso(utc_now()), identifier),
            )
        return self.get_broadcast(identifier)

    def claim_session(self, identifier: str, mode: RecordingMode) -> RecordingSession:
        """DB 원자적 슬롯 획득. 프로세스 생성 전 CREATED 상태부터 슬롯을 점유한다."""
        mode = RecordingMode(mode)
        now, session_id = to_iso(utc_now()), str(uuid4())
        with self.database.transaction() as connection:
            active = connection.execute(
                f"SELECT id FROM recording_sessions WHERE status IN {_ACTIVE_SQL}"
            ).fetchone()
            if active:
                raise AppError(ErrorCode.BUSY_SINGLE_SLOT)
            row = connection.execute(
                "SELECT * FROM broadcasts WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise KeyError("등록한 방송을 찾을 수 없습니다.")
            target = (
                BroadcastStatus.RECORDING
                if mode == RecordingMode.LIVE
                else BroadcastStatus.REPLAY_DOWNLOADING
            )
            validate_broadcast_transition(BroadcastStatus(row["status"]), target)
            connection.execute(
                """INSERT INTO recording_sessions
                   (id,broadcast_id,started_at,status,mode,selected_quality,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    identifier,
                    now,
                    SessionStatus.CREATED,
                    mode,
                    row["preferred_quality"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE broadcasts SET status=?,updated_at=? WHERE id=?", (target, now, identifier)
            )
        return self.get_session(session_id)

    def get_session(self, identifier: str) -> RecordingSession:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recording_sessions WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError("녹화 작업을 찾을 수 없습니다.")
        return _session(row)

    def active_session(self) -> RecordingSession | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM recording_sessions WHERE status IN {_ACTIVE_SQL}"
            ).fetchone()
        return _session(row) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO app_settings(key,value_json,updated_at) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (key, encoded, to_iso(utc_now())),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return default

    def add_event(
        self,
        category: str,
        message: str,
        *,
        severity: str = "INFO",
        broadcast_id: str | None = None,
        session_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO app_events
                (event_time,severity,category,broadcast_id,session_id,error_code,message)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    to_iso(utc_now()),
                    severity,
                    category,
                    broadcast_id,
                    session_id,
                    error_code,
                    redact(message),
                ),
            )
