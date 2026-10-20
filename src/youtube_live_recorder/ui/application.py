import json
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.ui.controller import Controller
from youtube_live_recorder.ui.main_window import PAGE_NAMES, MainWindow


def run_gui(context: ApplicationContext, *, smoke_report: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("YouTube Live Recorder")
    app.setOrganizationName("YouTubeLiveRecorder")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Malgun Gothic", 10))
    QLocale.setDefault(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))
    translator = QTranslator(app)
    if translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    controller = Controller(context)
    window = MainWindow(controller)
    window.show()
    if smoke_report:
        heartbeats = []
        timer = QTimer(window)
        timer.timeout.connect(lambda: heartbeats.append(1))
        timer.start(50)

        def finish_smoke():
            smoke_report.parent.mkdir(parents=True, exist_ok=True)
            screenshot = smoke_report.with_suffix(".png")
            rendered = window.grab().save(str(screenshot))
            screen = window.screen()
            pages = []
            for index, name in enumerate(PAGE_NAMES):
                window.select_page(index)
                app.processEvents()
                page_image = smoke_report.with_name(f"{smoke_report.stem}-{name}.png")
                rendered = window.grab().save(str(page_image)) and rendered
                pages.append({"이름": name, "화면": str(page_image)})
            report = {
                "성공": bool(rendered and len(heartbeats) >= 5 and window.engine_running),
                "UI 타이머 횟수": len(heartbeats),
                "엔진 실행": window.engine_running,
                "화면": str(screenshot),
                "페이지": pages,
                "장치 배율": window.devicePixelRatioF(),
                "가용 화면": list(screen.availableGeometry().getRect()) if screen else None,
                "창 테두리": list(window.frameGeometry().getRect()),
                "화면 안에 창 표시": bool(
                    screen and screen.availableGeometry().contains(window.frameGeometry())
                ),
            }
            smoke_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            window.quitting = True
            window.timer.stop()
            controller.close_async()

        QTimer.singleShot(3000, finish_smoke)
    return app.exec()
