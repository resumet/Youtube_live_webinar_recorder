from datetime import datetime
from threading import Event

from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import RecordingMode
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.interfaces import LiveState, MetadataProvider
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import from_iso, to_iso


class ReplayWatcher:
    def __init__(
        self, repository: Repository, metadata: MetadataProvider, recordings: RecordingManager
    ):
        self.repository, self.metadata, self.recordings = repository, metadata, recordings
        self.jobs = ReplayStore(repository)

    def tick(self, now: datetime, stop: Event | None = None) -> None:
        items = self.repository.list_broadcasts()
        live_pending = any(item.status == B.LIVE_DETECTED for item in items)
        for item in items:
            if stop and stop.is_set():
                break
            if item.status not in {B.REPLAY_WAIT, B.MISSED_BUSY}:
                continue
            self.jobs.ensure(item.id, "놓친 방송 또는 부분 녹화", now)
            job = self.jobs.get(item.id)
            if job["deadline_at"] and from_iso(job["deadline_at"]) <= now:
                if item.status == B.MISSED_BUSY:
                    self.repository.transition(item.id, B.REPLAY_WAIT)
                self.repository.transition(item.id, B.REPLAY_EXPIRED)
                self.jobs.expire(item.id)
                self.repository.note_error(item.id, ErrorCode.REPLAY_EXPIRED)
                continue
            if from_iso(job["next_check_at"]) > now:
                continue
            try:
                metadata = self.metadata.fetch(item.original_url)
                if stop and stop.is_set():
                    break
                # 조회 도중 사용자가 취소했으면 다시 활성화하지 않는다.
                current = self.repository.get_broadcast(item.id)
                if current.status not in {B.REPLAY_WAIT, B.MISSED_BUSY}:
                    continue
                ended = metadata.state in {LiveState.POST_LIVE, LiveState.WAS_LIVE}
                self.jobs.checked(item.id, now, ended=ended)
                self.repository.update_metadata(item.id, metadata, to_iso(now), to_iso(now))
                if current.status == B.MISSED_BUSY:
                    self.repository.transition(item.id, B.REPLAY_WAIT)
                if metadata.state != LiveState.WAS_LIVE or live_pending:
                    continue
                if self.repository.active_session() is not None:
                    continue
                self.recordings.start(item.id, RecordingMode.REPLAY)
            except AppError as error:
                self.jobs.checked(item.id, now, ended=False, error=error.code)
                current = self.repository.get_broadcast(item.id)
                if current.status in {B.REPLAY_WAIT, B.MISSED_BUSY}:
                    self.repository.note_error(item.id, error.code)
                    if error.code in {
                        ErrorCode.STREAM_UNAVAILABLE,
                        ErrorCode.DISK_LOW,
                        ErrorCode.WRITE_PERMISSION_DENIED,
                    }:
                        self.repository.transition(item.id, B.ERROR)
