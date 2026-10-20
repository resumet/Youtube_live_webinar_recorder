import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from youtube_live_recorder import __version__
from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.config import Settings
from youtube_live_recorder.core.archive_downloads import ArchiveDownloads
from youtube_live_recorder.core.engine import Engine
from youtube_live_recorder.data.models import (
    ACTIVE_SESSIONS,
    TERMINAL_BROADCASTS,
    Broadcast,
    BroadcastStatus,
    Quality,
    RecordingSession,
)
from youtube_live_recorder.limits import DEFAULT_CONCURRENT_RECORDINGS, validate_recording_limit
from youtube_live_recorder.services.download_progress import DownloadProgress
from youtube_live_recorder.services.interfaces import BroadcastMetadata
from youtube_live_recorder.services.storage import check_storage
from youtube_live_recorder.services.thumbnails import fetch_thumbnail
from youtube_live_recorder.services.toolchain import Toolchain
from youtube_live_recorder.services.updates import UpdateError, UpdateService
from youtube_live_recorder.services.ytdlp_adapter import YtdlpAdapter
from youtube_live_recorder.utils.errors import AppError
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
    session_bytes: dict[str, int] = field(default_factory=dict)
    max_concurrent_recordings: int = DEFAULT_CONCURRENT_RECORDINGS
    download_progress: dict[str, DownloadProgress] = field(default_factory=dict)

    @property
    def active_sessions(self) -> tuple[RecordingSession, ...]:
        return tuple(s for s in self.sessions if s.status in ACTIVE_SESSIONS)

    def recording_folder(self, session_id: str | None) -> Path:
        session = next((s for s in self.sessions if s.id == session_id), None)
        if session and session.output_path:
            return Path(session.output_path).parent
        if session and session.work_directory:
            return Path(session.work_directory).parent.parent
        return self.save_folder

    @property
    def queue(self) -> tuple[Broadcast, ...]:
        return tuple(item for item in self.broadcasts if item.status not in TERMINAL_BROADCASTS)


class Controller(QObject):
    _refresh_requested = Signal()
    snapshot_ready = Signal(object)
    preview_ready = Signal(int, object, bytes, str)
    operation_done = Signal(str, bool, str)
    engine_state = Signal(str, str)
    shutdown_ready = Signal()
    update_checked = Signal(object, str)
    update_downloaded = Signal(object, str)
    install_ready = Signal(object, str)

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
        self.refresh_dirty = False
        self._refresh_requested.connect(self.refresh, Qt.ConnectionType.QueuedConnection)
        self.closing = threading.Event()
        self.updates = UpdateService(context.paths.root / "updates")

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

    def download_archive(self, url: str, quality: Quality, filename: str, permission: bool) -> None:
        def action():
            provider = self.metadata or YtdlpAdapter(Toolchain.discover())
            ArchiveDownloads(self.repository, provider).register(
                url,
                permission_confirmed=permission,
                quality=quality,
                custom_filename=filename,
            )

        self._operation("archive", action)

    def cancel(self, identifier: str, *, operation: str = "cancel") -> None:
        self._operation(
            operation, lambda: self.repository.transition(identifier, BroadcastStatus.CANCELLED)
        )

    def edit(self, identifier: str, quality: Quality, filename: str) -> None:
        self._operation(
            "edit", lambda: self.repository.edit_broadcast(identifier, quality, filename)
        )

    def retry(self, identifier: str) -> None:
        self._operation("retry", lambda: self.repository.retry_broadcast(identifier))

    def delete_history(self, session_id: str | None = None) -> None:
        self._operation(
            "history_delete" if session_id else "history_clear",
            lambda: self.repository.delete_history(session_id),
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
                        self.repository.set_setting("save_folder", str(folder))
                        engine.recordings.settings = replace(
                            engine.recordings.settings, save_folder=folder
                        )
                else:
                    self.repository.set_setting("save_folder", str(folder))

        self._operation("folder", action)

    def save_concurrency(self, count: int) -> None:
        def action():
            validate_recording_limit(count)
            with self.config_lock:
                engine = self.engine
                if engine:
                    with engine.recordings.lock:
                        self.repository.set_setting("max_concurrent_recordings", count)
                        engine.recordings.settings = replace(
                            engine.recordings.settings, max_concurrent_recordings=count
                        )
                else:
                    self.repository.set_setting("max_concurrent_recordings", count)

        self._operation("concurrency", action)

    def stop_recording(self, session_id: str | None = None) -> None:
        if self.engine:
            self._operation(
                "stop", lambda: self.engine.recordings.stop(expected_session_id=session_id)
            )

    def refresh(self) -> None:
        if self.closing.is_set():
            return
        with self.refresh_lock:
            if self.refresh_pending:
                self.refresh_dirty = True
                return
            self.refresh_pending = True

        def run():
            try:
                broadcasts = tuple(self.repository.list_broadcasts(include_terminal=True))
                sessions = tuple(self.repository.list_sessions())
                active = tuple(s for s in sessions if s.status in ACTIVE_SESSIONS)
                settings = Settings.load(self.repository)
                folder = settings.save_folder
                sizes = {}
                for session in active:
                    sizes[session.id] = 0
                    if session.work_directory:
                        try:
                            sizes[session.id] = sum(
                                path.stat().st_size
                                for path in Path(session.work_directory).rglob("*")
                                if path.is_file()
                            )
                        except OSError:
                            pass
                try:
                    free = shutil.disk_usage(folder if folder.exists() else folder.parent).free
                except OSError:
                    free = None
                self.snapshot_ready.emit(
                    Snapshot(
                        broadcasts,
                        sessions,
                        active[0] if active else None,
                        sum(sizes.values()),
                        free,
                        folder,
                        sizes,
                        settings.max_concurrent_recordings,
                        self.engine.recordings.progress_snapshot() if self.engine else {},
                    )
                )
            except Exception:
                LOGGER.exception("화면 상태 갱신 실패")
            finally:
                with self.refresh_lock:
                    self.refresh_pending = False
                    again, self.refresh_dirty = self.refresh_dirty, False
                if again:
                    self._refresh_requested.emit()

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

    def check_update(self) -> None:
        def run():
            try:
                settings = Settings.load(self.repository)
                release = self.updates.check(settings.update_manifest_url, __version__)
                self.update_checked.emit(release, "")
            except (UpdateError, OSError) as error:
                self.update_checked.emit(None, str(error))

        if not self.closing.is_set():
            self.pool.submit(run)

    def download_update(self, release) -> None:
        def run():
            try:
                path = self.updates.download(release, cancelled=self.closing)
                self.update_downloaded.emit(path, "")
            except (UpdateError, OSError) as error:
                self.update_downloaded.emit(None, str(error))

        if not self.closing.is_set():
            self.pool.submit(run)

    def prepare_install(self, path, release) -> None:
        def run():
            try:
                self.updates.verify_installer(path, release)
                with self.config_lock:
                    if self.engine and not self.engine.recordings.freeze_if_idle():
                        raise UpdateError(
                            "녹화 또는 파일 정리 중에는 업데이트를 설치할 수 없습니다."
                        )
                    if self.repository.active_session():
                        raise UpdateError("미완료 작업을 복구한 뒤 업데이트를 설치해 주세요.")
                self.install_ready.emit(path, "")
            except (UpdateError, OSError) as error:
                self.install_ready.emit(None, str(error))

        if not self.closing.is_set():
            self.pool.submit(run)
