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
    QCompleter,
)

from . import strings
from .db import DBManager
from .flow_layout import FlowLayout


class TagChip(QFrame):
    removeRequested = Signal(int)  # tag_id
    clicked = Signal(str)  # tag name

    def __init__(
        self,
        tag_id: int,
        name: str,
        color: str,
        parent: QWidget | None = None,
        show_remove: bool = True,
    ):
        super().__init__(parent)
        self._id = tag_id
        self._name = name

        self.setObjectName("TagChip")

        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        color_lbl = QLabel()
        color_lbl.setFixedSize(10, 10)
        color_lbl.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        layout.addWidget(color_lbl)

        name_lbl = QLabel(name)
        layout.addWidget(name_lbl)

        if show_remove:
            btn = QToolButton()
            btn.setText("×")
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda: self.removeRequested.emit(self._id))
            layout.addWidget(btn)

        self.setCursor(Qt.PointingHandCursor)

    @property
    def tag_id(self) -> int:
        return self._id

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._name)
        try:
            super().mouseReleaseEvent(ev)
        except RuntimeError:
            pass


class PageTagsWidget(QFrame):
    """
    Collapsible per-page tag editor shown in the left sidebar.
    Now displays tag chips even when collapsed.
    """

    tagActivated = Signal(str)  # tag name
    tagAdded = Signal()  # emitted when a tag is added to trigger autosave

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

        # Body (chips + add line - only visible when expanded)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(4)

        # Chips container
        self.chip_container = QWidget()
        self.chip_layout = FlowLayout(self.chip_container, hspacing=4, vspacing=4)
        self.body_layout.addWidget(self.chip_container)

        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText(strings._("add_tag_placeholder"))
        self.add_edit.returnPressed.connect(self._on_add_tag)

        # Setup autocomplete
        self._setup_autocomplete()

        self.body_layout.addWidget(self.add_edit)
        self.body.setVisible(False)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(self.body)

    # ----- external API ------------------------------------------------

    def set_current_date(self, date_iso: str) -> None:
        self._current_date = date_iso
        # Only reload tags if expanded
        if self.toggle_btn.isChecked():
            self._reload_tags()
        else:
            self._clear_chips()  # Clear chips when collapsed
        self._setup_autocomplete()  # Update autocomplete with all available tags

    # ----- internals ---------------------------------------------------

    def _setup_autocomplete(self) -> None:
        """Setup autocomplete for the tag input with all existing tags"""
        all_tags = [name for _, name, _ in self._db.list_tags()]
        completer = QCompleter(all_tags, self.add_edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.add_edit.setCompleter(completer)

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked:
            if self._current_date:
                self._reload_tags()
            self.add_edit.setFocus()

    def _clear_chips(self) -> None:
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
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
            # Always show remove button since chips only visible when expanded
            chip = TagChip(tag_id, name, color, self, show_remove=True)
            chip.removeRequested.connect(self._remove_tag)
            chip.clicked.connect(self._on_chip_clicked)
            self.chip_layout.addWidget(chip)
            chip.show()
            chip.adjustSize()

        # Force complete layout recalculation
        self.chip_layout.invalidate()
        self.chip_layout.activate()
        self.chip_container.updateGeometry()
        self.updateGeometry()
        # Process pending events to ensure layout is applied
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()

    def _on_add_tag(self) -> None:
        if not self._current_date:
            return

        # If the completer popup is visible and user pressed Enter,
        # the completer will handle it - don't process it again
        if self.add_edit.completer() and self.add_edit.completer().popup().isVisible():
            return

        new_tag = self.add_edit.text().strip()
        if not new_tag:
            return

        # Get existing tags for current page
        existing = [
            name for _, name, _ in self._db.get_tags_for_page(self._current_date)
        ]

        # Check for duplicates (case-insensitive)
        if any(tag.lower() == new_tag.lower() for tag in existing):
            self.add_edit.clear()
            return

        existing.append(new_tag)
        self._db.set_tags_for_page(self._current_date, existing)

        self.add_edit.clear()
        self._reload_tags()
        self._setup_autocomplete()  # Update autocomplete list

        # Signal that a tag was added so main window can trigger autosave
        self.tagAdded.emit()

    def _remove_tag(self, tag_id: int) -> None:
        if not self._current_date:
            return
        tags = self._db.get_tags_for_page(self._current_date)
        remaining = [name for (tid, name, _color) in tags if tid != tag_id]
        self._db.set_tags_for_page(self._current_date, remaining)
        self._reload_tags()

    def _open_manager(self) -> None:
        from .tag_browser import TagBrowserDialog

        dlg = TagBrowserDialog(self._db, self)
        dlg.openDateRequested.connect(lambda date_iso: self.tagActivated.emit(date_iso))
        if dlg.exec():
            # Reload tags after manager closes to pick up any changes
            if self._current_date:
                self._reload_tags()
                self._setup_autocomplete()

    def _on_chip_clicked(self, name: str) -> None:
        self.tagActivated.emit(name)
