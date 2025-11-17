from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QDateTime, QObject
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QCursor, QPixmap
from PySide6.QtWidgets import QWidget, QRubberBand, QMessageBox

from . import strings


class ScreenRegionGrabber(QWidget):
    regionCaptured = Signal(QPixmap)

    def __init__(self, screenshot_pixmap: QPixmap, parent=None):
        super().__init__(parent)

        self._screen_pixmap = screenshot_pixmap
        self._selection_rect = QRect()
        self._origin = QPoint()

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setWindowState(Qt.WindowFullScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)

        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._screen_pixmap)

        # Dim everything
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        # Punch a clear hole for the selection, if there is one
        if self._selection_rect.isValid():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(self._selection_rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        else:
            # Placeholder text before first click
            painter.setPen(QColor(255, 255, 255, 220))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                strings._("screenshot_click_and_drag"),
            )

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._origin = event.pos()
        self._selection_rect = QRect(self._origin, self._origin)
        self._rubber_band.setGeometry(self._selection_rect)
        self._rubber_band.show()

    def mouseMoveEvent(self, event):
        if not self._rubber_band.isVisible():
            return
        self._selection_rect = QRect(self._origin, event.pos()).normalized()
        self._rubber_band.setGeometry(self._selection_rect)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if not self._rubber_band.isVisible():
            return

        self._rubber_band.hide()
        rect = self._selection_rect.intersected(self._screen_pixmap.rect())
        if rect.isValid():
            cropped = self._screen_pixmap.copy(rect)
            self.regionCaptured.emit(cropped)
        self.close()

    def keyPressEvent(self, event):
        key = event.key()

        # Enter / Return → accept full screen
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._screen_pixmap is not None and not self._screen_pixmap.isNull():
                self.regionCaptured.emit(self._screen_pixmap)
            self.close()
            return

        # Esc → cancel (no screenshot)
        if key == Qt.Key_Escape:
            self.close()
            return

        # Fallback to default behaviour
        super().keyPressEvent(event)


class ScreenshotMarkdownInserter(QObject):
    """
    Helper that captures a region of the screen, saves it to `images_dir`,
    and inserts a Markdown image reference into the MarkdownEditor.
    """

    def __init__(self, editor, images_dir: Path, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._images_dir = Path(images_dir)
        self._grabber: ScreenRegionGrabber | None = None

    def capture_and_insert(self):
        """
        Starts the screen-region selection overlay. When the user finishes,
        the screenshot is saved and the Markdown is inserted in the editor.
        """
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()

        pixmap = screen.grabWindow(0)
        self._grabber = ScreenRegionGrabber(pixmap)
        self._grabber.regionCaptured.connect(self._on_region_captured)
        self._grabber.show()

    # ------------------------------------------------------------------ internals

    def _on_region_captured(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return

        # Ensure output directory exists
        self._images_dir.mkdir(parents=True, exist_ok=True)

        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmsszzz")
        filename = f"bouquin_screenshot_{timestamp}.png"
        full_path = self._images_dir / filename

        if not pixmap.save(str(full_path), "PNG"):
            QMessageBox.critical(
                self,
                strings._("screenshot"),
                strings._("screenshot_could_not_save"),
            )
            return

        self._insert_markdown_image(full_path)

    def _insert_markdown_image(self, path: Path):
        """
        Insert image into the MarkdownEditor.
        """
        if hasattr(self._editor, "insert_image_from_path"):
            self._editor.insert_image_from_path(path)
            return

        rel = path.name
        markdown = f"![screenshot]({rel})"

        if hasattr(self._editor, "textCursor"):
            cursor = self._editor.textCursor()
            cursor.insertText(markdown)
            self._editor.setTextCursor(cursor)
        else:
            self._editor.insertPlainText(markdown)
