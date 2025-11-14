# tag_browser.py
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
)

from .db import DBManager
from . import strings


class TagBrowserDialog(QDialog):
    openDateRequested = Signal(str)

    def __init__(self, db: DBManager, parent=None, focus_tag: str | None = None):
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(strings._("tag_browser_title"))

        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([strings._("tag"), strings._("date")])
        self.tree.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.tree)

        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._populate(focus_tag)

    def _populate(self, focus_tag: str | None):
        tags = self._db.list_tags()
        focus_item = None
        for tag_id, name, color in tags:
            root = QTreeWidgetItem([name, ""])
            # coloured background or icon:
            root.setData(0, Qt.ItemDataRole.UserRole, name)
            self.tree.addTopLevelItem(root)

            pages = self._db.get_pages_for_tag(name)
            for date_iso, _content in pages:
                child = QTreeWidgetItem(["", date_iso])
                child.setData(0, Qt.ItemDataRole.UserRole, date_iso)
                root.addChild(child)

            if focus_tag and name.lower() == focus_tag.lower():
                focus_item = root

        if focus_item:
            self.tree.expandItem(focus_item)
            self.tree.setCurrentItem(focus_item)

    def _on_item_activated(self, item: QTreeWidgetItem, column: int):
        date_iso = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(date_iso, str) and date_iso:
            self.openDateRequested.emit(date_iso)
