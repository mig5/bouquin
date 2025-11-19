from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QLabel,
    QColorDialog,
    QMessageBox,
    QInputDialog,
)

from .db import DBManager
from . import strings
from sqlcipher3.dbapi2 import IntegrityError


class TagBrowserDialog(QDialog):
    openDateRequested = Signal(str)
    tagsModified = Signal()

    def __init__(self, db: DBManager, parent=None, focus_tag: str | None = None):
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(
            strings._("tag_browser_title") + " / " + strings._("manage_tags")
        )
        self.resize(600, 500)

        layout = QVBoxLayout(self)

        # Instructions
        instructions = QLabel(strings._("tag_browser_instructions"))
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [strings._("tag"), strings._("color_hex"), strings._("date")]
        )
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 100)
        self.tree.itemActivated.connect(self._on_item_activated)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        layout.addWidget(self.tree)

        # Tag management buttons
        btn_row = QHBoxLayout()

        self.add_tag_btn = QPushButton(strings._("add_a_tag"))
        self.add_tag_btn.clicked.connect(self._add_a_tag)
        btn_row.addWidget(self.add_tag_btn)

        self.edit_name_btn = QPushButton(strings._("edit_tag_name"))
        self.edit_name_btn.clicked.connect(self._edit_tag_name)
        self.edit_name_btn.setEnabled(False)
        btn_row.addWidget(self.edit_name_btn)

        self.change_color_btn = QPushButton(strings._("change_color"))
        self.change_color_btn.clicked.connect(self._change_tag_color)
        self.change_color_btn.setEnabled(False)
        btn_row.addWidget(self.change_color_btn)

        self.delete_btn = QPushButton(strings._("delete_tag"))
        self.delete_btn.clicked.connect(self._delete_tag)
        self.delete_btn.setEnabled(False)
        btn_row.addWidget(self.delete_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._populate(focus_tag)

    def _populate(self, focus_tag: str | None):
        # Disable sorting during population for better performance
        was_sorting = self.tree.isSortingEnabled()
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        tags = self._db.list_tags()
        focus_item = None

        for tag_id, name, color in tags:
            # Create the tree item
            root = QTreeWidgetItem([name, "", ""])
            root.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"type": "tag", "id": tag_id, "name": name, "color": color},
            )

            # Set background color for the second column to show the tag color
            bg_color = QColor(color)
            root.setBackground(1, bg_color)

            # Calculate luminance and set contrasting text color
            # Using relative luminance formula (ITU-R BT.709)
            luminance = (
                0.2126 * bg_color.red()
                + 0.7152 * bg_color.green()
                + 0.0722 * bg_color.blue()
            ) / 255.0
            text_color = QColor(0, 0, 0) if luminance > 0.5 else QColor(255, 255, 255)
            root.setForeground(1, text_color)
            root.setText(1, color)  # Also show the hex code
            root.setTextAlignment(1, Qt.AlignCenter)

            self.tree.addTopLevelItem(root)

            pages = self._db.get_pages_for_tag(name)
            for date_iso, _content in pages:
                child = QTreeWidgetItem(["", "", date_iso])
                child.setData(
                    0, Qt.ItemDataRole.UserRole, {"type": "page", "date": date_iso}
                )
                root.addChild(child)

            if focus_tag and name.lower() == focus_tag.lower():
                focus_item = root

        if focus_item:
            self.tree.expandItem(focus_item)
            self.tree.setCurrentItem(focus_item)

        # Re-enable sorting after population
        self.tree.setSortingEnabled(was_sorting)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Enable/disable buttons based on selection"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            if data.get("type") == "tag":
                self.edit_name_btn.setEnabled(True)
                self.change_color_btn.setEnabled(True)
                self.delete_btn.setEnabled(True)
            else:
                self.edit_name_btn.setEnabled(False)
                self.change_color_btn.setEnabled(False)
                self.delete_btn.setEnabled(False)

    def _on_item_activated(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            if data.get("type") == "page":
                date_iso = data.get("date")
                if date_iso:
                    self.openDateRequested.emit(date_iso)
                    self.accept()

    def _add_a_tag(self):
        """Add a new tag"""

        new_name, ok = QInputDialog.getText(
            self, strings._("add_a_tag"), strings._("new_tag_name"), text=""
        )

        if ok and new_name:
            color = QColorDialog.getColor(QColor(), self)
            if color.isValid():
                try:
                    self._db.add_tag(new_name, color.name())
                    self._populate(None)
                    self.tagsModified.emit()
                except IntegrityError as e:
                    QMessageBox.critical(self, strings._("db_database_error"), str(e))

    def _edit_tag_name(self):
        """Edit the name of the selected tag"""
        item = self.tree.currentItem()
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "tag":
            return

        tag_id = data["id"]
        old_name = data["name"]
        color = data["color"]

        new_name, ok = QInputDialog.getText(
            self, strings._("edit_tag_name"), strings._("new_tag_name"), text=old_name
        )

        if ok and new_name and new_name != old_name:
            try:
                self._db.update_tag(tag_id, new_name, color)
                self._populate(None)
                self.tagsModified.emit()
            except IntegrityError as e:
                QMessageBox.critical(self, strings._("db_database_error"), str(e))

    def _change_tag_color(self):
        """Change the color of the selected tag"""
        item = self.tree.currentItem()
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "tag":
            return

        tag_id = data["id"]
        name = data["name"]
        current_color = data["color"]

        color = QColorDialog.getColor(QColor(current_color), self)
        if color.isValid():
            try:
                self._db.update_tag(tag_id, name, color.name())
                self._populate(None)
                self.tagsModified.emit()
            except IntegrityError as e:
                QMessageBox.critical(self, strings._("db_database_error"), str(e))

    def _delete_tag(self):
        """Delete the selected tag"""
        item = self.tree.currentItem()
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "tag":
            return

        tag_id = data["id"]
        name = data["name"]

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            strings._("delete_tag"),
            strings._("delete_tag_confirm").format(name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._db.delete_tag(tag_id)
            self._populate(None)
            self.tagsModified.emit()
