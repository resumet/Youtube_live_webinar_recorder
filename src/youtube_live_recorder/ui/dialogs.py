from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from youtube_live_recorder import REPOSITORY_URL, __version__
from youtube_live_recorder.data.models import Broadcast, Quality
from youtube_live_recorder.ui.widgets import label


def confirm(parent, title: str, text: str, accept: str) -> bool:
    message = QMessageBox(parent)
    message.setWindowTitle(title)
    message.setText(text)
    message.setIcon(QMessageBox.Icon.Question)
    yes = message.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
    no = message.addButton(
        "계속 실행" if accept == "완전 종료" else "돌아가기", QMessageBox.ButtonRole.RejectRole
    )
    message.setDefaultButton(no)
    message.exec()
    return message.clickedButton() == yes


def show_about(parent) -> None:
    message = QMessageBox(parent)
    message.setWindowTitle("프로그램 정보")
    message.setIcon(QMessageBox.Icon.Information)
    message.setText(f"<b>YouTube Live Recorder</b><br>버전 {__version__}")
    message.setInformativeText(
        "허가받은 YouTube 라이브 방송을 자동으로 감지하고 저장합니다.<br><br>"
        f'<a href="{REPOSITORY_URL}">GitHub 저장소 및 릴리스</a>'
    )
    message.setTextFormat(Qt.TextFormat.RichText)
    message.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    message.setStandardButtons(QMessageBox.StandardButton.Ok)
    message.exec()


class EditDialog(QDialog):
    def __init__(self, item: Broadcast, parent=None):
        super().__init__(parent)
        self.setWindowTitle("대기 방송 수정")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(label(item.title or item.video_id, "sectionTitle", wrap=True))
        form = QFormLayout()
        self.quality = QComboBox()
        for text, value in (
            ("720p", Quality.P720),
            ("1080p", Quality.P1080),
            ("최고 화질", Quality.BEST),
        ):
            self.quality.addItem(text, value)
        self.quality.setCurrentIndex(self.quality.findData(item.preferred_quality))
        self.filename = QLineEdit(item.custom_filename)
        self.filename.setPlaceholderText("비워 두면 방송 시작일_방송제목.mp4")
        form.addRow("화질", self.quality)
        form.addRow("파일명", self.filename)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        buttons.addButton("변경 저장", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("돌아가기", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
