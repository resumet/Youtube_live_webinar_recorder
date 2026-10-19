import multiprocessing
import sys

from youtube_live_recorder.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # 설치 바로가기는 인수 없이 GUI를 연다. CLI 및 워커 호출은 기존 명령을 유지한다.
    result = main(sys.argv[1:] or ["gui"])
    if result and sys.stderr is None:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(
            None,
            "프로그램 실행 오류",
            "프로그램을 시작하지 못했습니다. 데이터 폴더와 진단 로그를 확인해 주세요.",
        )
    raise SystemExit(result)
