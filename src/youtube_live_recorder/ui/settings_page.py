from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from youtube_live_recorder import __version__
from youtube_live_recorder.ui.widgets import card, label


class SettingsPage(QWidget):
    folder_requested = Signal(object)
    logs_requested = Signal()
    update_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        frame, content = card()
        content.addWidget(label("녹화 저장 위치", "sectionTitle"))
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        self.choose = QPushButton("폴더 선택")
        self.choose.clicked.connect(self.choose_folder)
        row.addWidget(self.choose)
        content.addLayout(row)
        content.addWidget(
            label(
                "녹화 중에는 저장 위치를 변경할 수 없습니다. "
                "기존 녹화 파일은 원래 위치에 유지됩니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(frame)
        frame, content = card()
        content.addWidget(label("자동 감지", "sectionTitle"))
        content.addWidget(
            label(
                "라이브 확인: 60초 간격\n다시보기 확인: 30분 간격 · 방송 종료 관찰 후 최대 24시간",
                wrap=True,
            )
        )
        content.addWidget(
            label(
                "방송 시작 구간 확보와 다시보기 제공 여부는 방송 조건에 따라 달라집니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(frame)
        frame, content = card()
        content.addWidget(label("프로그램 정보", "sectionTitle"))
        content.addWidget(label(f"YouTube Live Recorder  {__version__}"))
        row = QHBoxLayout()
        update = QPushButton("업데이트 확인")
        update.clicked.connect(self.update_requested)
        logs = QPushButton("진단 로그 폴더 열기")
        logs.clicked.connect(self.logs_requested)
        row.addWidget(update)
        row.addWidget(logs)
        row.addStretch()
        content.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch()

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "녹화 저장 폴더 선택", self.folder.text())
        if selected:
            self.folder_requested.emit(Path(selected))
