"""로컬 검증 영상과 모의 상태로 실제 Windows 트레이·알림 클릭을 확인한다."""

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4


def run(reports: Path, *, smoke: bool = False) -> Path:
    if os.name != "nt":
        raise RuntimeError("이 검증은 Windows에서 실행하세요.")
    if smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    else:
        os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from youtube_live_recorder.bootstrap import bootstrap
    from youtube_live_recorder.data.db import Database
    from youtube_live_recorder.data.models import BroadcastStatus, SessionStatus
    from youtube_live_recorder.data.repository import Repository
    from youtube_live_recorder.services.diagnostics import run_self_test
    from youtube_live_recorder.ui.controller import Controller, Snapshot
    from youtube_live_recorder.ui.main_window import MainWindow
    from youtube_live_recorder.utils.time import to_iso, utc_now

    root = reports.resolve() / str(uuid4())
    root.mkdir(parents=True)
    print("검증용 로컬 영상을 준비합니다. YouTube에 접속하지 않습니다.", flush=True)
    media = run_self_test(root)
    output = Path(media["검증 파일"])
    fixtures = Repository(Database(output.parent / "test.db"))
    completed = fixtures.list_sessions()[0]
    broadcast = fixtures.get_broadcast(completed.broadcast_id)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    context = bootstrap(root / "ui-data")
    controller = Controller(context)
    window = MainWindow(controller, auto_start=False)
    window.setWindowTitle("트레이·알림 로컬 검증 — YouTube Live Recorder")
    window.on_engine_state("running", "로컬 검증 화면입니다. 실제 방송을 감지하거나 받지 않습니다.")
    # 검사 화면에서는 새 URL 등록이나 설정 변경을 받지 않는다.
    for page in (window.dashboard, window.queue, window.history, window.settings):
        page.setEnabled(False)
    report = {
        "범위": "실제 Windows 셸 클릭 확인용 · 방송 상태는 모의 응답",
        "자동 화면 점검": smoke,
        "검증 영상": str(output),
        "영상 기본 검사": media["MP4 검사"],
        "트레이 사용 가능": QSystemTrayIcon.isSystemTrayAvailable(),
        "창 숨김 관찰": False,
        "트레이 클릭 후 복원": False,
        "완료 알림 클릭": False,
        "탐색기 실제 표시": "사용자 육안 확인 필요",
    }

    class Observer(QObject):
        def eventFilter(self, watched, event):
            if watched is window and event.type() == QEvent.Type.Hide and not window.quitting:
                report["창 숨김 관찰"] = True
            return False

    observer = Observer(window)
    window.installEventFilter(observer)

    def activated(reason):
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            report["트레이 클릭 후 복원"] = bool(report["창 숨김 관찰"] and window.isVisible())

    def clicked():
        if window.last_notification_folder == output.parent:
            report["완료 알림 클릭"] = True

    window.tray.activated.connect(activated)
    window.tray.messageClicked.connect(clicked)
    started = to_iso(utc_now())

    def show_started():
        session = replace(
            completed,
            status=SessionStatus.RUNNING,
            started_at=started,
            ended_at=None,
            output_path=None,
            duration_seconds=None,
            size_bytes=0,
            ffprobe_ok=False,
        )
        window.on_snapshot(
            Snapshot(
                (replace(broadcast, status=BroadcastStatus.RECORDING),),
                (session,),
                session,
                0,
                None,
                output.parent,
            )
        )

    def show_completed():
        session = replace(completed, started_at=started, ended_at=to_iso(utc_now()))
        window.on_snapshot(Snapshot((broadcast,), (session,), None, 0, None, output.parent))

    def end_check():
        if not window.quitting:
            window.quitting = True
            window.timer.stop()
            controller.close_async()

    window.show()
    QTimer.singleShot(1000, show_started)
    QTimer.singleShot(20000, show_completed)
    QTimer.singleShot(25000 if smoke else 600000, end_check)
    print(
        "창 X → 트레이 아이콘 클릭 → 20초 후 완료 알림 클릭 → 완전 종료 순서로 확인하세요.",
        flush=True,
    )
    result = app.exec()
    report["정상 종료"] = result == 0
    report["모의 완료 화면 표시"] = bool(
        window.snapshot
        and any(session.status == SessionStatus.COMPLETE for session in window.snapshot.sessions)
    )
    path = root / "result.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["정상 종료"] or not report["모의 완료 화면 표시"]:
        raise RuntimeError(f"로컬 검사 화면의 실행/종료를 확인하지 못했습니다. 결과: {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="외부 방송 없이 Windows 트레이·알림 수동 검사")
    parser.add_argument("--reports", type=Path, default=Path(".runtime/manual-shell-tests"))
    parser.add_argument(
        "--smoke", action="store_true", help="화면만 자동 검사하고 종료; 클릭 성공 아님"
    )
    args = parser.parse_args()
    print(run(args.reports, smoke=args.smoke))
