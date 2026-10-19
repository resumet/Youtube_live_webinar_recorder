import ctypes
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from youtube_live_recorder.data.models import BroadcastStatus, Quality
from youtube_live_recorder.ui.controller import Controller, Snapshot
from youtube_live_recorder.ui.dashboard import Dashboard
from youtube_live_recorder.ui.dialogs import EditDialog, confirm
from youtube_live_recorder.ui.formatting import duration
from youtube_live_recorder.ui.history_page import HistoryPage
from youtube_live_recorder.ui.notifications import NotificationTracker
from youtube_live_recorder.ui.queue_page import QueuePage
from youtube_live_recorder.ui.settings_page import SettingsPage
from youtube_live_recorder.ui.theme import STYLE, ensure_system_font, status_icon
from youtube_live_recorder.ui.widgets import label
from youtube_live_recorder.utils.errors import MESSAGES, AppError
from youtube_live_recorder.utils.time import from_iso, utc_now
from youtube_live_recorder.utils.urls import parse_video_url


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller, *, auto_start: bool = True):
        super().__init__()
        ensure_system_font()
        self.controller = controller
        self.setWindowTitle("YouTube Live Recorder")
        self.setWindowIcon(status_icon())
        self.resize(1240, 860)
        self.setMinimumSize(720, 420)
        self._watched_screen = None
        self._screen_signal_connected = False
        self.setStyleSheet(STYLE)
        self.snapshot: Snapshot | None = None
        self.engine_running = False
        self.preview_token = 0
        self.preview_metadata = None
        self.stop_pending = False
        self.quitting = False
        self.allow_close = False
        self.last_notification_folder = None
        self.last_notification_page = None
        self.tracker = NotificationTracker()
        self.seen_errors = {}
        self.release = None
        self.update_path = None
        self.install_path = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(18, 30, 18, 24)
        navigation.setSpacing(10)
        navigation.addWidget(label("YouTube Live\nRecorder", "brand"))
        navigation.addSpacing(28)
        group = QButtonGroup(self)
        self.nav_buttons = []
        titles = ("대시보드", "녹화 대기", "녹화 기록", "설정")
        for index, title in enumerate(titles):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.select_page(i))
            group.addButton(button)
            navigation.addWidget(button)
            self.nav_buttons.append(button)
        navigation.addStretch()
        navigation.addWidget(
            label("창을 닫아도 트레이에서\n방송 감지를 계속합니다.", "sidebarNote", wrap=True)
        )
        exit_button = QPushButton("완전 종료")
        exit_button.setObjectName("nav")
        exit_button.clicked.connect(self.request_quit)
        navigation.addWidget(exit_button)
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFixedWidth(210)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.setWidget(sidebar)
        root.addWidget(self.sidebar_scroll)

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 26, 30, 24)
        content_layout.setSpacing(14)
        self.page_title = label("대시보드", "pageTitle")
        content_layout.addWidget(self.page_title)
        self.subtitle = label(
            "방송 URL을 등록하면 라이브 시작을 자동으로 확인합니다.", "subtitle", wrap=True
        )
        content_layout.addWidget(self.subtitle)
        self.banner = label("녹화 서비스를 준비하고 있습니다.", "banner", wrap=True)
        content_layout.addWidget(self.banner)
        self.stack = QStackedWidget()
        self.dashboard = Dashboard()
        self.queue = QueuePage()
        self.history = HistoryPage()
        self.settings = SettingsPage()
        for page in (self.dashboard, self.queue, self.history, self.settings):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)
        self.select_page(0)

        self.tray = QSystemTrayIcon(status_icon(), self)
        menu = QMenu(self)
        show_action = QAction("프로그램 열기", self)
        show_action.triggered.connect(self.restore_window)
        menu.addAction(show_action)
        menu.addSeparator()
        exit_action = QAction("완전 종료", self)
        exit_action.triggered.connect(self.request_quit)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.messageClicked.connect(self.notification_clicked)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self.dashboard.preview_requested.connect(self.preview)
        self.dashboard.url_changed.connect(self.invalidate_preview)
        self.dashboard.add_requested.connect(self.add_broadcast)
        self.dashboard.stop_requested.connect(self.stop_recording)
        self.queue.edit_requested.connect(self.edit_broadcast)
        self.queue.cancel_requested.connect(self.cancel_broadcast)
        self.queue.retry_requested.connect(self.controller.retry)
        self.history.open_requested.connect(self.open_recording)
        self.settings.folder_requested.connect(self.controller.save_folder)
        self.settings.logs_requested.connect(
            lambda: self.open_folder(self.controller.context.paths.logs)
        )
        self.settings.update_requested.connect(self.check_update)
        self.settings.update_action_requested.connect(self.update_action)
        self.controller.update_checked.connect(self.on_update_checked)
        self.controller.update_downloaded.connect(self.on_update_downloaded)
        self.controller.install_ready.connect(self.on_install_ready)
        self.controller.snapshot_ready.connect(self.on_snapshot)
        self.controller.preview_ready.connect(self.on_preview)
        self.controller.operation_done.connect(self.on_operation)
        self.controller.engine_state.connect(self.on_engine_state)
        self.controller.shutdown_ready.connect(self.finish_quit)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.controller.refresh)
        if auto_start:
            self.controller.refresh()
            self.controller.start()
            self.timer.start()
            if self.controller.context.settings.update_manifest_url:
                QTimer.singleShot(10000, self.check_update)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._screen_signal_connected and self.windowHandle():
            self.windowHandle().screenChanged.connect(self._watch_screen)
            self._screen_signal_connected = True
        self._watch_screen(self.screen())

    def _watch_screen(self, screen):
        if screen is not self._watched_screen:
            if self._watched_screen:
                self._watched_screen.availableGeometryChanged.disconnect(self._schedule_screen_fit)
            self._watched_screen = screen
            if screen:
                screen.availableGeometryChanged.connect(self._schedule_screen_fit)
        self._schedule_screen_fit()

    def _schedule_screen_fit(self, *_):
        QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self):
        if not self.isVisible() or self.isMaximized() or self.isMinimized() or not self.screen():
            return
        available = self.screen().availableGeometry()
        frame = self.frameGeometry()
        width = max(1, available.width() - (frame.width() - self.width()) - 24)
        height = max(1, available.height() - (frame.height() - self.height()) - 24)
        self.setMinimumSize(min(720, width), min(420, height))
        self.resize(min(self.width(), width), min(self.height(), height))
        frame = self.frameGeometry()
        self.move(
            max(available.left() + 12, min(frame.left(), available.right() - frame.width() - 11)),
            max(available.top() + 12, min(frame.top(), available.bottom() - frame.height() - 11)),
        )

    def select_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(("대시보드", "녹화 대기", "녹화 기록", "설정")[index])

    def show_message(self, text: str, *, error: bool = False):
        self.banner.setText(text)
        self.banner.setStyleSheet("background: #fff0da; color: #895216;" if error else "")

    @Slot()
    def invalidate_preview(self):
        self.preview_token += 1
        self.preview_metadata = None
        self.dashboard.preview_button.setEnabled(True)
        self.dashboard.preview_button.setText("방송 정보 조회")

    @Slot(str)
    def preview(self, url: str):
        try:
            parse_video_url(url)
        except AppError as error:
            self.show_message(str(error), error=True)
            return
        self.preview_token += 1
        self.dashboard.preview_button.setEnabled(False)
        self.dashboard.preview_button.setText("조회 중…")
        self.controller.preview(self.preview_token, url)

    @Slot(int, object, bytes, str)
    def on_preview(self, token, metadata, image, error):
        if token != self.preview_token or self.quitting:
            return
        self.preview_metadata = metadata
        self.dashboard.show_preview(metadata, image, error)

    @Slot(str, object, str, bool)
    def add_broadcast(self, url, quality, filename, permission):
        try:
            parse_video_url(url)
            if not permission:
                self.show_message("녹화하고 저장할 권한을 먼저 확인해 주세요.", error=True)
                return
        except AppError as error:
            self.show_message(str(error), error=True)
            return
        self.dashboard.add_button.setEnabled(False)
        self.controller.add(url, Quality(quality), filename, permission, self.preview_metadata)

    @Slot(str, bool, str)
    def on_operation(self, name, success, message):
        if self.quitting:
            return
        if name == "add":
            self.dashboard.add_button.setEnabled(True)
            if success:
                self.dashboard.url.clear()
                self.dashboard.filename.clear()
                self.dashboard.permission.setChecked(False)
        messages = {
            "add": "방송을 대기 목록에 등록했습니다.",
            "cancel": "방송 대기를 취소했습니다.",
            "edit": "방송 설정을 변경했습니다.",
            "folder": "저장 폴더를 변경했습니다.",
            "retry": "방송 상태를 다시 확인합니다.",
            "stop": "녹화 중지를 요청했습니다. 파일을 정리하고 있습니다.",
        }
        self.show_message(
            messages.get(name, "작업을 완료했습니다.") if success else message, error=not success
        )
        self.controller.refresh()

    @Slot(str, str)
    def on_engine_state(self, state, message):
        self.engine_running = state == "running"
        if not self.quitting:
            self.show_message(message, error=not self.engine_running)

    @Slot(object)
    def on_snapshot(self, snapshot: Snapshot):
        if self.quitting:
            return
        self.snapshot = snapshot
        if not snapshot.active:
            self.stop_pending = False
        self.dashboard.update_snapshot(snapshot, self.engine_running, self.stop_pending)
        self.queue.update_items(snapshot.queue)
        self.history.update_snapshot(snapshot)
        self.settings.folder.setText(str(snapshot.save_folder))
        self.settings.choose.setEnabled(snapshot.active is None)
        errors = any(
            item.status
            in {BroadcastStatus.ERROR, BroadcastStatus.ERROR_RETRYABLE, BroadcastStatus.INTERRUPTED}
            for item in snapshot.queue
        )
        color = (
            "#d94848"
            if snapshot.active and self.engine_running
            else "#d59c34"
            if errors or not self.engine_running
            else "#3baf77"
        )
        self.tray.setIcon(status_icon(color))
        tooltip = (
            "녹화 중"
            if snapshot.active and self.engine_running
            else "방송 대기"
            if self.engine_running
            else "오류 확인 필요"
        )
        if snapshot.active:
            tooltip += " · " + duration(
                (utc_now() - from_iso(snapshot.active.started_at)).total_seconds()
            )
        self.tray.setToolTip(f"YouTube Live Recorder · {tooltip}")
        for item in snapshot.queue:
            code = item.last_error_code if item.status == BroadcastStatus.ERROR else None
            if code and self.seen_errors.get(item.id) != code:
                message = MESSAGES.get(code, "방송 상태를 확인해 주세요.")
                self.show_message(message, error=True)
                self.last_notification_folder = None
                self.last_notification_page = 1
                self.tray.showMessage(
                    "녹화 확인이 필요합니다", message, QSystemTrayIcon.MessageIcon.Warning, 5000
                )
            self.seen_errors[item.id] = code
        for notice in self.tracker.update(snapshot.sessions):
            self.last_notification_folder = notice.folder
            self.last_notification_page = None
            self.tray.showMessage(
                notice.title, notice.text, QSystemTrayIcon.MessageIcon.Information, 5000
            )

    def selected_broadcast(self, identifier: str):
        item = (
            next((b for b in self.snapshot.queue if b.id == identifier), None)
            if self.snapshot
            else None
        )
        if not item:
            self.show_message("대기 목록에서 방송을 선택해 주세요.", error=True)
        return item

    @Slot(str)
    def edit_broadcast(self, identifier):
        item = self.selected_broadcast(identifier)
        if not item:
            return
        if self.snapshot.active and self.snapshot.active.broadcast_id == identifier:
            self.show_message("녹화 중인 방송은 중지한 뒤 수정해 주세요.", error=True)
            return
        dialog = EditDialog(item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.edit(
                identifier, Quality(dialog.quality.currentData()), dialog.filename.text()
            )

    @Slot(str)
    def cancel_broadcast(self, identifier):
        if not self.selected_broadcast(identifier):
            return
        if confirm(self, "방송 대기 취소", "선택한 방송의 자동 감지를 취소할까요?", "대기 취소"):
            self.controller.cancel(identifier)

    @Slot()
    def stop_recording(self):
        if confirm(
            self, "녹화 중지", "현재까지 받은 영상을 정리하고 부분 녹화로 저장합니다.", "녹화 중지"
        ):
            self.stop_pending = True
            self.dashboard.stop_button.setEnabled(False)
            self.controller.stop_recording(
                self.snapshot.active.id if self.snapshot and self.snapshot.active else None
            )

    @Slot(str, bool)
    def open_recording(self, identifier, folder):
        session = (
            next((s for s in self.snapshot.sessions if s.id == identifier), None)
            if self.snapshot
            else None
        )
        if session and folder and not session.output_path and session.work_directory:
            self.open_folder(Path(session.work_directory))
            return
        if not session or not session.output_path:
            self.show_message("저장된 파일이 있는 녹화 기록을 선택해 주세요.", error=True)
            return
        path = Path(session.output_path)
        if folder:
            self.open_folder(path.parent)
        elif path.suffix.lower() == ".mp4":
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.show_message("파일을 열 수 없습니다. 저장 위치를 확인해 주세요.", error=True)

    def open_folder(self, path: Path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_message("폴더를 열 수 없습니다. 저장 장치 연결을 확인해 주세요.", error=True)

    @Slot()
    def notification_clicked(self):
        if self.last_notification_folder:
            self.open_folder(self.last_notification_folder)
        else:
            self.restore_window()
            if self.last_notification_page is not None:
                self.select_page(self.last_notification_page)

    def tray_activated(self, reason):
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_window()

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent):
        if self.allow_close:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.ignore()
            self.request_quit()

    def changeEvent(self, event):
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    @Slot()
    def request_quit(self):
        if self.quitting:
            return
        if not confirm(
            self,
            "프로그램 완전 종료",
            "방송 감지를 중단하고 진행 중인 녹화 파일을 정리한 뒤 종료합니다.",
            "완전 종료",
        ):
            return
        self.quitting = True
        self.timer.stop()
        self.show_message("진행 중인 파일을 정리하고 있습니다. 완료되면 자동으로 종료합니다.")
        self.centralWidget().setEnabled(False)
        self.controller.close_async()

    @Slot()
    def finish_quit(self):
        if self.install_path:
            try:
                if os.name == "nt":
                    ctypes.windll.kernel32.SetDllDirectoryW(None)
                subprocess.Popen([str(self.install_path), "/SP-"])
            except OSError:
                self.show_message(
                    "설치 프로그램을 열지 못했습니다. 다운로드 폴더에서 다시 실행해 주세요.",
                    error=True,
                )
                self.open_folder(self.install_path.parent)
        self.allow_close = True
        self.tray.hide()
        self.close()
        QApplication.instance().quit()

    def check_update(self):
        if self.quitting or not self.settings.update.isEnabled():
            return
        self.settings.update.setEnabled(False)
        self.settings.update_status.setText("업데이트를 확인하고 있습니다.")
        self.controller.check_update()

    def on_update_checked(self, release, error):
        if self.quitting:
            return
        self.settings.update.setEnabled(True)
        if error:
            self.settings.update_status.setText(error)
            return
        if release is None:
            self.settings.update_status.setText("현재 최신 버전을 사용하고 있습니다.")
            return
        if release != self.release:
            self.update_path = None
        self.release = release
        self.settings.update_action.setText(
            "업데이트 설치" if self.update_path else "업데이트 다운로드"
        )
        self.settings.update_action.setEnabled(True)
        self.settings.update_status.setText(f"새 버전 {release.version}\n{release.notes}")
        self.last_notification_folder = None
        self.last_notification_page = 3
        self.tray.showMessage("새 버전이 있습니다", "설정에서 업데이트를 확인해 주세요.")

    def update_action(self):
        if not self.release or self.quitting:
            return
        if self.update_path:
            if self.snapshot and self.snapshot.active:
                self.show_message("녹화 또는 파일 정리가 끝난 뒤 설치해 주세요.", error=True)
                return
            if confirm(
                self,
                "업데이트 설치",
                f"버전 {self.release.version}을 설치하기 위해 프로그램을 종료할까요?",
                "종료 후 설치",
            ):
                self.settings.update_action.setEnabled(False)
                self.controller.prepare_install(self.update_path, self.release)
        else:
            self.settings.update_action.setEnabled(False)
            self.settings.update.setEnabled(False)
            self.settings.update_status.setText(
                "설치 파일을 다운로드하고 무결성을 확인하고 있습니다."
            )
            self.controller.download_update(self.release)

    def on_update_downloaded(self, path, error):
        if self.quitting:
            return
        self.settings.update.setEnabled(True)
        self.settings.update_action.setEnabled(True)
        if error:
            self.settings.update_status.setText(error)
            return
        self.update_path = path
        self.settings.update_action.setText("업데이트 설치")
        self.settings.update_status.setText(
            "파일 검사를 통과했습니다. 설치 버튼을 눌러 진행하세요."
        )

    def on_install_ready(self, path, error):
        if error:
            self.show_message(error, error=True)
            self.settings.update_action.setEnabled(True)
            return
        self.install_path = path
        self.quitting = True
        self.timer.stop()
        self.centralWidget().setEnabled(False)
        self.controller.close_async()
