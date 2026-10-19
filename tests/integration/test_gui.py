import threading
from dataclasses import replace
from datetime import timedelta

import pytest
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QSystemTrayIcon

from youtube_live_recorder.bootstrap import bootstrap
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import Quality, RecordingMode
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.services.interfaces import BroadcastMetadata, LiveState
from youtube_live_recorder.ui.controller import Controller, Snapshot
from youtube_live_recorder.ui.main_window import MainWindow
from youtube_live_recorder.ui.notifications import NotificationTracker
from youtube_live_recorder.utils.time import to_iso, utc_now


@pytest.fixture
def desktop(qtbot, tmp_path):
    context = bootstrap(tmp_path / "app")
    context.repository.set_setting("save_folder", str(tmp_path / "recordings"))
    controller = Controller(context)
    window = MainWindow(controller, auto_start=False)
    # 이 창은 녹화 종료 절차가 있으므로 아래 fixture에서 스레드 종료 후 직접 정리한다.
    window.show()
    yield window, controller, context
    window.timer.stop()
    controller.shutdown_ready.disconnect(window.finish_quit)
    with qtbot.waitSignal(controller.shutdown_ready, timeout=15000):
        controller.close_async()
    window.allow_close = True
    window.tray.hide()
    window.close()
    for handler in context.logger.handlers[:]:
        context.logger.removeHandler(handler)
        handler.close()


def test_window_navigation_and_required_permission(desktop, qtbot):
    window, _, context = desktop
    for index, title in enumerate(("대시보드", "녹화 대기", "녹화 기록", "설정")):
        qtbot.mouseClick(window.nav_buttons[index], Qt.MouseButton.LeftButton)
        assert window.page_title.text() == title
    window.select_page(0)
    window.dashboard.url.setText("https://youtu.be/Abc_123-xYz")
    qtbot.mouseClick(window.dashboard.add_button, Qt.MouseButton.LeftButton)
    assert "권한" in window.banner.text()
    assert not context.repository.list_broadcasts()


def test_register_and_duplicate_error_keep_ui_responsive(desktop, qtbot):
    window, controller, context = desktop
    window.dashboard.url.setText("https://youtu.be/Abc_123-xYz")
    window.dashboard.permission.setChecked(True)
    with qtbot.waitSignal(controller.operation_done, timeout=5000):
        qtbot.mouseClick(window.dashboard.add_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.queue.table.rowCount() == 1, timeout=5000)
    assert len(context.repository.list_broadcasts()) == 1
    window.dashboard.url.setText("https://youtube.com/live/Abc_123-xYz")
    window.dashboard.permission.setChecked(True)
    with qtbot.waitSignal(controller.operation_done, timeout=5000) as signal:
        qtbot.mouseClick(window.dashboard.add_button, Qt.MouseButton.LeftButton)
    assert signal.args[1] is False
    assert "이미 대기" in window.banner.text()
    assert window.dashboard.add_button.isEnabled()


def test_slow_preview_does_not_block_ui_or_apply_stale_results(desktop, qtbot):
    window, controller, _ = desktop
    gate = threading.Event()

    class SlowMetadata:
        def fetch(self, url):
            gate.wait(5)
            return BroadcastMetadata(
                "Abc_123-xYz", "예전 입력의 방송", "채널", "", LiveState.UPCOMING
            )

    controller.metadata = SlowMetadata()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    window.dashboard.url.setText("https://youtu.be/Abc_123-xYz")
    qtbot.mouseClick(window.dashboard.preview_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.nav_buttons[1], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=1000)
    assert window.stack.currentIndex() == 1
    window.dashboard.url.setText("https://youtu.be/Xyz_987-aBc")
    with qtbot.waitSignal(controller.preview_ready, timeout=5000):
        gate.set()
    assert window.preview_metadata is None
    assert "예전 입력" not in window.dashboard.title.text()
    timer.stop()


def test_close_hides_to_tray_without_stopping_engine(desktop, monkeypatch):
    window, controller, _ = desktop
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window.close()
    assert not window.isVisible()
    assert not controller.closing.is_set()
    window.restore_window()
    assert window.isVisible()


def test_engine_start_error_remains_visible(desktop, qtbot):
    window, controller, _ = desktop

    def unavailable(_):
        raise RuntimeError("녹화 도구를 확인해 주세요.")

    controller.engine_factory = unavailable
    with qtbot.waitSignal(controller.engine_state, timeout=5000) as signal:
        controller.start()
    assert signal.args == ["error", "녹화 도구를 확인해 주세요."]
    controller.engine_future.result(timeout=5)
    assert "녹화 도구" in window.banner.text()
    assert not window.engine_running


def test_notification_click_opens_last_completed_folder(desktop, monkeypatch):
    window, _, context = desktop
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window.last_notification_folder = context.paths.root
    window.notification_clicked()
    assert opened == [QUrl.fromLocalFile(str(context.paths.root))]


def test_edit_cancel_and_folder_change_are_persisted(desktop, qtbot, tmp_path):
    _, controller, context = desktop
    item = context.repository.add_broadcast(
        "https://youtu.be/Abc_123-xYz", permission_confirmed=True
    )
    with qtbot.waitSignal(controller.operation_done, timeout=5000):
        controller.edit(item.id, Quality.P720, "한글 저장 이름")
    changed = context.repository.get_broadcast(item.id)
    assert changed.preferred_quality == Quality.P720 and changed.custom_filename == "한글 저장 이름"
    with qtbot.waitSignal(controller.operation_done, timeout=5000):
        controller.cancel(item.id)
    assert context.repository.get_broadcast(item.id).status == B.CANCELLED
    folder = tmp_path / "새 저장 폴더"
    with qtbot.waitSignal(controller.operation_done, timeout=5000):
        controller.save_folder(folder)
    assert context.repository.get_setting("save_folder") == str(folder)


def test_progress_history_and_notification_state(desktop, tmp_path):
    window, _, context = desktop
    item = context.repository.add_broadcast(
        "https://youtu.be/Abc_123-xYz", permission_confirmed=True
    )
    context.repository.transition(item.id, B.LIVE_DETECTED)
    session = context.repository.claim_session(item.id, RecordingMode.LIVE)
    session = replace(
        session,
        status=S.RUNNING,
        actual_quality="720p",
        started_at=to_iso(utc_now() + timedelta(seconds=1)),
    )
    tracker = NotificationTracker()
    notices = tracker.update((session,))
    assert len(notices) == 1 and "시작" in notices[0].title
    assert tracker.update((session,)) == []
    window.engine_running = True
    window.on_snapshot(Snapshot((item,), (session,), session, 1024, 4 * 1024**3, tmp_path))
    assert "720p" in window.dashboard.recording_detail.text()
    assert window.dashboard.stop_button.isEnabled()
    completed = replace(
        session,
        status=S.PARTIAL,
        output_path=str(tmp_path / "부분.mp4"),
        duration_seconds=10,
        size_bytes=1000,
        ffprobe_ok=True,
    )
    notices = tracker.update((completed,))
    assert notices[0].title == "부분 녹화 저장 완료" and notices[0].folder == tmp_path
    window.on_snapshot(
        Snapshot((replace(item, status=B.CANCELLED),), (completed,), None, 0, 4 * 1024**3, tmp_path)
    )
    assert window.history.table.rowCount() == 1
    assert window.queue.table.rowCount() == 0
    assert window.history.table.item(0, 2).text() == "부분 저장"
