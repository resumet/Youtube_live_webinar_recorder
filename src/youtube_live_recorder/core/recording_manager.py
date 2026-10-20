import logging
import random
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Lock, Thread

from youtube_live_recorder.config import Settings
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import RecordingMode, RecordingSession
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.data.replays import ReplayStore
from youtube_live_recorder.data.repository import Repository
from youtube_live_recorder.limits import MAX_CONCURRENT_RECORDINGS
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
from youtube_live_recorder.utils.time import from_iso, utc_now

LOGGER = logging.getLogger(__name__)
RETRYABLE = {ErrorCode.NETWORK_DISCONNECTED, ErrorCode.RATE_LIMITED}


@dataclass
class RecordingTask:
    session: RecordingSession
    settings: Settings
    stop: Event = field(default_factory=Event)
    reason: str = ""
    future: Future | None = None

    def request_stop(self, reason: str):
        if not self.stop.is_set():
            self.reason = reason
            self.stop.set()


class RecordingManager:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        metadata: MetadataProvider,
        backend: CaptureBackend,
        finalizer: FFmpegAdapter,
        *,
        retry_wait=None,
        jitter=random.uniform,
        storage_check=check_storage,
        disk_interval: float = 5,
        confirmation_seconds: float = 1,
    ) -> None:
        self.repository, self.settings, self.metadata = repository, settings, metadata
        self.backend, self.finalizer = backend, finalizer
        self.replays = ReplayStore(repository)
        self.pool = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_RECORDINGS, thread_name_prefix="recorder"
        )
        self.tasks: dict[str, RecordingTask] = {}
        # 단일 작업을 실행하는 진단 도구의 마지막 작업 핸들.
        self.future: Future | None = None
        self.lock = Lock()
        self.accepting = True
        self.retry_wait = retry_wait or (lambda stop, delay: stop.wait(delay))
        self.jitter, self.storage_check = jitter, storage_check
        self.disk_interval, self.confirmation_seconds = disk_interval, confirmation_seconds

    def start(
        self, broadcast_id: str, mode: RecordingMode = RecordingMode.LIVE
    ) -> RecordingSession:
        with self.lock:
            if not self.accepting:
                raise AppError(ErrorCode.INVALID_STATE)
            self.storage_check(self.settings.save_folder, self.settings.min_free_bytes, create=True)
            self.tasks = {
                key: task
                for key, task in self.tasks.items()
                if task.future is None or not task.future.done()
            }
            session = self.repository.claim_session(
                broadcast_id,
                mode,
                max_concurrent=self.settings.max_concurrent_recordings,
                save_folder=self.settings.save_folder,
            )
            task = RecordingTask(session, self.settings)
            self.tasks[session.id] = task
            try:
                task.future = self.pool.submit(self._record, task)
                self.future = task.future
            except RuntimeError:
                self.tasks.pop(session.id, None)
                self.repository.finish_session(
                    session.id, S.FAILED, B.ERROR, reason="녹화 작업을 시작할 수 없습니다."
                )
                raise
            return session

    def stop(self, reason: str = "user", *, expected_session_id: str | None = None) -> None:
        with self.lock:
            for identifier, task in self.tasks.items():
                if expected_session_id is None or identifier == expected_session_id:
                    task.request_stop(reason)

    def preempt_replay(self) -> bool:
        with self.lock:
            for active in self.repository.active_sessions():
                if (
                    active.mode == RecordingMode.REPLAY
                    and active.id in self.tasks
                    and not self.repository.get_broadcast(active.broadcast_id).archive_download
                ):
                    self.tasks[active.id].request_stop("preempted")
                    return True
            return False

    def shutdown(self) -> None:
        self.stop_accepting()
        self.pool.shutdown(wait=True)

    def stop_accepting(self) -> None:
        with self.lock:
            self.accepting = False
            for task in self.tasks.values():
                task.request_stop("shutdown")

    def freeze_if_idle(self) -> bool:
        """설치 준비와 새 슬롯 획득의 경쟁을 막는다. 실행 중 녹화는 중단하지 않는다."""
        with self.lock:
            if self.repository.active_session() is not None:
                return False
            self.accepting = False
            return True

    def _disk_watch(self, task: RecordingTask, done: Event) -> None:
        while not done.wait(self.disk_interval):
            try:
                self.storage_check(task.settings.save_folder, task.settings.min_free_bytes)
            except AppError as error:
                with self.lock:
                    task.request_stop(error.code)
                return

    def _ended(self, url: str, stop: Event) -> bool:
        for attempt in range(2):
            if stop.is_set() or (attempt and stop.wait(self.confirmation_seconds)):
                return False
            if self.metadata.fetch(url).state not in {LiveState.WAS_LIVE, LiveState.POST_LIVE}:
                return False
        return True

    def _record(self, task: RecordingTask) -> None:
        session, stop, settings = task.session, task.stop, task.settings
        item = self.repository.get_broadcast(session.broadcast_id)
        work = settings.save_folder / ".ylr-work" / session.id
        resumed = session.mode == RecordingMode.LIVE and any(
            old.id != session.id
            and old.broadcast_id == session.broadcast_id
            and old.mode == RecordingMode.LIVE
            for old in self.repository.list_sessions()
        )
        from_start = session.mode == RecordingMode.LIVE and not resumed
        done = Event()
        monitor = Thread(target=self._disk_watch, args=(task, done), name="disk-watch", daemon=True)
        saved = []
        reason, last_error = "", None
        ended, gap, failed_piece, user_stopped = False, resumed, False, False
        retry, index = 0, 0
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
        filename_note = ""
        if not item.actual_start_at and not item.custom_filename.strip():
            basis = (
                "예정 시각"
                if item.scheduled_start_at
                else "첫 방송 감지 시각"
                if item.first_detected_at
                else "녹화 시작 시각"
            )
            filename_note = f" 파일명 날짜는 {basis} 기준 추정값입니다."
        try:
            self.repository.set_session_state(
                session.id,
                S.RUNNING,
                work_directory=str(work),
                from_start=from_start,
                note=(
                    "이전 녹화 중단 이후 구간입니다. 기존 부분 파일은 유지됩니다."
                    if resumed
                    else "처음부터 저장 요청 · 전체 구간 확보는 보장하지 않습니다."
                    if from_start
                    else "다시보기 다운로드"
                )
                + filename_note,
            )
            monitor.start()
            while True:
                segment_work = work / f"segment-{index:04d}"
                segment = self.repository.add_segment(session.id, index, str(segment_work))
                result = self.backend.capture(
                    CaptureRequest(
                        item.original_url,
                        item.preferred_quality,
                        segment_work,
                        from_start,
                        lambda height: self.repository.record_actual_quality(session.id, height),
                    ),
                    stop,
                )
                last_error = result.error_code
                user_stopped = result.stopped_by_user
                fallback = (
                    from_start
                    and not stop.is_set()
                    and last_error in {ErrorCode.DVR_UNAVAILABLE, ErrorCode.FORMAT_UNAVAILABLE}
                    and not any(p.exists() and p.stat().st_size for p in result.files)
                )
                if fallback:
                    self.repository.finish_segment(segment, None, "DVR 시작 구간 사용 불가")
                    from_start, gap, index = False, True, index + 1
                    continue
                if not stop.is_set() and not user_stopped:
                    try:
                        ended = session.mode == RecordingMode.REPLAY and result.return_code == 0
                        if session.mode == RecordingMode.LIVE:
                            ended = self._ended(item.original_url, stop)
                    except AppError as error:
                        last_error = error.code
                        ended = False
                    if not ended and result.return_code == 0 and not last_error:
                        last_error = ErrorCode.NETWORK_DISCONNECTED
                can_retry = (
                    not stop.is_set()
                    and not user_stopped
                    and not ended
                    and last_error in RETRYABLE
                    and retry < settings.max_reconnect_attempts
                )
                self.repository.set_session_state(
                    session.id, S.RECONNECTING if can_retry else S.FINALIZING
                )
                self.repository.transition(item.id, B.RECONNECTING if can_retry else B.FINALIZING)
                last_valid = False
                try:
                    part_name = name if index == 0 else f"{Path(name).stem}_구간{index + 1:02d}.mp4"
                    inspection = self.finalizer.finalize(
                        result.files, settings.save_folder, part_name
                    )
                    saved.append(inspection)
                    last_valid = True
                    self.repository.finish_segment(segment, inspection)
                except AppError as error:
                    failed_piece = True
                    self.repository.finish_segment(segment, None, str(error))
                    reason = str(error)
                    if error.code in {ErrorCode.DISK_LOW, ErrorCode.WRITE_PERMISSION_DENIED}:
                        last_error = error.code
                        can_retry = False
                    LOGGER.warning("세그먼트 정리 실패: %s", error.code)
                if not can_retry:
                    if self.repository.get_session(session.id).status == S.RECONNECTING:
                        self.repository.set_session_state(session.id, S.FINALIZING)
                        self.repository.transition(item.id, B.FINALIZING)
                    break
                gap = True
                self.repository.note_coverage(
                    session.id,
                    "연결이 끊긴 구간이 있습니다. 재개 구간은 별도 파일로 보존합니다."
                    + filename_note,
                )
                delay = min(600, 15 * 2**retry)
                delay += self.jitter(0, delay * 0.1)
                if self.retry_wait(stop, delay) or stop.is_set():
                    self.repository.set_session_state(session.id, S.FINALIZING)
                    self.repository.transition(item.id, B.FINALIZING)
                    break
                self.storage_check(settings.save_folder, settings.min_free_bytes)
                retry, index = retry + 1, index + 1
                from_start = False
                self.repository.set_session_state(session.id, S.RUNNING)
                self.repository.transition(
                    item.id,
                    B.RECORDING if session.mode == RecordingMode.LIVE else B.REPLAY_DOWNLOADING,
                )
            self.repository.set_session_state(session.id, S.VERIFYING)
            self.repository.transition(item.id, B.VERIFYING)
            manual = (stop.is_set() or user_stopped) and task.reason in {"", "user"}
            if manual:
                target, reason = B.CANCELLED, "사용자가 중지한 부분 녹화입니다."
            elif task.reason in {ErrorCode.DISK_LOW, ErrorCode.WRITE_PERMISSION_DENIED}:
                target, reason = B.ERROR, str(AppError(task.reason))
                last_error = task.reason
            elif task.reason == "shutdown":
                target, reason = (
                    B.ERROR_RETRYABLE,
                    "프로그램 종료로 중단했습니다. 다음 실행에서 상태를 재확인합니다.",
                )
            elif task.reason == "preempted":
                target, reason = (
                    B.REPLAY_WAIT,
                    "라이브 녹화를 우선해 다시보기를 대기 상태로 돌렸습니다.",
                )
            elif (
                session.mode == RecordingMode.REPLAY
                and ended
                and result.return_code == 0
                and last_valid
            ):
                target = B.COMPLETED
            elif ended and result.return_code == 0 and not gap and not failed_piece and saved:
                target = B.COMPLETED
            elif last_error in {
                ErrorCode.STREAM_UNAVAILABLE,
                ErrorCode.FORMAT_UNAVAILABLE,
                ErrorCode.DISK_LOW,
                ErrorCode.WRITE_PERMISSION_DENIED,
            }:
                target, reason = B.ERROR, str(AppError(last_error))
            else:
                target = B.REPLAY_WAIT
                reason = (
                    reason
                    or "연결 중단 또는 구간 누락으로 부분 저장했습니다. 다시보기를 확인합니다."
                )
            final_files = (
                saved[-1:]
                if target == B.COMPLETED and session.mode == RecordingMode.REPLAY
                else saved
            )
            self._finish(session, target, final_files, reason)
            if last_error and target != B.COMPLETED:
                self.repository.note_error(item.id, last_error)
            if target in {B.REPLAY_WAIT, B.ERROR_RETRYABLE, B.ERROR}:
                self.replays.ensure(item.id, reason)
                if ended:
                    self.replays.checked(item.id, utc_now(), ended=True)
                self.replays.defer(item.id, utc_now())
        except Exception as error:
            LOGGER.exception("녹화 세션 처리 실패")
            current = self.repository.get_session(session.id)
            if current.status in {S.COMPLETE, S.PARTIAL, S.FAILED, S.CANCELLED}:
                return
            if current.status == S.RUNNING:
                self.repository.set_session_state(session.id, S.FINALIZING)
            target = (
                B.ERROR
                if isinstance(error, AppError) and error.code not in RETRYABLE
                else B.REPLAY_WAIT
            )
            reason = (
                str(error)
                if isinstance(error, AppError)
                else "녹화 처리 중 오류가 발생했습니다. 임시 파일은 보존됩니다."
            )
            self._finish(session, target, saved, reason)
            self.replays.ensure(item.id, reason)
            self.replays.defer(item.id, utc_now())
            if isinstance(error, AppError):
                self.repository.note_error(item.id, error.code)
        finally:
            done.set()
            if monitor.ident is not None:
                monitor.join(timeout=2)

    def _finish(self, session, target, saved, reason):
        # 복수 조각은 이어 붙이지 않는다. 대표 경로와 합산 길이/용량을 기록한다.
        inspection = (
            replace(
                saved[0],
                duration_seconds=sum(p.duration_seconds for p in saved),
                size_bytes=sum(p.size_bytes for p in saved),
            )
            if saved
            else None
        )
        if len(saved) > 1:
            reason = (
                f"{len(saved)}개 부분 파일을 저장했습니다. 폴더에서 각 구간을 확인하세요. " + reason
            )
        status = S.COMPLETE if target == B.COMPLETED else S.PARTIAL if saved else S.FAILED
        self.repository.finish_session(session.id, status, target, inspection, reason)
