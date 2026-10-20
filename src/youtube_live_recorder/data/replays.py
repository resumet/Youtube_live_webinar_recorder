from datetime import datetime, timedelta
from uuid import uuid4

from youtube_live_recorder.config import POLL_SECONDS, REPLAY_POLL_SECONDS, REPLAY_WINDOW_SECONDS
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.utils.time import to_iso, utc_now


class ReplayStore:
    def __init__(self, repository: Repository):
        self.database = repository.database

    def ensure(self, broadcast_id: str, reason: str, now: datetime | None = None) -> None:
        timestamp = to_iso(now or utc_now())
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO replay_jobs
                (id,broadcast_id,status,reason,created_at,next_check_at)
                VALUES (?,?,'WAITING',?,?,?) ON CONFLICT(broadcast_id) DO NOTHING""",
                (str(uuid4()), broadcast_id, reason, timestamp, timestamp),
            )

    def get(self, broadcast_id: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM replay_jobs WHERE broadcast_id=?", (broadcast_id,)
            ).fetchone()
        return dict(row) if row else None

    def checked(self, broadcast_id: str, now: datetime, *, ended: bool, error: str = "") -> None:
        with self.database.transaction() as connection:
            manual = connection.execute(
                "SELECT archive_download FROM broadcasts WHERE id=?", (broadcast_id,)
            ).fetchone()[0]
            deadline = (
                to_iso(now + timedelta(seconds=REPLAY_WINDOW_SECONDS))
                if ended and not manual
                else None
            )
            interval = POLL_SECONDS if manual else REPLAY_POLL_SECONDS
            connection.execute(
                """UPDATE replay_jobs SET last_attempt_at=?,next_check_at=?,
                attempts=attempts+1,error_code=?,deadline_at=COALESCE(deadline_at,?)
                WHERE broadcast_id=?""",
                (
                    to_iso(now),
                    to_iso(now + timedelta(seconds=interval)),
                    error or None,
                    deadline,
                    broadcast_id,
                ),
            )

    def expire(self, broadcast_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE replay_jobs SET status='EXPIRED',error_code='REPLAY_EXPIRED' "
                "WHERE broadcast_id=?",
                (broadcast_id,),
            )

    def defer(self, broadcast_id: str, now: datetime, *, immediate: bool = False) -> None:
        with self.database.transaction() as connection:
            manual = connection.execute(
                "SELECT archive_download FROM broadcasts WHERE id=?", (broadcast_id,)
            ).fetchone()[0]
            interval = POLL_SECONDS if manual else REPLAY_POLL_SECONDS
            connection.execute(
                "UPDATE replay_jobs SET status='WAITING',next_check_at=? WHERE broadcast_id=?",
                (
                    to_iso(now if immediate else now + timedelta(seconds=interval)),
                    broadcast_id,
                ),
            )
