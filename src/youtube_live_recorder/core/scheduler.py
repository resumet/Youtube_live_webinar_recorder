import logging
import random
from datetime import datetime, timedelta
from threading import Event

from youtube_live_recorder.config import POLL_SECONDS
from youtube_live_recorder.core.recording_manager import RecordingManager
from youtube_live_recorder.core.replay_watcher import ReplayWatcher
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.interfaces import LiveState, MetadataProvider
from youtube_live_recorder.services.power import PowerManager
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import from_iso, to_iso, utc_now

LOGGER = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        repository: Repository,
        metadata: MetadataProvider,
        recordings: RecordingManager,
        *,
        jitter=random.uniform,
        power=None,
    ) -> None:
        self.repository, self.metadata, self.recordings = repository, metadata, recordings
        self.jitter = jitter
        self.replays = ReplayWatcher(repository, metadata, recordings)
        self.jobs = ReplayStore(repository)
        self.power = power or PowerManager()

    def tick(self, now: datetime | None = None, *, stop: Event | None = None) -> None:
        now = now or utc_now()
        # 등록 순 정렬은 Repository가 보장한다. 동일 tick에 시작한 방송은 먼저 등록한 건 우선.
        for item in self.repository.list_broadcasts():
            if stop is not None and stop.is_set():
                break
            if item.archive_download or item.status not in {
                B.WAITING,
                B.ERROR_RETRYABLE,
                B.LIVE_DETECTED,
            }:
                continue
            if item.next_check_at and from_iso(item.next_check_at) > now:
                continue
            try:
                metadata = self.metadata.fetch(item.original_url)
                if stop is not None and stop.is_set():
                    break
                self.repository.update_metadata(
                    item.id, metadata, to_iso(now), to_iso(now + timedelta(seconds=POLL_SECONDS))
                )
                # 네트워크 조회 중 UI/다른 CLI에서 취소했을 수 있다.
                item = self.repository.get_broadcast(item.id)
                if item.status not in {B.WAITING, B.ERROR_RETRYABLE, B.LIVE_DETECTED}:
                    continue
                if item.status == B.ERROR_RETRYABLE:
                    self.repository.transition(item.id, B.WAITING)
                if metadata.state == LiveState.LIVE:
                    if item.status != B.LIVE_DETECTED:
                        self.repository.transition(item.id, B.LIVE_DETECTED)
                    try:
                        self.recordings.start(item.id)
                    except AppError as error:
                        if error.code != ErrorCode.RECORDING_LIMIT:
                            raise
                        if self.recordings.preempt_replay():
                            self.repository.set_next_check(item.id, to_iso(now))
                            continue
                        # 상한 초과 방송도 60초마다 확인한다. 종료되면 다시보기로 전환한다.
                        self.repository.note_error(item.id, error.code)
                elif metadata.state in {LiveState.POST_LIVE, LiveState.WAS_LIVE}:
                    self.repository.transition(item.id, B.REPLAY_WAIT)
                    self.jobs.ensure(item.id, "감지 전 방송 종료", now)
            except AppError as error:
                delay = min(600, POLL_SECONDS * 2 ** min(item.poll_failures + 1, 4))
                delay += self.jitter(0, delay * 0.1)
                if error.code == ErrorCode.STREAM_NOT_LIVE:
                    delay = POLL_SECONDS
                self.repository.poll_failed(
                    item.id,
                    error.code,
                    to_iso(now),
                    to_iso(now + timedelta(seconds=delay)),
                    permanent=error.code
                    in {
                        ErrorCode.STREAM_UNAVAILABLE,
                        ErrorCode.DISK_LOW,
                        ErrorCode.WRITE_PERMISSION_DENIED,
                    },
                )
        self.replays.tick(now, stop)

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                pending = self.repository.list_broadcasts()
                self.power.set_required(
                    bool(self.repository.active_session())
                    or any(item.status != B.ERROR for item in pending)
                )
                self.tick(stop=stop)
            except Exception:
                LOGGER.exception("방송 감지 작업 오류")
            stop.wait(1)
        # Engine이 파일 정리 후 같은 스레드에서 절전 방지를 해제한다.
