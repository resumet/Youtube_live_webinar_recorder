from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from youtube_live_recorder import __version__
from youtube_live_recorder.limits import DEFAULT_CONCURRENT_RECORDINGS, MAX_CONCURRENT_RECORDINGS
from youtube_live_recorder.ui.widgets import card, label


class SettingsPage(QWidget):
    folder_requested = Signal(object)
    concurrency_requested = Signal(int)
    logs_requested = Signal()
    update_requested = Signal()
    update_action_requested = Signal()

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
                "변경한 폴더는 이후 시작하는 녹화부터 적용됩니다. "
                "진행 중인 녹화와 기존 파일은 원래 위치에 유지됩니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(frame)
        frame, content = card()
        content.addWidget(label("동시 녹화", "sectionTitle"))
        row = QHBoxLayout()
        row.addWidget(label("최대 녹화 수"))
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, MAX_CONCURRENT_RECORDINGS)
        self.concurrency.setValue(DEFAULT_CONCURRENT_RECORDINGS)
        self.concurrency.setSuffix("개")
        self.limit_dirty = False
        self.concurrency.valueChanged.connect(self._limit_changed)
        row.addWidget(self.concurrency)
        self.save_limit = QPushButton("동시 녹화 수 저장")
        self.save_limit.clicked.connect(self._save_limit)
        row.addWidget(self.save_limit)
        row.addStretch()
        content.addLayout(row)
        content.addWidget(
            label(
                "기본 5개 · 1~10개 설정 가능. 상한을 낮춰도 진행 중인 녹화는 계속됩니다. "
                "자리가 부족하면 등록 순서대로 60초마다 다시 확인합니다.",
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
        self.update = QPushButton("업데이트 확인")
        self.update.clicked.connect(self.update_requested)
        self.update_action = QPushButton("업데이트 다운로드")
        self.update_action.setEnabled(False)
        self.update_action.clicked.connect(self.update_action_requested)
        logs = QPushButton("진단 로그 폴더 열기")
        logs.clicked.connect(self.logs_requested)
        row.addWidget(self.update)
        row.addWidget(self.update_action)
        row.addWidget(logs)
        row.addStretch()
        content.addLayout(row)
        self.update_status = label("업데이트 확인 결과가 여기에 표시됩니다.", "muted", wrap=True)
        content.addWidget(self.update_status)
        layout.addWidget(frame)
        layout.addStretch()

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "녹화 저장 폴더 선택", self.folder.text())
        if selected:
            self.folder_requested.emit(Path(selected))

    def _limit_changed(self):
        self.limit_dirty = True

    def _save_limit(self):
        self.save_limit.setEnabled(False)
        self.concurrency_requested.emit(self.concurrency.value())

    def sync_limit(self, count):
        if not self.limit_dirty:
            self.concurrency.blockSignals(True)
            self.concurrency.setValue(count)
            self.concurrency.blockSignals(False)
