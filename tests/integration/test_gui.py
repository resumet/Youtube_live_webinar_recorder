import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton, QSystemTrayIcon

from youtube_live_recorder.bootstrap import bootstrap
from youtube_live_recorder.config import Settings
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.data.models import Quality, RecordingMode
from youtube_live_recorder.data.models import SessionStatus as S
from youtube_live_recorder.services.interfaces import BroadcastMetadata, LiveState
from youtube_live_recorder.services.updates import Release, UpdateService
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


@pytest.mark.parametrize("available", [QRect(0, 0, 960, 516), QRect(1920, 0, 1280, 688)])
def test_small_screen_keeps_window_and_scrolled_controls_reachable(
    desktop, qtbot, monkeypatch, available
):
    window, _, _ = desktop
    monkeypatch.setattr(
        window, "screen", lambda: SimpleNamespace(availableGeometry=lambda: available)
    )
    window.resize(1240, 860)
    window._fit_to_screen()
    qtbot.waitUntil(lambda: available.contains(window.frameGeometry()))
    for index, navigation in enumerate(window.nav_buttons):
        window.sidebar_scroll.ensureWidgetVisible(navigation, 0, 0)
        qtbot.mouseClick(navigation, Qt.MouseButton.LeftButton)
        assert window.stack.currentIndex() == index
        scroll = window.stack.currentWidget()
        for button in scroll.widget().findChildren(QPushButton):
            scroll.ensureWidgetVisible(button, 0, 0)
            rect = QRect(button.mapTo(scroll.viewport(), QPoint()), button.size())
            assert scroll.viewport().rect().contains(rect), button.text()
    exit_button = next(
        button
        for button in window.sidebar_scroll.widget().findChildren(QPushButton)
        if button.text() == "완전 종료"
    )
    window.sidebar_scroll.ensureWidgetVisible(exit_button, 0, 0)
    rect = QRect(exit_button.mapTo(window.sidebar_scroll.viewport(), QPoint()), exit_button.size())
    assert window.sidebar_scroll.viewport().rect().contains(rect)


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


def test_stop_request_does_not_block_ui_while_engine_lock_is_busy(desktop, qtbot):
    _, controller, _ = desktop
    gate = threading.Event()
    entered = threading.Event()

    class BusyRecorder:
        def stop(self, *, expected_session_id=None):
            assert expected_session_id == "current-session"
            entered.set()
            gate.wait(5)

    class FakeEngine:
        recordings = BusyRecorder()

        def stop(self):
            pass

    controller.engine = FakeEngine()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    controller.stop_recording("current-session")
    qtbot.waitUntil(entered.is_set, timeout=1000)
    qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=1000)
    with qtbot.waitSignal(controller.operation_done, timeout=5000):
        gate.set()
    timer.stop()


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


def test_update_install_guard_rejects_active_recording(desktop, qtbot, tmp_path):
    _, controller, context = desktop
    item = context.repository.add_broadcast(
        "https://youtu.be/Abc_123-xYz", permission_confirmed=True
    )
    context.repository.transition(item.id, B.LIVE_DETECTED)
    context.repository.claim_session(item.id, RecordingMode.LIVE)

    class VerifiedUpdate:
        def verify_installer(self, *_):
            pass

    controller.updates = VerifiedUpdate()
    with qtbot.waitSignal(controller.install_ready, timeout=5000) as signal:
        controller.prepare_install(tmp_path / "Setup.exe", None)
    assert signal.args[0] is None and "미완료" in signal.args[1]
    assert not controller.closing.is_set()


def test_update_check_download_ui_never_runs_installer_without_click(desktop, qtbot, tmp_path):
    import hashlib
    import io
    import json

    window, controller, context = desktop
    content = b"MZfixture"
    release = Release(
        "0.3.0", "https://updates.example/Setup.exe", hashlib.sha256(content).hexdigest()
    )
    data = json.dumps(
        {"version": release.version, "download_url": release.download_url, "sha256": release.sha256}
    ).encode()
    controller.updates = UpdateService(
        tmp_path / "updates",
        opener=lambda url: io.BytesIO(data if url.endswith(".json") else content),
    )
    context.repository.set_setting("update_manifest_url", "https://updates.example/release.json")
    with qtbot.waitSignal(controller.update_checked, timeout=5000):
        window.check_update()
    assert window.release.version == "0.3.0" and window.update_path is None
    window.notification_clicked()
    assert window.stack.currentIndex() == 3
    with qtbot.waitSignal(controller.update_downloaded, timeout=5000):
        window.update_action()
    assert window.update_path.is_file()
    assert window.install_path is None and not controller.closing.is_set()
    assert window.settings.update_action.text() == "업데이트 설치"


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
        coverage_note="파일명 날짜는 첫 방송 감지 시각 기준 추정값입니다.",
        started_at=to_iso(utc_now() + timedelta(seconds=1)),
    )
    tracker = NotificationTracker()
    notices = tracker.update((session,))
    assert len(notices) == 1 and "시작" in notices[0].title
    assert tracker.update((session,)) == []
    window.engine_running = True
    window.on_snapshot(Snapshot((item,), (session,), session, 1024, 4 * 1024**3, tmp_path))
    assert "720p" in window.dashboard.recording_detail.text()
    assert "파일명 날짜" in window.dashboard.recording_detail.text()
    assert window.dashboard.stop_button.isEnabled()
    completed = replace(
        session,
        status=S.PARTIAL,
        output_path=str(tmp_path / "부분.mp4"),
        duration_seconds=10,
        size_bytes=1000,
        ffprobe_ok=True,
        failure_reason="사용자가 중지한 부분 녹화입니다.",
    )
    notices = tracker.update((completed,))
    assert notices[0].title == "부분 녹화 저장 완료" and notices[0].folder == tmp_path
    window.on_snapshot(
        Snapshot((replace(item, status=B.CANCELLED),), (completed,), None, 0, 4 * 1024**3, tmp_path)
    )
    assert window.history.table.rowCount() == 1
    assert window.queue.table.rowCount() == 0
    assert window.history.table.item(0, 2).text() == "부분 저장"
    assert "파일명 날짜" in window.history.table.item(0, 7).text()
    assert "사용자가 중지" in window.history.table.item(0, 7).text()


def test_multiple_recordings_select_stop_and_edit_guard(desktop, qtbot, monkeypatch, tmp_path):
    window, controller, context = desktop
    repo = context.repository
    items, sessions = [], []
    for index in range(5):
        item = repo.add_broadcast(f"https://youtu.be/Test{index:07}", permission_confirmed=True)
        repo.transition(item.id, B.LIVE_DETECTED)
        folder = tmp_path / f"저장 폴더 {index}"
        folder.mkdir()
        session = repo.claim_session(item.id, RecordingMode.LIVE, save_folder=folder)
        items.append(item)
        sessions.append(session)
    window.engine_running = True
    window.on_snapshot(Snapshot(tuple(items), tuple(sessions), sessions[0], 0, None, tmp_path))
    assert window.dashboard.recordings.rowCount() == 5
    assert "5개" in window.dashboard.metrics["status"].text()
    assert "5개" in window.tray.toolTip()
    requested = []
    monkeypatch.setattr(controller, "stop_recording", requested.append)
    monkeypatch.setattr("youtube_live_recorder.ui.main_window.confirm", lambda *_: True)
    window.dashboard.recordings.selectRow(3)
    qtbot.mouseClick(window.dashboard.stop_button, Qt.MouseButton.LeftButton)
    assert requested == [sessions[3].id]
    assert window.stop_pending == {sessions[3].id}
    window.dashboard.recordings.selectRow(4)
    assert window.dashboard.stop_button.isEnabled()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    for index in (4, 1):
        window.dashboard.recordings.selectRow(index)
        qtbot.mouseClick(window.dashboard.open_folder_button, Qt.MouseButton.LeftButton)
        actual = tmp_path / f"저장 폴더 {index}"
        assert opened[-1] == QUrl.fromLocalFile(str(actual))
        assert str(actual) in window.dashboard.recording_path.text()
    qtbot.mouseClick(window.dashboard.open_drive_button, Qt.MouseButton.LeftButton)
    assert opened[-1].toString() == (
        "https://drive.google.com/drive/folders/1R0hzzsDs0M7SOW6vOfe4ayZ353TRcE93?usp=sharing"
    )
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _: False)
    qtbot.mouseClick(window.dashboard.open_drive_button, Qt.MouseButton.LeftButton)
    assert "기본 브라우저 설정" in window.banner.text()
    window.edit_broadcast(items[4].id)
    assert "중지한 뒤" in window.banner.text()
    assert window.settings.choose.isEnabled()


def test_live_folder_and_capacity_settings_persist_without_changing_running_session(
    desktop, qtbot, tmp_path
):
    window, controller, context = desktop
    item = context.repository.add_broadcast(
        "https://youtu.be/Test0000000", permission_confirmed=True
    )
    context.repository.transition(item.id, B.LIVE_DETECTED)
    session = context.repository.claim_session(item.id, RecordingMode.LIVE, save_folder=tmp_path)
    recorder = SimpleNamespace(lock=threading.Lock(), settings=Settings(tmp_path))
    controller.engine = SimpleNamespace(recordings=recorder, stop=lambda: None)
    new_folder = tmp_path / "설정에서 선택한 저장소"
    with qtbot.waitSignal(controller.operation_done, timeout=5000) as result:
        controller.save_folder(new_folder)
    assert result.args[1] is True
    assert recorder.settings.save_folder == new_folder
    assert context.repository.get_session(session.id).work_directory == session.work_directory
    window.settings.concurrency.setValue(7)
    # 화면 갱신이 아직 저장하지 않은 입력을 덮어쓰지 않아야 한다.
    window.settings.sync_limit(5)
    assert window.settings.concurrency.value() == 7
    with qtbot.waitSignal(controller.operation_done, timeout=5000) as result:
        qtbot.mouseClick(window.settings.save_limit, Qt.MouseButton.LeftButton)
    assert result.args[1] is True
    assert recorder.settings.max_concurrent_recordings == 7
    restored = Settings.load(context.repository)
    assert restored.save_folder == new_folder and restored.max_concurrent_recordings == 7
    assert len(context.repository.active_sessions()) == 1
