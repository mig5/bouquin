from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QColorDialog,
    QMessageBox,
)

from . import strings
from .db import DBManager

class TagManagerDialog(QDialog):
    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(strings._("manage_tags"))

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(
            [strings._("tag_name"), strings._("tag_color_hex")]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton(strings._("add"))
        self.remove_btn = QPushButton(strings._("remove"))
        self.color_btn = QPushButton(strings._("pick_color"))
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.remove_btn)
        btn_row.addWidget(self.color_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        action_row = QHBoxLayout()
        ok_btn = QPushButton(strings._("ok"))
        cancel_btn = QPushButton(strings._("cancel"))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        action_row.addStretch(1)
        action_row.addWidget(ok_btn)
        action_row.addWidget(cancel_btn)
        layout.addLayout(action_row)

        self.add_btn.clicked.connect(self._add_row)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.color_btn.clicked.connect(self._pick_color)

        self._load_tags()

    def _load_tags(self) -> None:
        self.table.setRowCount(0)
        for tag_id, name, color in self._db.list_tags():
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, tag_id)
            self.table.setItem(row, 0, name_item)

            color_item = QTableWidgetItem(color)
            color_item.setBackground(Qt.GlobalColor.transparent)
            self.table.setItem(row, 1, color_item)

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem("")
        name_item.setData(Qt.ItemDataRole.UserRole, 0)  # 0 => new tag
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem("#CCCCCC"))

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        tag_id = item.data(Qt.ItemDataRole.UserRole)
        if tag_id:
            self._db.delete_tag(int(tag_id))
        self.table.removeRow(row)

    def _pick_color(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 1)
        current = item.text() or "#CCCCCC"
        color = QColorDialog.getColor()
        if color.isValid():
            item.setText(color.name())

    def accept(self) -> None:
        # Persist all rows back to DB
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            color_item = self.table.item(row, 1)
            if name_item is None or color_item is None:
                continue

            name = name_item.text().strip()
            color = color_item.text().strip() or "#CCCCCC"
            tag_id = int(name_item.data(Qt.ItemDataRole.UserRole) or 0)

            if not name:
                continue  # ignore empty rows

            if not color.startswith("#") or len(color) not in (4, 7):
                QMessageBox.warning(
                    self,
                    strings._("invalid_color_title"),
                    strings._("invalid_color_message"),
                )
                return  # keep dialog open

            if tag_id == 0:
                # new tag: just rely on set_tags_for_page/create, or you can
                # insert here if you like. Easiest is to create via DBManager:
                # use a dummy page or do a direct insert
                self._db.set_tags_for_page("__dummy__", [name])
                # then delete the dummy row; or instead provide a DBManager
                # helper to create a tag explicitly.
            else:
                self._db.update_tag(tag_id, name, color)

        super().accept()
