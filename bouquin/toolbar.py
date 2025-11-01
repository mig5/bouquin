from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import QToolBar

class ToolBar(QToolBar):
    boldRequested = Signal(QFont.Weight)
    italicRequested = Signal()
    underlineRequested = Signal()
    strikeRequested = Signal()
    codeRequested = Signal()
    headingRequested = Signal(int)
    bulletsRequested = Signal()
    numbersRequested = Signal()
    alignRequested = Signal(Qt.AlignmentFlag)

    def __init__(self, parent=None):
        super().__init__("Format", parent)
        self._build_actions()

    def _build_actions(self):
        # Bold
        bold = QAction("Bold", self)
        bold.setShortcut("Ctrl+B")
        bold.triggered.connect(lambda: self.boldRequested.emit(QFont.Weight.Bold))

        italic = QAction("Italic", self)
        italic.setShortcut("Ctrl+I")
        italic.triggered.connect(self.italicRequested)

        underline = QAction("Underline", self)
        underline.setShortcut("Ctrl+U")
        underline.triggered.connect(self.underlineRequested)

        strike = QAction("Strikethrough", self)
        strike.setShortcut("Ctrl+-")
        strike.triggered.connect(self.strikeRequested)

        code = QAction("<code>", self)
        code.setShortcut("Ctrl+`")
        code.triggered.connect(self.codeRequested)

        # Headings
        h1 = QAction("H1", self)
        h1.setShortcut("Ctrl+1")
        h2 = QAction("H2", self)
        h2.setShortcut("Ctrl+2")
        h3 = QAction("H3", self)
        h3.setShortcut("Ctrl+3")
        normal = QAction("Normal", self)
        normal.setShortcut("Ctrl+P")

        h1.triggered.connect(lambda: self.headingRequested.emit(24))
        h2.triggered.connect(lambda: self.headingRequested.emit(18))
        h3.triggered.connect(lambda: self.headingRequested.emit(14))
        normal.triggered.connect(lambda: self.headingRequested.emit(0))

        # Lists
        bullets = QAction("• Bullets", self)
        bullets.triggered.connect(self.bulletsRequested)
        numbers = QAction("1. Numbered", self)
        numbers.triggered.connect(self.numbersRequested)

        # Alignment
        left = QAction("Align Left", self)
        center = QAction("Align Center", self)
        right = QAction("Align Right", self)

        left.triggered.connect(
            lambda: self.alignRequested.emit(Qt.AlignmentFlag.AlignLeft)
        )
        center.triggered.connect(
            lambda: self.alignRequested.emit(Qt.AlignmentFlag.AlignHCenter)
        )
        right.triggered.connect(
            lambda: self.alignRequested.emit(Qt.AlignmentFlag.AlignRight)
        )

        self.addActions(
            [
                bold,
                italic,
                underline,
                strike,
                code,
                h1,
                h2,
                h3,
                normal,
                bullets,
                numbers,
                left,
                center,
                right,
            ]
        )
