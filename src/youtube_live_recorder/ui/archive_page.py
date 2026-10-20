from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from youtube_live_recorder.data.models import STATUS_LABELS, Quality
from youtube_live_recorder.data.models import BroadcastStatus as B
from youtube_live_recorder.services.interfaces import LiveState
from youtube_live_recorder.ui.controller import Snapshot
from youtube_live_recorder.ui.formatting import size_label
from youtube_live_recorder.ui.widgets import card, label, populate, selected_id, table
from youtube_live_recorder.utils.errors import MESSAGES


class ArchivePage(QWidget):
    download_requested = Signal(str, object, str, bool)
    cancel_requested = Signal(str)
    retry_requested = Signal(str)
    folder_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.snapshot = None
        self.stop_pending = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        frame, form = card()
        form.addWidget(label("종료된 라이브를 처음부터 끝까지", "sectionTitle"))
        form.addWidget(
            label(
                "YouTube에서 제공하는 전체 다시보기를 MP4로 저장합니다. "
                "아직 다시보기를 처리 중이면 준비될 때까지 자동으로 확인합니다.",
                "muted",
                wrap=True,
            )
        )
        self.url = QLineEdit()
        self.url.setPlaceholderText("종료된 YouTube 라이브 URL을 붙여 넣으세요")
        self.url.setClearButtonEnabled(True)
        form.addWidget(self.url)
        fields = QGridLayout()
        fields.addWidget(label("다운로드 화질"), 0, 0)
        fields.addWidget(label("파일명 (선택)"), 0, 1)
        self.quality = QComboBox()
        for text, value in (
            ("720p", Quality.P720),
            ("1080p", Quality.P1080),
            ("최고 화질", Quality.BEST),
        ):
            self.quality.addItem(text, value)
        self.quality.setCurrentIndex(1)
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("비워 두면 방송 시작일_방송제목_다시보기.mp4")
        fields.addWidget(self.quality, 1, 0)
        fields.addWidget(self.filename, 1, 1)
        fields.setColumnStretch(1, 1)
        form.addLayout(fields)
        self.permission = QCheckBox("이 콘텐츠를 다운로드하고 저장할 권한이 있습니다.")
        form.addWidget(self.permission)
        self.folder = label("저장 폴더를 확인하고 있습니다.", "muted", wrap=True)
        form.addWidget(self.folder)
        self.add_button = QPushButton("전체 영상 다운로드")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(
            lambda: self.download_requested.emit(
                self.url.text(),
                self.quality.currentData(),
                self.filename.text(),
                self.permission.isChecked(),
            )
        )
        form.addWidget(self.add_button)
        layout.addWidget(frame)
        layout.addWidget(label("다운로드 목록", "sectionTitle"))
        self.hint = label("", "muted", wrap=True)
        layout.addWidget(self.hint)
        self.table = table(["영상 제목", "채널", "상태", "받은 데이터", "화질"])
        self.table.setMinimumHeight(180)
        self.table.setMaximumHeight(320)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        self.detail = label("종료된 라이브 URL을 등록해 주세요.", "muted", wrap=True)
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("다운로드 취소")
        self.cancel_button.setObjectName("danger")
        self.retry_button = QPushButton("오류 다시 확인")
        self.folder_button = QPushButton("저장 폴더 열기")
        for button, signal in (
            (self.cancel_button, self.cancel_requested),
            (self.retry_button, self.retry_requested),
            (self.folder_button, self.folder_requested),
        ):
            button.setEnabled(False)
            button.clicked.connect(
                lambda checked=False, s=signal: s.emit(selected_id(self.table) or "")
            )
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()

    def set_submitting(self, busy: bool):
        for widget in (self.url, self.quality, self.filename, self.permission, self.add_button):
            widget.setEnabled(not busy)
        self.add_button.setText("종료 여부 확인 중…" if busy else "전체 영상 다운로드")

    def update_snapshot(self, snapshot: Snapshot, stop_pending: set[str]):
        self.snapshot, self.stop_pending = snapshot, stop_pending
        self.folder.setText(f"저장 폴더: {snapshot.save_folder}\n설정에서 변경할 수 있습니다.")
        self.hint.setText(
            f"라이브 녹화와 합쳐 최대 {snapshot.max_concurrent_recordings}개 동시 처리 · "
            "빈자리가 나면 자동 시작 · 목록은 재시작 후에도 유지됩니다."
        )
        items = [b for b in reversed(snapshot.broadcasts) if b.archive_download]
        rows = []
        for item in items:
            session = next((s for s in snapshot.sessions if s.broadcast_id == item.id), None)
            state = STATUS_LABELS[item.status]
            if item.status == B.REPLAY_WAIT:
                state = (
                    "YouTube 처리 대기"
                    if item.live_state == LiveState.POST_LIVE
                    else "다운로드 대기"
                )
            elif item.status == B.REPLAY_DOWNLOADING:
                state = "다운로드 중"
            written = snapshot.session_bytes.get(session.id, session.size_bytes) if session else 0
            rows.append(
                (
                    item.id,
                    [
                        item.title or "제목 확인 중",
                        item.channel_name,
                        state,
                        size_label(written),
                        "최고 화질"
                        if item.preferred_quality == Quality.BEST
                        else item.preferred_quality,
                    ],
                )
            )
        populate(self.table, rows)
        if rows and selected_id(self.table) is None:
            self.table.selectRow(0)
        self._selection_changed()

    def _selection_changed(self):
        identifier = selected_id(self.table)
        item = (
            next((b for b in self.snapshot.broadcasts if b.id == identifier), None)
            if self.snapshot
            else None
        )
        active = (
            next((s for s in self.snapshot.active_sessions if s.broadcast_id == identifier), None)
            if self.snapshot
            else None
        )
        self.cancel_button.setEnabled(
            bool(
                item
                and item.status not in {B.CANCELLED, B.COMPLETED, B.REPLAY_EXPIRED}
                and (not active or active.id not in self.stop_pending)
            )
        )
        self.cancel_button.setText("다운로드 중지" if active else "다운로드 취소")
        self.retry_button.setEnabled(bool(item and item.status == B.ERROR and not active))
        self.folder_button.setEnabled(bool(item))
        if item:
            session = next((s for s in self.snapshot.sessions if s.broadcast_id == item.id), None)
            folder = self.snapshot.recording_folder(session.id if session else None)
            note = MESSAGES.get(item.last_error_code, "")
            if session and session.failure_reason:
                note = session.failure_reason
            self.detail.setText(
                f"{item.original_url}\n저장 폴더: {folder}" + (f"\n{note}" if note else "")
            )
