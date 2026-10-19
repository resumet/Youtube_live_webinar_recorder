from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


def label(text: str, style: str = "", *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(style)
    widget.setWordWrap(wrap)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(46)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    widget.setWordWrap(False)
    return widget


def populate(widget: QTableWidget, rows: list[tuple[str, list[str]]]) -> None:
    selected = selected_id(widget)
    scroll = widget.verticalScrollBar().value()
    widget.setUpdatesEnabled(False)
    widget.setRowCount(len(rows))
    for row, (identifier, values) in enumerate(rows):
        for column, value in enumerate(values):
            cell = widget.item(row, column)
            if cell is None:
                cell = QTableWidgetItem()
                widget.setItem(row, column, cell)
            cell.setText(value)
            cell.setToolTip(value)
            if column == 0:
                cell.setData(Qt.ItemDataRole.UserRole, identifier)
        if identifier == selected:
            widget.selectRow(row)
    widget.verticalScrollBar().setValue(scroll)
    widget.setUpdatesEnabled(True)


def selected_id(widget: QTableWidget) -> str | None:
    row = widget.currentRow()
    return (
        widget.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if row >= 0 and widget.item(row, 0)
        else None
    )
