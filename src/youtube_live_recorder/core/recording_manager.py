import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock

from youtube_live_recorder.config import Settings
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import RecordingMode, RecordingSession
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.services.ffmpeg_adapter import FFmpegAdapter
from youtube_live_recorder.services.interfaces import (
    CaptureBackend,
    CaptureRequest,
    LiveState,
    MetadataProvider,
)
from youtube_live_recorder.services.storage import check_storage
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.filenames import recording_name
from youtube_live_recorder.utils.time import from_iso

LOGGER = logging.getLogger(__name__)


class RecordingManager:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        metadata: MetadataProvider,
        backend: CaptureBackend,
        finalizer: FFmpegAdapter,
    ) -> None:
        self.repository, self.settings, self.metadata = repository, settings, metadata
        self.backend, self.finalizer = backend, finalizer
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recorder")
        self.stop_event = Event()
        self.future: Future | None = None
        self.lock = Lock()

    def start(
        self, broadcast_id: str, mode: RecordingMode = RecordingMode.LIVE
    ) -> RecordingSession:
        with self.lock:
            check_storage(self.settings.save_folder, self.settings.min_free_bytes, create=True)
            session = self.repository.claim_session(broadcast_id, mode)
            self.stop_event = Event()
            try:
                self.future = self.pool.submit(self._record, session, self.stop_event)
            except RuntimeError:
                self.repository.finish_session(
                    session.id, S.FAILED, B.ERROR, reason="녹화 작업을 시작할 수 없습니다."
                )
                raise
            return session

    def stop(self) -> None:
        self.stop_event.set()

    def shutdown(self) -> None:
        self.stop()
        self.pool.shutdown(wait=True)

    def _record(self, session: RecordingSession, stop: Event) -> None:
        item = self.repository.get_broadcast(session.broadcast_id)
        work = self.settings.save_folder / ".ylr-work" / session.id
        from_start = session.mode == RecordingMode.LIVE
        self.repository.set_session_state(
            session.id,
            S.RUNNING,
            work_directory=str(work),
            from_start=from_start,
            note="처음부터 저장 요청 · 전체 구간 확보는 보장하지 않습니다."
            if from_start
            else "다시보기 다운로드",
        )
        segment = self.repository.add_segment(session.id, 0, str(work))
        inspection = None
        try:
            result = self.backend.capture(
                CaptureRequest(item.original_url, item.preferred_quality, work, from_start), stop
            )
            edge_fallback = False
            if (
                from_start
                and not stop.is_set()
                and result.error_code in {ErrorCode.DVR_UNAVAILABLE, ErrorCode.FORMAT_UNAVAILABLE}
                and not any(path.exists() and path.stat().st_size for path in result.files)
            ):
                self.repository.finish_segment(segment, None)
                edge_work = work / "live-edge"
                segment = self.repository.add_segment(session.id, 1, str(edge_work))
                result = self.backend.capture(
                    CaptureRequest(item.original_url, item.preferred_quality, edge_work, False),
                    stop,
                )
                edge_fallback = True
            self.repository.set_session_state(session.id, S.FINALIZING)
            self.repository.transition(item.id, B.FINALIZING)
            timestamp = (
                item.actual_start_at
                or item.scheduled_start_at
                or item.first_detected_at
                or session.started_at
            )
            name = recording_name(
                item.title or "방송",
                from_iso(timestamp),
                item.custom_filename,
                replay=session.mode == RecordingMode.REPLAY,
            )
            inspection = self.finalizer.finalize(result.files, self.settings.save_folder, name)
            self.repository.finish_segment(segment, inspection)
            self.repository.set_session_state(session.id, S.VERIFYING)
            self.repository.transition(item.id, B.VERIFYING)
            if result.stopped_by_user or stop.is_set():
                self.repository.finish_session(
                    session.id,
                    S.PARTIAL,
                    B.CANCELLED,
                    inspection,
                    "사용자가 중지한 부분 녹화입니다.",
                )
                return
            ended = session.mode == RecordingMode.REPLAY
            if not ended and result.return_code == 0:
                # 프로세스 종료만으로 방송 종료를 추정하지 않는다. 두 번 명시적 상태를 확인한다.
                checks = []
                for attempt in range(2):
                    if attempt and stop.wait(1):
                        break
                    checks.append(self.metadata.fetch(item.original_url).state)
                ended = len(checks) == 2 and all(
                    s in {LiveState.WAS_LIVE, LiveState.POST_LIVE} for s in checks
                )
            if result.return_code == 0 and ended and not edge_fallback:
                self.repository.finish_session(session.id, S.COMPLETE, B.COMPLETED, inspection)
            elif ended and edge_fallback:
                self.repository.finish_session(
                    session.id,
                    S.PARTIAL,
                    B.REPLAY_WAIT,
                    inspection,
                    "현재 시점부터 저장해 방송 앞부분이 누락될 수 있습니다.",
                )
            else:
                self.repository.finish_session(
                    session.id,
                    S.PARTIAL,
                    B.ERROR_RETRYABLE,
                    inspection,
                    "방송 종료 또는 전체 녹화를 확인하지 못했습니다.",
                )
        except Exception as error:
            LOGGER.exception("녹화 세션 처리 실패")
            current = self.repository.get_session(session.id)
            if current.status in {S.COMPLETE, S.PARTIAL, S.FAILED, S.CANCELLED}:
                return
            target = (
                S.PARTIAL
                if inspection and inspection.valid and current.status != S.RUNNING
                else S.FAILED
            )
            self.repository.finish_segment(segment, inspection)
            self.repository.finish_session(
                session.id,
                target,
                B.ERROR
                if isinstance(error, AppError)
                and error.code in {"DISK_LOW", "WRITE_PERMISSION_DENIED", "STREAM_UNAVAILABLE"}
                else B.ERROR_RETRYABLE,
                inspection,
                str(error)
                if isinstance(error, AppError)
                else "녹화 처리 중 오류가 발생했습니다. 임시 파일은 보존됩니다.",
            )
