import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPen, QPixmap

STYLE = """
QWidget { font-family: 'Malgun Gothic'; font-size: 10pt; color: #27313b; }
QMainWindow, QWidget#content { background: #f4f6f8; }
QFrame#sidebar { background: #172b38; border: none; }
QLabel#brand { color: #ffffff; font-size: 15pt; font-weight: 700; }
QLabel#sidebarNote { color: #afc0cb; font-size: 9pt; }
QPushButton#nav { border: none; border-radius: 6px; text-align: left;
    padding: 12px 16px; color: #c9d6df; background: transparent; }
QPushButton#nav:checked { color: white; background: #31586a; font-weight: 700; }
QPushButton#nav:hover { background: #264655; }
QLabel#pageTitle { font-size: 22pt; font-weight: 700; color: #172b38; }
QLabel#subtitle, QLabel#muted { color: #647581; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 700; }
QFrame#card { background: white; border: 1px solid #dce3e8; border-radius: 8px; }
QLabel#metric { font-size: 17pt; font-weight: 700; color: #172b38; }
QLabel#banner { padding: 10px 14px; background: #e8f3ee; color: #27674d; border-radius: 5px; }
QLineEdit, QComboBox { background: white; border: 1px solid #cbd5dd; border-radius: 5px;
    padding: 9px; min-height: 20px; selection-background-color: #287e69; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #287e69; }
QLineEdit:read-only { background: #f4f6f8; }
QPushButton { background: white; border: 1px solid #cbd5dd; border-radius: 5px;
    padding: 9px 16px; min-height: 20px; }
QPushButton:hover { background: #edf3f5; }
QPushButton#primary { background: #287e69; border-color: #287e69; color: white; font-weight: 700; }
QPushButton#primary:hover { background: #206653; }
QPushButton#danger { color: #ac3b39; border-color: #dfbcbb; }
QPushButton:disabled { color: #9ba8b2; background: #edf0f3; border-color: #e1e6ea; }
QCheckBox { spacing: 8px; padding: 5px 0; }
QTableWidget { background: white; alternate-background-color: #f6f8fa; border: 1px solid #dce3e8;
    border-radius: 6px; gridline-color: #ecf0f3; selection-background-color: #e0eeea;
    selection-color: #1c4c40; }
QHeaderView::section { background: #edf2f5; padding: 10px 8px; border: none;
    border-bottom: 1px solid #dce3e8; color: #526370; font-weight: 700; }
QTableWidget::item { padding: 8px; }
QScrollArea { border: none; background: transparent; }
QToolTip { color: #27313b; background: #fff; border: 1px solid #cbd5dd; }
"""


def ensure_system_font() -> None:
    # Windows offscreen Qt 플러그인은 시스템 글꼴 목록을 자동으로 채우지 않는다.
    if "Malgun Gothic" not in QFontDatabase.families():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("malgun.ttf", "malgunbd.ttf"):
            path = fonts / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))


def status_icon(color: str = "#287e69") -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#172b38"))
    painter.drawRoundedRect(3, 3, 58, 58, 14, 14)
    painter.setPen(QPen(QColor("#ffffff"), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(14, 17, 36, 28, 5, 5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(23, 22, 18, 18)
    painter.end()
    return QIcon(pixmap)
