from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QFont, QFontDatabase, QKeySequence
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
    alarmRequested = Signal()
    timerRequested = Signal()
    documentsRequested = Signal()
    fontSizeLargerRequested = Signal()
    fontSizeSmallerRequested = Signal()

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
        self.actNormal = QAction("P", self)
        self.actNormal.setToolTip(strings._("toolbar_normal_paragraph_text"))
        self.actNormal.setCheckable(True)
        self.actNormal.setShortcut("Ctrl+.")
        self.actNormal.triggered.connect(lambda: self.headingRequested.emit(0))

        self.actFontSmaller = QAction("P-", self)
        self.actFontSmaller.setToolTip(strings._("toolbar_font_smaller"))
        self.actFontSmaller.setShortcut("Ctrl+Shift+-")
        self.actFontSmaller.triggered.connect(self.fontSizeSmallerRequested)

        self.actFontLarger = QAction("P+", self)
        self.actFontLarger.setToolTip(strings._("toolbar_font_larger"))
        self.actFontLarger.setShortcut("Ctrl+Shift+=")
        self.actFontLarger.triggered.connect(self.fontSizeLargerRequested)

        # Lists
        self.actBullets = QAction("•", self)
        self.actBullets.setToolTip(strings._("toolbar_bulleted_list"))
        self.actBullets.setCheckable(True)
        self.actBullets.triggered.connect(self.bulletsRequested)
        self.actNumbers = QAction("1.", self)
        self.actNumbers.setToolTip(strings._("toolbar_numbered_list"))
        self.actNumbers.setCheckable(True)
        self.actNumbers.triggered.connect(self.numbersRequested)
        self.actCheckboxes = QAction("☑", self)
        self.actCheckboxes.setToolTip(strings._("toolbar_toggle_checkboxes"))
        self.actCheckboxes.setCheckable(True)
        self.actCheckboxes.triggered.connect(self.checkboxesRequested)

        # Images
        self.actInsertImg = QAction("📸", self)
        self.actInsertImg.setToolTip(strings._("insert_images"))
        self.actInsertImg.setShortcut("Ctrl+Shift+I")
        self.actInsertImg.triggered.connect(self.insertImageRequested)

        # History button
        self.actHistory = QAction("↺", self)
        self.actHistory.setToolTip(strings._("history"))
        self.actHistory.triggered.connect(self.historyRequested)

        # Alarm / reminder
        self.actAlarm = QAction("⏰", self)
        self.actAlarm.setToolTip(strings._("toolbar_alarm"))
        self.actAlarm.triggered.connect(self.alarmRequested)

        # Focus timer
        self.actTimer = QAction("⌛", self)
        self.actTimer.setToolTip(strings._("toolbar_pomodoro_timer"))
        self.actTimer.setCheckable(True)
        self.actTimer.triggered.connect(self.timerRequested)

        # Documents
        self.actDocuments = QAction("📁", self)
        self.actDocuments.setToolTip(strings._("toolbar_documents"))
        self.actDocuments.triggered.connect(self.documentsRequested)
        # Headings are mutually exclusive (like radio buttons)
        self.grpHeadings = QActionGroup(self)
        self.grpHeadings.setExclusive(True)
        for a in (self.actH1, self.actH2, self.actH3, self.actNormal):
            a.setCheckable(True)
            a.setActionGroup(self.grpHeadings)

        # List types are mutually exclusive
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
                self.actFontSmaller,
                self.actFontLarger,
                self.actBullets,
                self.actNumbers,
                self.actCheckboxes,
                self.actInsertImg,
                self.actAlarm,
                self.actTimer,
                self.actDocuments,
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
        self._style_letter_button(self.actNormal, "P")
        self._style_letter_button(self.actFontSmaller, "P-")
        self._style_letter_button(self.actFontLarger, "P+")

        # Lists
        self._style_letter_button(self.actBullets, "•")
        self._style_letter_button(self.actNumbers, "1.")
        self._style_letter_button(self.actCheckboxes, "☑")
        self._style_letter_button(self.actAlarm, "⏰")
        self._style_letter_button(self.actTimer, "⌛")
        self._style_letter_button(self.actDocuments, "📁")

        # History
        self._style_letter_button(self.actHistory, "↺")

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
