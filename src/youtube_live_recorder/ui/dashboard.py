from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
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

from youtube_live_recorder.data.models import BroadcastStatus, Quality
from youtube_live_recorder.services.interfaces import BroadcastMetadata
from youtube_live_recorder.ui.controller import Snapshot
from youtube_live_recorder.ui.formatting import duration, local_time, size_label
from youtube_live_recorder.ui.widgets import card, label
from youtube_live_recorder.utils.time import from_iso, utc_now


class Dashboard(QWidget):
    preview_requested = Signal(str)
    add_requested = Signal(str, object, str, bool)
    stop_requested = Signal()
    url_changed = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        summary = QHBoxLayout()
        self.metrics = {}
        for key, caption in (
            ("status", "현재 상태"),
            ("waiting", "대기 방송"),
            ("errors", "확인 필요"),
            ("disk", "저장 공간"),
        ):
            frame, box = card()
            box.addWidget(label(caption, "muted"))
            value = label("—", "metric")
            box.addWidget(value)
            self.metrics[key] = value
            summary.addWidget(frame)
        layout.addLayout(summary)

        frame, form = card()
        form.addWidget(label("새 방송 등록", "sectionTitle"))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setObjectName("broadcastUrl")
        self.url.setPlaceholderText("YouTube 라이브 URL을 붙여 넣으세요")
        self.url.setClearButtonEnabled(True)
        self.url.textChanged.connect(self.url_changed)
        self.preview_button = QPushButton("방송 정보 조회")
        self.preview_button.clicked.connect(lambda: self.preview_requested.emit(self.url.text()))
        row.addWidget(self.url, 1)
        row.addWidget(self.preview_button)
        form.addLayout(row)

        preview = QHBoxLayout()
        self.thumbnail = label("방송 미리보기", "muted")
        self.thumbnail.setFixedSize(160, 90)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet("background: #edf2f5; border-radius: 5px;")
        preview.addWidget(self.thumbnail)
        info = QVBoxLayout()
        self.title = label("방송 정보를 조회하면 여기에 표시됩니다.", "sectionTitle", wrap=True)
        self.channel = label(
            "제목 · 채널 · 예정 시간을 미리 확인할 수 있습니다.", "muted", wrap=True
        )
        self.preview_status = label("조회에 실패해도 URL만 등록할 수 있습니다.", "muted", wrap=True)
        info.addWidget(self.title)
        info.addWidget(self.channel)
        info.addWidget(self.preview_status)
        preview.addLayout(info, 1)
        form.addLayout(preview)

        fields = QGridLayout()
        fields.addWidget(label("녹화 화질"), 0, 0)
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
        self.filename.setPlaceholderText("비워 두면 방송 시작일_방송제목.mp4")
        fields.addWidget(self.quality, 1, 0)
        fields.addWidget(self.filename, 1, 1)
        fields.setColumnStretch(1, 1)
        form.addLayout(fields)
        self.permission = QCheckBox("이 콘텐츠를 녹화하고 저장할 권한이 있습니다.")
        form.addWidget(self.permission)
        actions = QHBoxLayout()
        actions.addWidget(
            label(
                "60초마다 확인 · 최대 1개 녹화 · 시작 구간 확보는 방송 조건에 따라 달라집니다.",
                "muted",
                wrap=True,
            ),
            1,
        )
        self.add_button = QPushButton("대기 목록에 등록")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(
            lambda: self.add_requested.emit(
                self.url.text(),
                self.quality.currentData(),
                self.filename.text(),
                self.permission.isChecked(),
            )
        )
        actions.addWidget(self.add_button)
        form.addLayout(actions)
        layout.addWidget(frame)

        frame, progress = card()
        row = QHBoxLayout()
        row.addWidget(label("진행 중인 녹화", "sectionTitle"), 1)
        self.stop_button = QPushButton("녹화 중지")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        row.addWidget(self.stop_button)
        progress.addLayout(row)
        self.recording_title = label("등록한 방송의 시작을 기다립니다.", wrap=True)
        self.recording_detail = label(
            "녹화가 시작되면 시간·용량·화질이 표시됩니다.", "muted", wrap=True
        )
        self.recording_path = label("", "muted", wrap=True)
        progress.addWidget(self.recording_title)
        progress.addWidget(self.recording_detail)
        progress.addWidget(self.recording_path)
        layout.addWidget(frame)
        layout.addStretch()

    def show_preview(self, metadata: BroadcastMetadata | None, image: bytes, message: str):
        self.preview_button.setEnabled(True)
        self.preview_button.setText("방송 정보 조회")
        self.thumbnail.clear()
        if metadata is None:
            self.thumbnail.setText("미리보기 없음")
            self.title.setText("방송 정보를 확인하지 못했습니다.")
            self.channel.setText("URL만 등록한 뒤 자동 감지에서 다시 확인할 수 있습니다.")
            self.preview_status.setText(message)
            return
        self.title.setText(metadata.title)
        self.channel.setText(metadata.channel_name or "채널 정보 없음")
        statuses = {
            "is_live": "라이브 진행 중",
            "is_upcoming": "방송 예정",
            "post_live": "다시보기 처리 중",
            "was_live": "종료된 방송",
            "not_live": "일반 영상",
            "unknown": "상태 확인 중",
        }
        self.preview_status.setText(
            f"{statuses[metadata.state]}  ·  예정: {local_time(metadata.scheduled_start_at)}"
        )
        pixmap = QPixmap()
        if image and pixmap.loadFromData(image):
            self.thumbnail.setPixmap(
                pixmap.scaled(
                    160,
                    90,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.thumbnail.setText("썸네일 없음")

    def update_snapshot(self, snapshot: Snapshot, engine_running: bool, stop_pending: bool):
        errors = sum(
            item.status
            in {BroadcastStatus.ERROR, BroadcastStatus.ERROR_RETRYABLE, BroadcastStatus.INTERRUPTED}
            for item in snapshot.queue
        )
        self.metrics["status"].setText(
            "녹화 중"
            if snapshot.active and engine_running
            else "감지 중"
            if engine_running
            else "확인 필요"
        )
        self.metrics["waiting"].setText(f"{len(snapshot.queue)}개")
        self.metrics["errors"].setText(f"{errors}개")
        self.metrics["disk"].setText(
            size_label(snapshot.free_bytes) if snapshot.free_bytes is not None else "확인 필요"
        )
        active = snapshot.active
        self.stop_button.setEnabled(bool(active and engine_running and not stop_pending))
        self.stop_button.setText("파일 정리 중…" if stop_pending and active else "녹화 중지")
        if active:
            item = next((b for b in snapshot.broadcasts if b.id == active.broadcast_id), None)
            self.recording_title.setText(item.title if item and item.title else "방송 녹화")
            elapsed = (utc_now() - from_iso(active.started_at)).total_seconds()
            self.recording_detail.setText(
                f"경과 {duration(elapsed)}  ·  저장 데이터 {size_label(snapshot.bytes_written)}"
                f"  ·  실제 화질 {active.actual_quality or '확인 중'}"
            )
        else:
            self.recording_title.setText(
                "등록한 방송의 시작을 기다립니다."
                if snapshot.queue
                else "등록된 대기 방송이 없습니다."
            )
            self.recording_detail.setText(
                "방송 감지는 서비스 응답과 재시도 시간에 따라 지연될 수 있습니다."
            )
        self.recording_path.setText(f"저장 위치: {snapshot.save_folder}")
