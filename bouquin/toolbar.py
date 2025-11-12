from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QAction, QKeySequence, QFont, QFontDatabase, QActionGroup
from PySide6.QtWidgets import QToolBar

from . import strings


class ToolBar(QToolBar):
    boldRequested = Signal()
    italicRequested = Signal()
    strikeRequested = Signal()
    codeRequested = Signal()
    headingRequested = Signal(int)
    bulletsRequested = Signal()
    numbersRequested = Signal()
    checkboxesRequested = Signal()
    historyRequested = Signal()
    insertImageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(strings._("toolbar_format"), parent)
        self.setObjectName(strings._("toolbar_format"))
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._build_actions()
        self._apply_toolbar_styles()

    def _build_actions(self):
        self.actBold = QAction("B", self)
        self.actBold.setToolTip(strings._("toolbar_bold"))
        self.actBold.setCheckable(True)
        self.actBold.setShortcut(QKeySequence.Bold)
        self.actBold.triggered.connect(self.boldRequested)

        self.actItalic = QAction("I", self)
        self.actItalic.setToolTip(strings._("toolbar_italic"))
        self.actItalic.setCheckable(True)
        self.actItalic.setShortcut(QKeySequence.Italic)
        self.actItalic.triggered.connect(self.italicRequested)

        self.actStrike = QAction("S", self)
        self.actStrike.setToolTip(strings._("toolbar_strikethrough"))
        self.actStrike.setCheckable(True)
        self.actStrike.setShortcut("Ctrl+-")
        self.actStrike.triggered.connect(self.strikeRequested)

        self.actCode = QAction("</>", self)
        self.actCode.setToolTip(strings._("toolbar_code_block"))
        self.actCode.setShortcut("Ctrl+`")
        self.actCode.triggered.connect(self.codeRequested)

        # Headings
        self.actH1 = QAction("H1", self)
        self.actH1.setToolTip(strings._("toolbar_heading") + " 1")
        self.actH1.setCheckable(True)
        self.actH1.setShortcut("Ctrl+1")
        self.actH1.triggered.connect(lambda: self.headingRequested.emit(24))
        self.actH2 = QAction("H2", self)
        self.actH2.setToolTip(strings._("toolbar_heading") + " 2")
        self.actH2.setCheckable(True)
        self.actH2.setShortcut("Ctrl+2")
        self.actH2.triggered.connect(lambda: self.headingRequested.emit(18))
        self.actH3 = QAction("H3", self)
        self.actH3.setToolTip(strings._("toolbar_heading") + " 3")
        self.actH3.setCheckable(True)
        self.actH3.setShortcut("Ctrl+3")
        self.actH3.triggered.connect(lambda: self.headingRequested.emit(14))
        self.actNormal = QAction("N", self)
        self.actNormal.setToolTip(strings._("toolbar_normal_paragraph_text"))
        self.actNormal.setCheckable(True)
        self.actNormal.setShortcut("Ctrl+N")
        self.actNormal.triggered.connect(lambda: self.headingRequested.emit(0))

        # Lists
        self.actBullets = QAction("•", self)
        self.actBullets.setToolTip(strings._("toolbar_bulleted_list"))
        self.actBullets.setCheckable(True)
        self.actBullets.triggered.connect(self.bulletsRequested)
        self.actNumbers = QAction("1.", self)
        self.actNumbers.setToolTip(strings._("toolbar_numbered_list"))
        self.actNumbers.setCheckable(True)
        self.actNumbers.triggered.connect(self.numbersRequested)
        self.actCheckboxes = QAction("☐", self)
        self.actCheckboxes.setToolTip(strings._("toolbar_toggle_checkboxes"))
        self.actCheckboxes.triggered.connect(self.checkboxesRequested)

        # Images
        self.actInsertImg = QAction(strings._("images"), self)
        self.actInsertImg.setToolTip(strings._("insert_images"))
        self.actInsertImg.setShortcut("Ctrl+Shift+I")
        self.actInsertImg.triggered.connect(self.insertImageRequested)

        # History button
        self.actHistory = QAction(strings._("history"), self)
        self.actHistory.triggered.connect(self.historyRequested)

        # Set exclusive buttons in QActionGroups
        self.grpHeadings = QActionGroup(self)
        self.grpHeadings.setExclusive(True)
        for a in (
            self.actBold,
            self.actItalic,
            self.actStrike,
            self.actH1,
            self.actH2,
            self.actH3,
            self.actNormal,
        ):
            a.setCheckable(True)
            a.setActionGroup(self.grpHeadings)

        self.grpLists = QActionGroup(self)
        self.grpLists.setExclusive(True)
        for a in (self.actBullets, self.actNumbers, self.actCheckboxes):
            a.setActionGroup(self.grpLists)

        # Add actions
        self.addActions(
            [
                self.actBold,
                self.actItalic,
                self.actStrike,
                self.actCode,
                self.actH1,
                self.actH2,
                self.actH3,
                self.actNormal,
                self.actBullets,
                self.actNumbers,
                self.actCheckboxes,
                self.actInsertImg,
                self.actHistory,
            ]
        )

    def _apply_toolbar_styles(self):
        self._style_letter_button(self.actBold, "B", bold=True)
        self._style_letter_button(self.actItalic, "I", italic=True)
        self._style_letter_button(self.actStrike, "S", strike=True)
        # Monospace look for code; use a fixed font
        code_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._style_letter_button(self.actCode, "</>", custom_font=code_font)

        # Headings
        self._style_letter_button(self.actH1, "H1")
        self._style_letter_button(self.actH2, "H2")
        self._style_letter_button(self.actH3, "H3")
        self._style_letter_button(self.actNormal, "N")

        # Lists
        self._style_letter_button(self.actBullets, "•")
        self._style_letter_button(self.actNumbers, "1.")

        # History
        self._style_letter_button(self.actHistory, strings._("view_history"))

    def _style_letter_button(
        self,
        action: QAction,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        strike: bool = False,
        custom_font: QFont | None = None,
        tooltip: str | None = None,
    ):
        btn = self.widgetForAction(action)
        if not btn:
            return
        btn.setText(text)

        f = custom_font if custom_font is not None else QFont(btn.font())
        if custom_font is None:
            f.setBold(bold)
            f.setItalic(italic)
            f.setUnderline(underline)
            f.setStrikeOut(strike)
        btn.setFont(f)

        # Keep accessibility/tooltip readable
        if tooltip:
            btn.setToolTip(tooltip)
            btn.setAccessibleName(tooltip)
