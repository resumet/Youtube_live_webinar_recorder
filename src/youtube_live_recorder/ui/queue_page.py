from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from youtube_live_recorder.data.models import STATUS_LABELS, Broadcast, Quality
from youtube_live_recorder.ui.formatting import local_time
from youtube_live_recorder.ui.widgets import label, populate, selected_id, table
from youtube_live_recorder.utils.errors import MESSAGES


class QueuePage(QWidget):
    edit_requested = Signal(str)
    cancel_requested = Signal(str)
    retry_requested = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.addWidget(label("등록한 방송은 프로그램을 다시 실행해도 유지됩니다.", "muted"), 1)
        edit = QPushButton("선택 항목 수정")
        edit.clicked.connect(lambda: self.edit_requested.emit(selected_id(self.table) or ""))
        cancel = QPushButton("대기 취소")
        cancel.setObjectName("danger")
        cancel.clicked.connect(lambda: self.cancel_requested.emit(selected_id(self.table) or ""))
        actions.addWidget(edit)
        retry = QPushButton("오류 다시 확인")
        retry.clicked.connect(lambda: self.retry_requested.emit(selected_id(self.table) or ""))
        actions.addWidget(retry)
        actions.addWidget(cancel)
        layout.addLayout(actions)
        self.empty = label(
            "대기 중인 방송이 없습니다. 대시보드에서 URL을 등록해 주세요.", "muted", wrap=True
        )
        layout.addWidget(self.empty)
        self.table = table(
            [
                "방송 제목",
                "채널",
                "영상 ID",
                "예정 시작",
                "상태",
                "화질",
                "파일명",
                "등록 시각",
                "안내",
            ]
        )
        self.table.setObjectName("queueTable")
        layout.addWidget(self.table, 1)
        self._items = None

    def update_items(self, items: tuple[Broadcast, ...]) -> None:
        if items == self._items:
            return
        self._items = items
        self.empty.setVisible(not items)
        populate(
            self.table,
            [
                (
                    item.id,
                    [
                        item.title or "제목 확인 중",
                        item.channel_name or "—",
                        item.video_id,
                        local_time(item.scheduled_start_at),
                        STATUS_LABELS[item.status],
                        "최고 화질"
                        if item.preferred_quality == Quality.BEST
                        else item.preferred_quality,
                        item.custom_filename or "방송 시작일_제목.mp4",
                        local_time(item.registered_at),
                        MESSAGES.get(item.last_error_code, ""),
                    ],
                )
                for item in items
            ],
        )
