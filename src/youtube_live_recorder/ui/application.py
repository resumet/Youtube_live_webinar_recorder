import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from youtube_live_recorder.bootstrap import ApplicationContext
from youtube_live_recorder.ui.controller import Controller
from youtube_live_recorder.ui.main_window import MainWindow


def run_gui(context: ApplicationContext) -> int:
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
    return app.exec()
