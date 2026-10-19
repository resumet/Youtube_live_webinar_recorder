import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.engine import Engine
from youtube_live_recorder.data.models import (
    ACTIVE_SESSIONS,
    TERMINAL_BROADCASTS,
    Broadcast,
    BroadcastStatus,
    Quality,
    RecordingSession,
)
from youtube_live_recorder.services.interfaces import BroadcastMetadata
from youtube_live_recorder.services.storage import check_storage
from youtube_live_recorder.services.thumbnails import fetch_thumbnail
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.errors import AppError, ErrorCode
from youtube_live_recorder.utils.time import to_iso, utc_now

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    broadcasts: tuple[Broadcast, ...]
    sessions: tuple[RecordingSession, ...]
    active: RecordingSession | None
    bytes_written: int
    free_bytes: int | None
    save_folder: Path

    @property
    def queue(self) -> tuple[Broadcast, ...]:
        return tuple(item for item in self.broadcasts if item.status not in TERMINAL_BROADCASTS)


class Controller(QObject):
    snapshot_ready = Signal(object)
    preview_ready = Signal(int, object, bytes, str)
    operation_done = Signal(str, bool, str)
    engine_state = Signal(str, str)
    shutdown_ready = Signal()

    def __init__(self, context: ApplicationContext, *, engine_factory=Engine, metadata=None):
        super().__init__()
        self.context = context
        self.repository = context.repository
        self.engine_factory = engine_factory
        self.metadata = metadata
        self.engine = None
        self.engine_future = None
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop")
        self.config_lock = threading.Lock()
        self.refresh_lock = threading.Lock()
        self.refresh_pending = False
        self.closing = threading.Event()

    def start(self) -> None:
        if self.engine_future is not None or self.closing.is_set():
            return

        def run():
            failed = False
            try:
                with self.config_lock:
                    context = replace(self.context, settings=Settings.load(self.repository))
                    self.engine = self.engine_factory(context)
                if self.closing.is_set():
                    self.engine.stop()
                self.engine_state.emit("running", "방송을 자동으로 확인하고 있습니다.")
                self.engine.run()
            except Exception as error:
                failed = True
                LOGGER.exception("녹화 엔진 시작 또는 실행 실패")
                self.engine_state.emit(
                    "error",
                    str(error)
                    if isinstance(error, (AppError, RuntimeError))
                    else "녹화 서비스를 시작할 수 없습니다. 로그를 확인해 주세요.",
                )
            finally:
                if not failed and not self.closing.is_set():
                    self.engine_state.emit("stopped", "자동 감지가 중지되었습니다.")

        self.engine_future = self.pool.submit(run)

    def _operation(self, name, action):
        if self.closing.is_set():
            return

        def run():
            try:
                action()
                self.operation_done.emit(name, True, "")
            except Exception as error:
                LOGGER.exception("화면 요청 처리 실패: %s", name)
                message = (
                    str(error)
                    if isinstance(error, (AppError, ValueError, RuntimeError))
                    else "작업을 처리하지 못했습니다. 로그를 확인해 주세요."
                )
                self.operation_done.emit(name, False, message)

        self.pool.submit(run)

    def preview(self, token: int, url: str) -> None:
        def run():
            metadata = None
            image = b""
            error_text = ""
            try:
                provider = self.metadata or YtdlpAdapter(Toolchain.discover())
                metadata = provider.fetch(url)
                try:
                    image = fetch_thumbnail(metadata.thumbnail_url)
                except OSError:
                    LOGGER.info("썸네일을 불러올 수 없습니다.")
            except Exception as error:
                LOGGER.exception("등록 미리보기 조회 실패")
                error_text = (
                    str(error)
                    if isinstance(error, AppError)
                    else "방송 정보를 불러오지 못했습니다. URL만 등록할 수 있습니다."
                )
            self.preview_ready.emit(token, metadata, image, error_text)

        if not self.closing.is_set():
            self.pool.submit(run)

    def add(
        self,
        url: str,
        quality: Quality,
        filename: str,
        permission: bool,
        metadata: BroadcastMetadata | None = None,
    ) -> None:
        def action():
            item = self.repository.add_broadcast(
                url, permission_confirmed=permission, quality=quality, custom_filename=filename
            )
            if metadata and metadata.video_id == item.video_id:
                now = to_iso(utc_now())
                self.repository.update_metadata(item.id, metadata, now, now)

        self._operation("add", action)

    def cancel(self, identifier: str) -> None:
        self._operation(
            "cancel", lambda: self.repository.transition(identifier, BroadcastStatus.CANCELLED)
        )

    def edit(self, identifier: str, quality: Quality, filename: str) -> None:
        self._operation(
            "edit", lambda: self.repository.edit_broadcast(identifier, quality, filename)
        )

    def save_folder(self, folder: Path) -> None:
        def action():
            if not folder.is_absolute():
                raise ValueError("절대 경로로 저장 폴더를 선택해 주세요.")
            check_storage(folder, self.context.settings.min_free_bytes, create=True)
            with self.config_lock:
                engine = self.engine
                if engine:
                    with engine.recordings.lock:
                        if self.repository.active_session():
                            raise AppError(
                                ErrorCode.INVALID_STATE, "녹화 중에는 저장 위치를 바꿀 수 없습니다."
                            )
                        self.repository.set_setting("save_folder", str(folder))
                        engine.recordings.settings = Settings.load(self.repository)
                else:
                    self.repository.set_setting("save_folder", str(folder))

        self._operation("folder", action)

    def stop_recording(self) -> None:
        if self.engine:
            self.engine.recordings.stop()

    def refresh(self) -> None:
        if self.closing.is_set():
            return
        with self.refresh_lock:
            if self.refresh_pending:
                return
            self.refresh_pending = True

        def run():
            try:
                broadcasts = tuple(self.repository.list_broadcasts(include_terminal=True))
                sessions = tuple(self.repository.list_sessions())
                active = next((s for s in sessions if s.status in ACTIVE_SESSIONS), None)
                folder = Settings.load(self.repository).save_folder
                size = 0
                if active and active.work_directory:
                    try:
                        size = sum(
                            path.stat().st_size
                            for path in Path(active.work_directory).rglob("*")
                            if path.is_file()
                        )
                    except OSError:
                        pass
                try:
                    free = shutil.disk_usage(folder if folder.exists() else folder.parent).free
                except OSError:
                    free = None
                self.snapshot_ready.emit(Snapshot(broadcasts, sessions, active, size, free, folder))
            except Exception:
                LOGGER.exception("화면 상태 갱신 실패")
            finally:
                with self.refresh_lock:
                    self.refresh_pending = False

        self.pool.submit(run)

    def close_async(self) -> None:
        if self.closing.is_set():
            return
        self.closing.set()

        def shutdown():
            if self.engine:
                self.engine.stop()
            if self.engine_future:
                self.engine_future.result()
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.shutdown_ready.emit()

        threading.Thread(target=shutdown, name="desktop-shutdown", daemon=True).start()
