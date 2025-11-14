from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QToolButton,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStyle,
)

from . import strings
from .db import DBManager
from .flow_layout import FlowLayout


class TagChip(QFrame):
    removeRequested = Signal(int)  # tag_id
    clicked = Signal(str)  # tag name

    def __init__(
        self, tag_id: int, name: str, color: str, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self._id = tag_id
        self._name = name

        self.setObjectName("TagChip")

        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        color_lbl = QLabel()
        color_lbl.setFixedSize(10, 10)
        color_lbl.setStyleSheet(f"background-color: {color}; border-radius: 3px;")
        layout.addWidget(color_lbl)

        name_lbl = QLabel(name)
        layout.addWidget(name_lbl)

        btn = QToolButton()
        btn.setText("×")
        btn.setAutoRaise(True)
        btn.clicked.connect(lambda: self.removeRequested.emit(self._id))

        self.setCursor(Qt.PointingHandCursor)

        layout.addWidget(btn)

    @property
    def tag_id(self) -> int:
        return self._id

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._name)
        super().mouseReleaseEvent(ev)


class PageTagsWidget(QFrame):
    """
    Collapsible per-page tag editor shown in the left sidebar.
    """

    def __init__(self, db: DBManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._db = db
        self._current_date: Optional[str] = None

        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Header (toggle + manage button)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(strings._("tags"))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setArrowType(Qt.RightArrow)
        self.toggle_btn.clicked.connect(self._on_toggle)

        self.manage_btn = QToolButton()
        self.manage_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.manage_btn.setToolTip(strings._("manage_tags"))
        self.manage_btn.setAutoRaise(True)
        self.manage_btn.clicked.connect(self._open_manager)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle_btn)
        header.addStretch(1)
        header.addWidget(self.manage_btn)

        # Body (chips + add line)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(4)

        # Simple horizontal layout for now; you can swap for a FlowLayout
        self.chip_row = FlowLayout(self.body, hspacing=4, vspacing=4)
        self.body_layout.addLayout(self.chip_row)

        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText(strings._("add_tag_placeholder"))
        self.add_edit.returnPressed.connect(self._on_add_tag)
        self.body_layout.addWidget(self.add_edit)

        self.body.setVisible(False)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(self.body)

    # ----- external API ------------------------------------------------

    def set_current_date(self, date_iso: str) -> None:
        self._current_date = date_iso
        if self.toggle_btn.isChecked():
            self._reload_tags()
        else:
            # Keep it cheap while collapsed; reload only when expanded
            self._clear_chips()

    # ----- internals ---------------------------------------------------

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked and self._current_date:
            self._reload_tags()

    def _clear_chips(self) -> None:
        while self.chip_row.count():
            item = self.chip_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _reload_tags(self) -> None:
        if not self._current_date:
            self._clear_chips()
            return

        self._clear_chips()
        tags = self._db.get_tags_for_page(self._current_date)
        for tag_id, name, color in tags:
            chip = TagChip(tag_id, name, color, self)
            chip.removeRequested.connect(self._remove_tag)
            chip.clicked.connect(self._on_chip_clicked)
            self.chip_row.addWidget(chip)

    def _on_add_tag(self) -> None:
        if not self._current_date:
            return
        new_tag = self.add_edit.text().strip()
        if not new_tag:
            return

        # Combine current tags + new one, then write back
        existing = [
            name for _, name, _ in self._db.get_tags_for_page(self._current_date)
        ]
        existing.append(new_tag)
        self._db.set_tags_for_page(self._current_date, existing)
        self.add_edit.clear()
        self._reload_tags()

    def _remove_tag(self, tag_id: int) -> None:
        if not self._current_date:
            return
        tags = self._db.get_tags_for_page(self._current_date)
        remaining = [name for (tid, name, _color) in tags if tid != tag_id]
        self._db.set_tags_for_page(self._current_date, remaining)
        self._reload_tags()

    def _open_manager(self) -> None:
        from .tags_dialog import TagManagerDialog

        dlg = TagManagerDialog(self._db, self)
        if dlg.exec():
            # Names/colours may have changed
            if self._current_date:
                self._reload_tags()

    def _on_chip_clicked(self, name: str) -> None:
        self.tagActivated.emit(name)
