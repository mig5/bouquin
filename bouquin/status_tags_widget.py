from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
)

from .flow_layout import FlowLayout
from .db import DBManager
from .tags_widget import TagChip  # reuse, or make a smaller variant if you prefer


class StatusBarTagsWidget(QWidget):
    tagActivated = Signal(str)  # tag name

    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._current_date_iso: str | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(4)

        label = QLabel("Tags:")
        outer.addWidget(label)

        self.flow = FlowLayout(self, hspacing=2, vspacing=2)
        outer.addLayout(self.flow)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_current_page(self, date_iso: str):
        self._current_date_iso = date_iso
        self._reload()

    def _clear(self):
        while self.flow.count():
            item = self.flow.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _reload(self):
        self._clear()
        if not self._current_date_iso:
            return

        tags = self._db.get_tags_for_page(self._current_date_iso)
        # Keep it small; maybe only first N tags:
        MAX_TAGS = 6
        for i, (tid, name, color) in enumerate(tags):
            if i >= MAX_TAGS:
                more = QLabel("…")
                self.flow.addWidget(more)
                break
            chip = TagChip(tid, name, color, self)
            chip.clicked.connect(self.tagActivated)
            # In status bar you might want a smaller style: adjust chip's stylesheet if needed.
            self.flow.addWidget(chip)
