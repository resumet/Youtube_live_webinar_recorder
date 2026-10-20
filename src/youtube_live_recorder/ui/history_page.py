from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from youtube_live_recorder.data.models import ACTIVE_SESSIONS, SessionStatus
from youtube_live_recorder.ui.controller import Snapshot
from youtube_live_recorder.ui.formatting import duration, local_time, size_label
from youtube_live_recorder.ui.widgets import label, populate, selected_id, table


class HistoryPage(QWidget):
    open_requested = Signal(str, bool)
    delete_requested = Signal(str)
    delete_all_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.addWidget(label("완료·부분 저장·실패 기록과 저장된 파일을 확인합니다.", "muted"), 1)
        self.file_button = QPushButton("파일 열기")
        self.file_button.clicked.connect(
            lambda: self.open_requested.emit(selected_id(self.table) or "", False)
        )
        self.folder_button = QPushButton("폴더 열기")
        self.folder_button.clicked.connect(
            lambda: self.open_requested.emit(selected_id(self.table) or "", True)
        )
        self.delete_button = QPushButton("선택 삭제")
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(
            lambda: self.delete_requested.emit(selected_id(self.table) or "")
        )
        self.delete_all_button = QPushButton("전체 삭제")
        self.delete_all_button.setObjectName("danger")
        self.delete_all_button.clicked.connect(self.delete_all_requested)
        for button in (self.file_button, self.folder_button, self.delete_button):
            button.setEnabled(False)
        self.delete_all_button.setEnabled(False)
        actions.addWidget(self.file_button)
        actions.addWidget(self.folder_button)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.delete_all_button)
        layout.addLayout(actions)
        self.empty = label("아직 녹화 기록이 없습니다.", "muted")
        layout.addWidget(self.empty)
        self.table = table(
            ["방송 제목", "시작 날짜", "결과", "길이", "용량", "원본 URL", "저장 경로", "안내"]
        )
        self.table.setObjectName("historyTable")
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(
            lambda *_: self.open_requested.emit(selected_id(self.table) or "", False)
        )
        layout.addWidget(self.table, 1)
        self._rows = None

    def update_snapshot(self, snapshot: Snapshot):
        broadcasts = {item.id: item for item in snapshot.broadcasts}
        rows = []
        results = {
            SessionStatus.COMPLETE: "완료",
            SessionStatus.PARTIAL: "부분 저장",
            SessionStatus.FAILED: "실패",
            SessionStatus.CANCELLED: "취소",
        }
        for session in snapshot.sessions:
            if session.status in ACTIVE_SESSIONS:
                continue
            item = broadcasts.get(session.broadcast_id)
            rows.append(
                (
                    session.id,
                    [
                        item.title or "방송" if item else "방송",
                        local_time(session.started_at),
                        results[session.status],
                        duration(session.duration_seconds),
                        size_label(session.size_bytes),
                        item.original_url if item else "",
                        session.output_path or "완료 파일 없음",
                        " ".join(
                            dict.fromkeys(
                                note
                                for note in (session.failure_reason, session.coverage_note)
                                if note
                            )
                        ),
                    ],
                )
            )
        self.empty.setVisible(not rows)
        if rows != self._rows:
            self._rows = rows
            populate(self.table, rows)
        self.delete_all_button.setEnabled(bool(rows))
        self._selection_changed()

    def _selection_changed(self):
        enabled = selected_id(self.table) is not None
        for button in (self.file_button, self.folder_button, self.delete_button):
            button.setEnabled(enabled)
