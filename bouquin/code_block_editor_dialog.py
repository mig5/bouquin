from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import strings


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditorWithLineNumbers"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # type: ignore[override]
        self._editor.line_number_area_paint_event(event)


class CodeEditorWithLineNumbers(QPlainTextEdit):
    """QPlainTextEdit with a non-selectable line-number gutter on the left."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Allow Tab to insert indentation (not move focus between widgets)
        self.setTabChangesFocus(False)

        # Track whether we just auto-inserted indentation on Enter
        self._last_enter_was_empty_indent = False

        self._line_number_area = _LineNumberArea(self)

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._line_number_area.update)

        self._update_line_number_area_width()
        self._update_tab_stop_width()

    # ---- layout / sizing -------------------------------------------------

    def setFont(self, font: QFont) -> None:  # type: ignore[override]
        """Ensure tab width stays at 4 spaces when the font changes."""
        super().setFont(font)
        self._update_tab_stop_width()

    def _update_tab_stop_width(self) -> None:
        """Set tab width to 4 spaces."""
        metrics = QFontMetrics(self.font())
        # Tab width = width of 4 space characters
        self.setTabStopDistance(metrics.horizontalAdvance(" ") * 4)

    def line_number_area_width(self) -> int:
        # Enough digits for large-ish code blocks.
        digits = max(2, len(str(max(1, self.blockCount()))))
        fm = QFontMetrics(self._line_number_font())
        return fm.horizontalAdvance("9" * digits) + 8

    def _line_number_font(self) -> QFont:
        """Font to use for line numbers (slightly smaller than main text)."""
        font = self.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() - 1)
        else:
            # fallback for pixel-sized fonts
            font.setPointSizeF(font.pointSizeF() * 0.9)
        return font

    def _update_line_number_area_width(self) -> None:
        margin = self.line_number_area_width()
        self.setViewportMargins(margin, 0, 0, 0)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def _update_line_number_area(self, rect, dy) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    # ---- painting --------------------------------------------------------

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self.palette().base())

        # Use a slightly smaller font for numbers
        painter.setFont(self._line_number_font())

        # Faded colour: same blend used for completed-task text in
        # MarkdownHighlighter (text colour towards background).
        pal = self.palette()
        text_fg = pal.color(QPalette.Text)
        text_bg = pal.color(QPalette.Base)
        t = 0.55  # same factor as completed_task_format
        faded = QColor(
            int(text_fg.red() * (1.0 - t) + text_bg.red() * t),
            int(text_fg.green() * (1.0 - t) + text_bg.green() * t),
            int(text_fg.blue() * (1.0 - t) + text_bg.blue() * t),
        )
        painter.setPen(faded)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        fm = self.fontMetrics()
        line_height = fm.height()
        right_margin = self._line_number_area.width() - 4

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(self.palette().text().color())
                painter.drawText(
                    0,
                    int(top),
                    right_margin,
                    line_height,
                    Qt.AlignRight | Qt.AlignVCenter,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def keyPressEvent(self, event):  # type: ignore[override]
        """Auto-retain indentation on newlines (Tab/space) like the markdown editor.

        Rules:
        - If the current line is indented, Enter inserts a newline + the same indent.
        - If the current line contains only indentation, a *second* Enter clears the indent
          and starts an unindented line (similar to exiting bullets/checkboxes).
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            indent = re.match(r"[ \t]*", block_text).group(0)  # type: ignore[union-attr]

            if indent:
                rest = block_text[len(indent) :]
                indent_only = rest.strip() == ""

                if indent_only and self._last_enter_was_empty_indent:
                    # Second Enter on an indentation-only line: remove that line and
                    # start a fresh, unindented line.
                    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                    cursor.removeSelectedText()
                    cursor.insertText("\n")
                    self.setTextCursor(cursor)
                    self._last_enter_was_empty_indent = False
                    return

                # First Enter: keep indentation
                super().keyPressEvent(event)
                self.textCursor().insertText(indent)
                self._last_enter_was_empty_indent = True
                return

            # No indent -> normal Enter
            self._last_enter_was_empty_indent = False
            super().keyPressEvent(event)
            return

        # Any other key resets the empty-indent-enter flag
        self._last_enter_was_empty_indent = False
        super().keyPressEvent(event)


class CodeBlockEditorDialog(QDialog):
    def __init__(
        self, code: str, language: str | None, parent=None, allow_delete: bool = False
    ):
        super().__init__(parent)
        self.setWindowTitle(strings._("edit_code_block"))

        self.setMinimumSize(650, 650)
        self._code_edit = CodeEditorWithLineNumbers(self)
        self._code_edit.setPlainText(code)

        # Track whether the user clicked "Delete"
        self._delete_requested = False

        # Language selector (optional)
        self._lang_combo = QComboBox(self)
        languages = [
            "",
            "bash",
            "css",
            "html",
            "javascript",
            "php",
            "python",
        ]
        self._lang_combo.addItems(languages)
        if language and language in languages:
            self._lang_combo.setCurrentText(language)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if allow_delete:
            delete_btn = buttons.addButton(
                strings._("delete_code_block"),
                QDialogButtonBox.ButtonRole.DestructiveRole,
            )
            delete_btn.clicked.connect(self._on_delete_clicked)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(strings._("locale") + ":", self))
        layout.addWidget(self._lang_combo)
        layout.addWidget(self._code_edit)
        layout.addWidget(buttons)

    def _on_delete_clicked(self) -> None:
        """Mark this dialog as 'delete requested' and close as Accepted."""
        self._delete_requested = True
        self.accept()

    def was_deleted(self) -> bool:
        """Return True if the user chose to delete the code block."""
        return self._delete_requested

    def code(self) -> str:
        return self._code_edit.toPlainText()

    def language(self) -> str | None:
        text = self._lang_combo.currentText().strip()
        return text or None
