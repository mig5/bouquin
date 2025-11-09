from __future__ import annotations

import base64
import re
from pathlib import Path

from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QPalette,
    QGuiApplication,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QSyntaxHighlighter,
    QTextImageFormat,
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTextEdit

from .theme import ThemeManager, Theme


class MarkdownHighlighter(QSyntaxHighlighter):
    """Live syntax highlighter for markdown that applies formatting as you type."""

    def __init__(self, document: QTextDocument, theme_manager: ThemeManager):
        super().__init__(document)
        self.theme_manager = theme_manager
        self._setup_formats()
        # Recompute formats whenever the app theme changes
        try:
            self.theme_manager.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

    def _on_theme_changed(self, *_):
        self._setup_formats()
        self.rehighlight()

    def _setup_formats(self):
        """Setup text formats for different markdown elements."""
        # Bold: **text** or __text__
        self.bold_format = QTextCharFormat()
        self.bold_format.setFontWeight(QFont.Weight.Bold)

        # Italic: *text* or _text_
        self.italic_format = QTextCharFormat()
        self.italic_format.setFontItalic(True)

        # Strikethrough: ~~text~~
        self.strike_format = QTextCharFormat()
        self.strike_format.setFontStrikeOut(True)

        # Code: `code`
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.code_format = QTextCharFormat()
        self.code_format.setFont(mono)
        self.code_format.setFontFixedPitch(True)

        # Code block: ```
        self.code_block_format = QTextCharFormat()
        self.code_block_format.setFont(mono)
        self.code_block_format.setFontFixedPitch(True)
        pal = QGuiApplication.palette()
        if self.theme_manager.current() == Theme.DARK:
            # In dark mode, use a darker panel-like background
            bg = pal.color(QPalette.AlternateBase)
            fg = pal.color(QPalette.Text)
        else:
            # Light mode: keep the existing light gray
            bg = QColor(245, 245, 245)
            fg = pal.color(QPalette.Text)
        self.code_block_format.setBackground(bg)
        self.code_block_format.setForeground(fg)

        # Headings
        self.h1_format = QTextCharFormat()
        self.h1_format.setFontPointSize(24.0)
        self.h1_format.setFontWeight(QFont.Weight.Bold)

        self.h2_format = QTextCharFormat()
        self.h2_format.setFontPointSize(18.0)
        self.h2_format.setFontWeight(QFont.Weight.Bold)

        self.h3_format = QTextCharFormat()
        self.h3_format.setFontPointSize(14.0)
        self.h3_format.setFontWeight(QFont.Weight.Bold)

        # Markdown syntax (the markers themselves) - make invisible
        self.syntax_format = QTextCharFormat()
        # Make the markers invisible by setting font size to 0.1 points
        self.syntax_format.setFontPointSize(0.1)
        # Also make them very faint in case they still show
        self.syntax_format.setForeground(QColor(250, 250, 250))

    def highlightBlock(self, text: str):
        """Apply formatting to a block of text based on markdown syntax."""
        if not text:
            return

        # Track if we're in a code block (multiline)
        prev_state = self.previousBlockState()
        in_code_block = prev_state == 1

        # Check for code block fences
        if text.strip().startswith("```"):
            # Toggle code block state
            in_code_block = not in_code_block
            self.setCurrentBlockState(1 if in_code_block else 0)
            # Format the fence markers - but keep them somewhat visible for editing
            # Use code format instead of syntax format so cursor is visible
            self.setFormat(0, len(text), self.code_format)
            return

        if in_code_block:
            # Format entire line as code
            self.setFormat(0, len(text), self.code_block_format)
            self.setCurrentBlockState(1)
            return

        self.setCurrentBlockState(0)

        # Headings (must be at start of line)
        heading_match = re.match(r"^(#{1,3})\s+", text)
        if heading_match:
            level = len(heading_match.group(1))
            marker_len = len(heading_match.group(0))

            # Format the # markers
            self.setFormat(0, marker_len, self.syntax_format)

            # Format the heading text
            heading_fmt = (
                self.h1_format
                if level == 1
                else self.h2_format if level == 2 else self.h3_format
            )
            self.setFormat(marker_len, len(text) - marker_len, heading_fmt)
            return

        # Bold: **text** or __text__
        for match in re.finditer(r"\*\*(.+?)\*\*|__(.+?)__", text):
            start, end = match.span()
            content_start = start + 2
            content_end = end - 2

            # Gray out the markers
            self.setFormat(start, 2, self.syntax_format)
            self.setFormat(end - 2, 2, self.syntax_format)

            # Bold the content
            self.setFormat(content_start, content_end - content_start, self.bold_format)

        # Italic: *text* or _text_ (but not part of bold)
        for match in re.finditer(
            r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", text
        ):
            start, end = match.span()
            # Skip if this is part of a bold pattern
            if start > 0 and text[start - 1 : start + 1] in ("**", "__"):
                continue
            if end < len(text) and text[end : end + 1] in ("*", "_"):
                continue

            content_start = start + 1
            content_end = end - 1

            # Gray out markers
            self.setFormat(start, 1, self.syntax_format)
            self.setFormat(end - 1, 1, self.syntax_format)

            # Italicize content
            self.setFormat(
                content_start, content_end - content_start, self.italic_format
            )

        # Strikethrough: ~~text~~
        for match in re.finditer(r"~~(.+?)~~", text):
            start, end = match.span()
            content_start = start + 2
            content_end = end - 2

            self.setFormat(start, 2, self.syntax_format)
            self.setFormat(end - 2, 2, self.syntax_format)
            self.setFormat(
                content_start, content_end - content_start, self.strike_format
            )

        # Inline code: `code`
        for match in re.finditer(r"`([^`]+)`", text):
            start, end = match.span()
            content_start = start + 1
            content_end = end - 1

            self.setFormat(start, 1, self.syntax_format)
            self.setFormat(end - 1, 1, self.syntax_format)
            self.setFormat(content_start, content_end - content_start, self.code_format)


class MarkdownEditor(QTextEdit):
    """A QTextEdit that stores/loads markdown and provides live rendering."""

    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

    # Checkbox characters (Unicode for display, markdown for storage)
    _CHECK_UNCHECKED_DISPLAY = "☐"
    _CHECK_CHECKED_DISPLAY = "☑"
    _CHECK_UNCHECKED_STORAGE = "[ ]"
    _CHECK_CHECKED_STORAGE = "[x]"

    def __init__(self, theme_manager: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.theme_manager = theme_manager

        # Setup tab width
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        # We accept plain text, not rich text (markdown is plain text)
        self.setAcceptRichText(False)

        # Install syntax highlighter
        self.highlighter = MarkdownHighlighter(self.document(), theme_manager)

        # Track current list type for smart enter handling
        self._last_enter_was_empty = False

        # Track if we're currently updating text programmatically
        self._updating = False

        # Connect to text changes for smart formatting
        self.textChanged.connect(self._on_text_changed)

        # Enable mouse tracking for checkbox clicking
        self.viewport().setMouseTracking(True)

    def setDocument(self, doc):
        super().setDocument(doc)
        # reattach the highlighter to the new document
        if hasattr(self, "highlighter") and self.highlighter:
            self.highlighter.setDocument(self.document())

    def _on_text_changed(self):
        """Handle live formatting updates - convert checkbox markdown to Unicode."""
        if self._updating:
            return

        self._updating = True
        try:
            c = self.textCursor()
            block = c.block()
            line = block.text()
            pos_in_block = c.position() - block.position()

            # Transform only this line:
            #   - "TODO " at start (with optional indent) -> "- ☐ "
            #   - "- [ ] " -> " ☐ "   and   "- [x] " -> " ☑ "
            def transform_line(s: str) -> str:
                s = s.replace("- [x] ", f"{self._CHECK_CHECKED_DISPLAY} ")
                s = s.replace("- [ ] ", f"{self._CHECK_UNCHECKED_DISPLAY} ")
                s = re.sub(
                    r"^([ \t]*)TODO\b[:\-]?\s+",
                    lambda m: f"{m.group(1)}\n{self._CHECK_UNCHECKED_DISPLAY} ",
                    s,
                )
                return s

            new_line = transform_line(line)
            if new_line != line:
                # Replace just the current block
                bc = QTextCursor(block)
                bc.beginEditBlock()
                bc.select(QTextCursor.BlockUnderCursor)
                bc.insertText(new_line)
                bc.endEditBlock()

                # Restore cursor near its original visual position in the edited line
                new_pos = min(
                    block.position() + len(new_line), block.position() + pos_in_block
                )
                c.setPosition(new_pos)
                self.setTextCursor(c)
        finally:
            self._updating = False

    def to_markdown(self) -> str:
        """Export current content as markdown (convert Unicode checkboxes back to markdown)."""
        # First, extract any embedded images and convert to markdown
        text = self._extract_images_to_markdown()

        # Convert Unicode checkboxes back to markdown syntax
        text = text.replace(f"{self._CHECK_CHECKED_DISPLAY} ", "- [x] ")
        text = text.replace(f"{self._CHECK_UNCHECKED_DISPLAY} ", "- [ ] ")

        return text

    def _extract_images_to_markdown(self) -> str:
        """Extract embedded images and convert them back to markdown format."""
        doc = self.document()
        cursor = QTextCursor(doc)

        # Build the output text with images as markdown
        result = []
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        block = doc.begin()
        while block.isValid():
            it = block.begin()
            block_text = ""

            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    if fragment.charFormat().isImageFormat():
                        # This is an image - convert to markdown
                        img_format = fragment.charFormat().toImageFormat()
                        img_name = img_format.name()
                        # The name contains the data URI
                        if img_name.startswith("data:image/"):
                            block_text += f"![image]({img_name})"
                    else:
                        # Regular text
                        block_text += fragment.text()
                it += 1

            result.append(block_text)
            block = block.next()

        return "\n".join(result)

    def from_markdown(self, markdown_text: str):
        """Load markdown text into the editor (convert markdown checkboxes to Unicode)."""
        # Convert markdown checkboxes to Unicode for display
        display_text = markdown_text.replace(
            "- [x] ", f"{self._CHECK_CHECKED_DISPLAY} "
        )
        display_text = display_text.replace(
            "- [ ] ", f"{self._CHECK_UNCHECKED_DISPLAY} "
        )
        # Also convert any plain 'TODO ' at the start of a line to an unchecked checkbox
        display_text = re.sub(
            r"(?m)^([ \t]*)TODO\s",
            lambda m: f"{m.group(1)}\n{self._CHECK_UNCHECKED_DISPLAY} ",
            display_text,
        )

        self._updating = True
        try:
            self.setPlainText(display_text)
            if hasattr(self, "highlighter") and self.highlighter:
                self.highlighter.rehighlight()
        finally:
            self._updating = False

        # Render any embedded images
        self._render_images()

    def _render_images(self):
        """Find and render base64 images in the document."""
        text = self.toPlainText()

        # Pattern for markdown images with base64 data
        img_pattern = r"!\[([^\]]*)\]\(data:image/([^;]+);base64,([^\)]+)\)"

        matches = list(re.finditer(img_pattern, text))

        if not matches:
            return

        # Process matches in reverse to preserve positions
        for match in reversed(matches):
            mime_type = match.group(2)
            b64_data = match.group(3)

            try:
                # Decode base64 to image
                img_bytes = base64.b64decode(b64_data)
                image = QImage.fromData(img_bytes)

                if image.isNull():
                    continue

                # Use original image size - no scaling
                original_width = image.width()
                original_height = image.height()

                # Create image format with original base64
                img_format = QTextImageFormat()
                img_format.setName(f"data:image/{mime_type};base64,{b64_data}")
                img_format.setWidth(original_width)
                img_format.setHeight(original_height)

                # Add image to document resources
                self.document().addResource(
                    QTextDocument.ResourceType.ImageResource, img_format.name(), image
                )

                # Replace markdown with rendered image
                cursor = QTextCursor(self.document())
                cursor.setPosition(match.start())
                cursor.setPosition(match.end(), QTextCursor.MoveMode.KeepAnchor)
                cursor.insertImage(img_format)

            except Exception as e:
                # If image fails to render, leave the markdown as-is
                print(f"Failed to render image: {e}")
                continue

    def _get_current_line(self) -> str:
        """Get the text of the current line."""
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        return cursor.selectedText()

    def _detect_list_type(self, line: str) -> tuple[str | None, str]:
        """
        Detect if line is a list item. Returns (list_type, prefix).
        list_type: 'bullet', 'number', 'checkbox', or None
        prefix: the actual prefix string to use (e.g., '- ', '1. ', '- ☐ ')
        """
        line = line.lstrip()

        # Checkbox list (Unicode display format)
        if line.startswith(f"{self._CHECK_UNCHECKED_DISPLAY} ") or line.startswith(
            f"{self._CHECK_CHECKED_DISPLAY} "
        ):
            return ("checkbox", f"{self._CHECK_UNCHECKED_DISPLAY} ")

        # Bullet list
        if re.match(r"^[-*+]\s", line):
            match = re.match(r"^([-*+]\s)", line)
            return ("bullet", match.group(1))

        # Numbered list
        if re.match(r"^\d+\.\s", line):
            # Extract the number and increment
            match = re.match(r"^(\d+)\.\s", line)
            num = int(match.group(1))
            return ("number", f"{num + 1}. ")

        return (None, "")

    def keyPressEvent(self, event):
        """Handle special key events for markdown editing."""

        # Handle Enter key for smart list continuation AND code blocks
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            cursor = self.textCursor()
            current_line = self._get_current_line()

            # Check if we're in a code block
            current_block = cursor.block()
            line_text = current_block.text()
            pos_in_block = cursor.position() - current_block.position()

            moved = False
            i = 0
            patterns = ["**", "__", "~~", "`", "*", "_"]  # bold, italic, strike, code
            # Consume stacked markers like **` if present
            while True:
                matched = False
                for pat in patterns:
                    L = len(pat)
                    if line_text[pos_in_block + i : pos_in_block + i + L] == pat:
                        i += L
                        matched = True
                        moved = True
                        break
                if not matched:
                    break
            if moved:
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, i
                )
                self.setTextCursor(cursor)

            block_state = current_block.userState()

            # If current line is opening code fence, or we're inside a code block
            if current_line.strip().startswith("```") or block_state == 1:
                # Just insert a regular newline - the highlighter will format it as code
                super().keyPressEvent(event)
                return

            # Check for list continuation
            list_type, prefix = self._detect_list_type(current_line)

            if list_type:
                # Check if the line is empty (just the prefix)
                content = current_line.lstrip()
                is_empty = (
                    content == prefix.strip() or not content.replace(prefix, "").strip()
                )

                if is_empty and self._last_enter_was_empty:
                    # Second enter on empty list item - remove the list formatting
                    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                    cursor.removeSelectedText()
                    cursor.insertText("\n")
                    self._last_enter_was_empty = False
                    return
                elif is_empty:
                    # First enter on empty list item - remember this
                    self._last_enter_was_empty = True
                else:
                    # Not empty - continue the list
                    self._last_enter_was_empty = False

                # Insert newline and continue the list
                super().keyPressEvent(event)
                cursor = self.textCursor()
                cursor.insertText(prefix)
                return
            else:
                self._last_enter_was_empty = False
        else:
            # Any other key resets the empty enter flag
            self._last_enter_was_empty = False

        # Default handling
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse clicks - check for checkbox clicking."""
        if event.button() == Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            line = cursor.selectedText()

            # Check if clicking on a checkbox line
            if (
                f"{self._CHECK_UNCHECKED_DISPLAY} " in line
                or f"{self._CHECK_CHECKED_DISPLAY} " in line
            ):
                # Toggle the checkbox
                if f"{self._CHECK_UNCHECKED_DISPLAY} " in line:
                    new_line = line.replace(
                        f"{self._CHECK_UNCHECKED_DISPLAY} ",
                        f"{self._CHECK_CHECKED_DISPLAY} ",
                    )
                else:
                    new_line = line.replace(
                        f"{self._CHECK_CHECKED_DISPLAY} ",
                        f"{self._CHECK_UNCHECKED_DISPLAY} ",
                    )

                cursor.insertText(new_line)
                # Don't call super() - we handled the click
                return

        # Default handling for non-checkbox clicks
        super().mousePressEvent(event)

    # ------------------------ Toolbar action handlers ------------------------

    def apply_weight(self):
        """Toggle bold formatting."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            # Check if already bold
            if selected.startswith("**") and selected.endswith("**"):
                # Remove bold
                new_text = selected[2:-2]
            else:
                # Add bold
                new_text = f"**{selected}**"
            cursor.insertText(new_text)
        else:
            # No selection - just insert markers
            cursor.insertText("****")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 2
            )
            self.setTextCursor(cursor)

        # Return focus to editor
        self.setFocus()

    def apply_italic(self):
        """Toggle italic formatting."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            if (
                selected.startswith("*")
                and selected.endswith("*")
                and not selected.startswith("**")
            ):
                new_text = selected[1:-1]
            else:
                new_text = f"*{selected}*"
            cursor.insertText(new_text)
        else:
            cursor.insertText("**")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 1
            )
            self.setTextCursor(cursor)

        # Return focus to editor
        self.setFocus()

    def apply_strikethrough(self):
        """Toggle strikethrough formatting."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            if selected.startswith("~~") and selected.endswith("~~"):
                new_text = selected[2:-2]
            else:
                new_text = f"~~{selected}~~"
            cursor.insertText(new_text)
        else:
            cursor.insertText("~~~~")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 2
            )
            self.setTextCursor(cursor)

        # Return focus to editor
        self.setFocus()

    def apply_code(self):
        """Insert or toggle code block."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            # Wrap selection in code fence
            selected = cursor.selectedText()
            # Note: selectedText() uses Unicode paragraph separator, replace with newline
            selected = selected.replace("\u2029", "\n")
            new_text = f"```\n{selected}\n```"
            cursor.insertText(new_text)
        else:
            # Insert code block template
            cursor.insertText("```\n\n```")
            cursor.movePosition(
                QTextCursor.MoveOperation.Up, QTextCursor.MoveMode.MoveAnchor, 1
            )
            self.setTextCursor(cursor)

        # Return focus to editor
        self.setFocus()

    def apply_heading(self, size: int):
        """Apply heading formatting to current line."""
        cursor = self.textCursor()

        # Determine heading level from size
        if size >= 24:
            level = 1
        elif size >= 18:
            level = 2
        elif size >= 14:
            level = 3
        else:
            level = 0  # Normal text

        # Get current line
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        line = cursor.selectedText()

        # Remove existing heading markers
        line = re.sub(r"^#{1,6}\s+", "", line)

        # Add new heading markers if not normal
        if level > 0:
            new_line = "#" * level + " " + line
        else:
            new_line = line

        cursor.insertText(new_line)

        # Return focus to editor
        self.setFocus()

    def toggle_bullets(self):
        """Toggle bullet list on current line."""
        cursor = self.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        line = cursor.selectedText()

        # Check if already a bullet
        if line.lstrip().startswith("- ") or line.lstrip().startswith("* "):
            # Remove bullet
            new_line = re.sub(r"^\s*[-*]\s+", "", line)
        else:
            # Add bullet
            new_line = "- " + line.lstrip()

        cursor.insertText(new_line)

        # Return focus to editor
        self.setFocus()

    def toggle_numbers(self):
        """Toggle numbered list on current line."""
        cursor = self.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        line = cursor.selectedText()

        # Check if already numbered
        if re.match(r"^\s*\d+\.\s", line):
            # Remove number
            new_line = re.sub(r"^\s*\d+\.\s+", "", line)
        else:
            # Add number
            new_line = "1. " + line.lstrip()

        cursor.insertText(new_line)

        # Return focus to editor
        self.setFocus()

    def toggle_checkboxes(self):
        """Toggle checkbox on current line."""
        cursor = self.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor
        )
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        line = cursor.selectedText()

        # Check if already has checkbox (Unicode display format)
        if (
            f"{self._CHECK_UNCHECKED_DISPLAY} " in line
            or f"{self._CHECK_CHECKED_DISPLAY} " in line
        ):
            # Remove checkbox - use raw string to avoid escape sequence warning
            new_line = re.sub(
                rf"^\s*[{self._CHECK_UNCHECKED_DISPLAY}{self._CHECK_CHECKED_DISPLAY}]\s+",
                "",
                line,
            )
        else:
            # Add checkbox (Unicode display format)
            new_line = f"{self._CHECK_UNCHECKED_DISPLAY} " + line.lstrip()

        cursor.insertText(new_line)

        # Return focus to editor
        self.setFocus()

    def insert_image_from_path(self, path: Path):
        """Insert an image as rendered image (but save as base64 markdown)."""
        if not path.exists():
            return

        # Read the ORIGINAL image file bytes for base64 encoding
        with open(path, "rb") as f:
            img_data = f.read()

        # Encode ORIGINAL file bytes to base64
        b64_data = base64.b64encode(img_data).decode("ascii")

        # Determine mime type
        ext = path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "image/png")

        # Load the image
        image = QImage(str(path))
        if image.isNull():
            return

        # Use ORIGINAL size - no scaling!
        original_width = image.width()
        original_height = image.height()

        # Create image format with original base64
        img_format = QTextImageFormat()
        img_format.setName(f"data:image/{mime_type};base64,{b64_data}")
        img_format.setWidth(original_width)
        img_format.setHeight(original_height)

        # Add ORIGINAL image to document resources
        self.document().addResource(
            QTextDocument.ResourceType.ImageResource, img_format.name(), image
        )

        # Insert the image at original size
        cursor = self.textCursor()
        cursor.insertImage(img_format)
        cursor.insertText("\n")  # Add newline after image
