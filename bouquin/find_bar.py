from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QShortcut,
    QTextCursor,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QCheckBox,
    QTextEdit,
)

from . import strings


class FindBar(QWidget):
    """Widget for finding text in the Editor"""

    # emitted when the bar is hidden (Esc/✕), so caller can refocus editor
    closed = Signal()

    def __init__(
        self,
        editor: QTextEdit,
        shortcut_parent: QWidget | None = None,
        parent: QWidget | None = None,
    ):

        super().__init__(parent)

        # store how to get the current editor
        self._editor_getter = editor if callable(editor) else (lambda: editor)
        self.shortcut_parent = shortcut_parent

        # UI (build ONCE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)

        layout.addWidget(QLabel(strings._("find")))

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(strings._("find_bar_type_to_search"))
        layout.addWidget(self.edit)

        self.case = QCheckBox(strings._("find_bar_match_case"), self)
        layout.addWidget(self.case)

        self.prevBtn = QPushButton(strings._("previous"), self)
        self.nextBtn = QPushButton(strings._("next"), self)
        self.closeBtn = QPushButton("✕", self)
        self.closeBtn.setFlat(True)
        layout.addWidget(self.prevBtn)
        layout.addWidget(self.nextBtn)
        layout.addWidget(self.closeBtn)

        self.setVisible(False)

        # Shortcut (press Esc to hide bar)
        sp = (
            self.shortcut_parent
            if self.shortcut_parent is not None
            else (self.parent() or self)
        )
        QShortcut(Qt.Key_Escape, sp, activated=self._maybe_hide)

        # Signals (connect ONCE)
        self.edit.returnPressed.connect(self.find_next)
        self.edit.textChanged.connect(self._update_highlight)
        self.case.toggled.connect(self._update_highlight)
        self.nextBtn.clicked.connect(self.find_next)
        self.prevBtn.clicked.connect(self.find_prev)
        self.closeBtn.clicked.connect(self.hide_bar)

    @property
    def editor(self) -> QTextEdit | None:
        """Get the current editor"""
        return self._editor_getter()

    # ----- Public API -----

    def show_bar(self):
        """Show the bar, seed with current selection if sensible, focus the line edit."""
        if not self.editor:
            return
        tc = self.editor.textCursor()
        sel = tc.selectedText().strip()
        if sel and "\u2029" not in sel:  # ignore multi-paragraph selections
            self.edit.setText(sel)
        self.setVisible(True)
        self.edit.setFocus(Qt.ShortcutFocusReason)
        self.edit.selectAll()
        self._update_highlight()

    def hide_bar(self):
        self.setVisible(False)
        self._clear_highlight()
        self.closed.emit()

    def refresh(self):
        """Recompute highlights"""
        self._update_highlight()

    # ----- Internals -----

    def _maybe_hide(self):
        if self.isVisible():
            self.hide_bar()

    def _flags(self, backward: bool = False) -> QTextDocument.FindFlags:
        flags = QTextDocument.FindFlags()
        if backward:
            flags |= QTextDocument.FindBackward
        if self.case.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        return flags

    def find_next(self):
        if not self.editor:
            return
        txt = self.edit.text()
        if not txt:
            return
        # If current selection == query, bump caret to the end so we don't re-match it.
        c = self.editor.textCursor()
        if c.hasSelection():
            sel = c.selectedText()
            same = (
                (sel == txt)
                if self.case.isChecked()
                else (sel.casefold() == txt.casefold())
            )
            if same:
                end = max(c.position(), c.anchor())
                c.setPosition(end, QTextCursor.MoveAnchor)
                self.editor.setTextCursor(c)
        if not self.editor.find(txt, self._flags(False)):
            cur = self.editor.textCursor()
            cur.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cur)
            self.editor.find(txt, self._flags(False))
        self.editor.ensureCursorVisible()
        self._update_highlight()

    def find_prev(self):
        if not self.editor:
            return
        txt = self.edit.text()
        if not txt:
            return
        # If current selection == query, bump caret to the start so we don't re-match it.
        c = self.editor.textCursor()
        if c.hasSelection():
            sel = c.selectedText()
            same = (
                (sel == txt)
                if self.case.isChecked()
                else (sel.casefold() == txt.casefold())
            )
            if same:
                start = min(c.position(), c.anchor())
                c.setPosition(start, QTextCursor.MoveAnchor)
                self.editor.setTextCursor(c)
        if not self.editor.find(txt, self._flags(True)):
            cur = self.editor.textCursor()
            cur.movePosition(QTextCursor.End)
            self.editor.setTextCursor(cur)
            self.editor.find(txt, self._flags(True))
        self.editor.ensureCursorVisible()
        self._update_highlight()

    def _update_highlight(self):
        if not self.editor:
            return
        txt = self.edit.text()
        if not txt:
            self._clear_highlight()
            return

        doc = self.editor.document()
        flags = self._flags(False)
        cur = QTextCursor(doc)
        cur.movePosition(QTextCursor.Start)

        fmt = QTextCharFormat()
        hl = self.palette().highlight().color()
        hl.setAlpha(90)
        fmt.setBackground(hl)

        selections = []
        while True:
            cur = doc.find(txt, cur, flags)
            if cur.isNull():
                break
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format = fmt
            selections.append(sel)

        self.editor.setExtraSelections(selections)

    def _clear_highlight(self):
        if self.editor:
            self.editor.setExtraSelections([])
