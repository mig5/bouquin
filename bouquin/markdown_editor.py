from __future__ import annotations

import base64
import re
from pathlib import Path

from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QImage,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
)
from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtWidgets import QTextEdit

from .theme import ThemeManager
from .markdown_highlighter import MarkdownHighlighter


class MarkdownEditor(QTextEdit):
    """A QTextEdit that stores/loads markdown and provides live rendering."""

    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

    def __init__(self, theme_manager: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.theme_manager = theme_manager

        # Setup tab width
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        # We accept plain text, not rich text (markdown is plain text)
        self.setAcceptRichText(False)

        # Normal text
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        # Checkbox characters (Unicode for display, markdown for storage)
        self._CHECK_UNCHECKED_DISPLAY = "☐"
        self._CHECK_CHECKED_DISPLAY = "☑"
        self._CHECK_UNCHECKED_STORAGE = "[ ]"
        self._CHECK_CHECKED_STORAGE = "[x]"

        # Install syntax highlighter
        self.highlighter = MarkdownHighlighter(self.document(), theme_manager)

        # Track current list type for smart enter handling
        self._last_enter_was_empty = False

        # Track if we're currently updating text programmatically
        self._updating = False

        # Connect to text changes for smart formatting
        self.textChanged.connect(self._on_text_changed)
        self.textChanged.connect(self._update_code_block_row_backgrounds)
        self.theme_manager.themeChanged.connect(
            lambda *_: self._update_code_block_row_backgrounds()
        )

        # Enable mouse tracking for checkbox clicking
        self.viewport().setMouseTracking(True)

    def setDocument(self, doc):
        super().setDocument(doc)
        # reattach the highlighter to the new document
        if hasattr(self, "highlighter") and self.highlighter:
            self.highlighter.setDocument(self.document())
        QTimer.singleShot(0, self._update_code_block_row_backgrounds)

    def showEvent(self, e):
        super().showEvent(e)
        # First time the widget is shown, Qt may rebuild layout once more.
        QTimer.singleShot(0, self._update_code_block_row_backgrounds)

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

            # Transform markldown checkboxes and 'TODO' to unicode checkboxes
            def transform_line(s: str) -> str:
                s = s.replace(
                    f"- {self._CHECK_CHECKED_STORAGE} ",
                    f"{self._CHECK_CHECKED_DISPLAY} ",
                )
                s = s.replace(
                    f"- {self._CHECK_UNCHECKED_STORAGE} ",
                    f"{self._CHECK_UNCHECKED_DISPLAY} ",
                )
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

    def _is_inside_code_block(self, block):
        """Return True if 'block' is inside a fenced code block (based on fences above)."""
        inside = False
        b = block.previous()
        while b.isValid():
            if b.text().strip().startswith("```"):
                inside = not inside
            b = b.previous()
        return inside

    def _update_code_block_row_backgrounds(self):
        """Paint a full-width background for each line that is in a fenced code block."""
        doc = self.document()
        sels = []

        # Use the same bg color as the highlighter's code block
        bg_brush = self.highlighter.code_block_format.background()

        inside = False
        block = doc.begin()
        while block.isValid():
            text = block.text()
            stripped = text.strip()
            is_fence = stripped.startswith("```")

            paint_this_line = is_fence or inside
            if paint_this_line:
                sel = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                fmt.setBackground(bg_brush)
                fmt.setProperty(QTextFormat.FullWidthSelection, True)
                # mark so we can merge with other selections safely
                fmt.setProperty(QTextFormat.UserProperty, "codeblock_bg")
                sel.format = fmt

                cur = QTextCursor(doc)
                cur.setPosition(
                    block.position()
                )  # collapsed cursor = whole line when FullWidthSelection
                sel.cursor = cur

                sels.append(sel)

            if is_fence:
                inside = not inside

            block = block.next()

        others = [
            s
            for s in self.extraSelections()
            if s.format.property(QTextFormat.UserProperty) != "codeblock_bg"
        ]
        self.setExtraSelections(others + sels)

    def to_markdown(self) -> str:
        """Export current content as markdown."""
        # First, extract any embedded images and convert to markdown
        text = self._extract_images_to_markdown()

        # Convert Unicode checkboxes back to markdown syntax
        text = text.replace(
            f"{self._CHECK_CHECKED_DISPLAY} ", f"- {self._CHECK_CHECKED_STORAGE} "
        )
        text = text.replace(
            f"{self._CHECK_UNCHECKED_DISPLAY} ", f"- {self._CHECK_UNCHECKED_STORAGE} "
        )

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
        """Load markdown text into the editor."""
        # Convert markdown checkboxes to Unicode for display
        display_text = markdown_text.replace(
            f"- {self._CHECK_CHECKED_STORAGE} ", f"{self._CHECK_CHECKED_DISPLAY} "
        )
        display_text = display_text.replace(
            f"- {self._CHECK_UNCHECKED_STORAGE} ", f"{self._CHECK_UNCHECKED_DISPLAY} "
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

        self._update_code_block_row_backgrounds()
        QTimer.singleShot(0, self._update_code_block_row_backgrounds)

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

        # --- Auto-close code fences when typing the 3rd backtick at line start ---
        if event.text() == "`":
            c = self.textCursor()
            block = c.block()
            line = block.text()
            pos_in_block = c.position() - block.position()

            # text before caret on this line
            before = line[:pos_in_block]

            # If we've typed exactly two backticks at line start (or after whitespace),
            # treat this backtick as the "third" and expand to a full fenced block.
            if before.endswith("``") and before.strip() == "``":
                start = (
                    block.position() + pos_in_block - 2
                )  # start of the two backticks

                edit = QTextCursor(self.document())
                edit.beginEditBlock()
                edit.setPosition(start)
                edit.setPosition(start + 2, QTextCursor.KeepAnchor)
                edit.insertText("```\n\n```\n")
                edit.endEditBlock()

                # place caret on the blank line between the fences
                new_pos = start + 4  # after "```\n"
                c.setPosition(new_pos)
                self.setTextCursor(c)
                return
        # Step out of a code block with Down at EOF
        if event.key() == Qt.Key.Key_Down:
            c = self.textCursor()
            b = c.block()
            pos_in_block = c.position() - b.position()
            line = b.text()

            def next_is_closing(bb):
                nb = bb.next()
                return nb.isValid() and nb.text().strip().startswith("```")

            # Case A: caret is on the line BEFORE the closing fence, at EOL → jump after the fence
            if (
                self._is_inside_code_block(b)
                and pos_in_block >= len(line)
                and next_is_closing(b)
            ):
                fence_block = b.next()
                after_fence = fence_block.next()
                if not after_fence.isValid():
                    # make a line after the fence
                    edit = QTextCursor(self.document())
                    endpos = fence_block.position() + len(fence_block.text())
                    edit.setPosition(endpos)
                    edit.insertText("\n")
                    after_fence = fence_block.next()
                c.setPosition(after_fence.position())
                self.setTextCursor(c)
                if hasattr(self, "_update_code_block_row_backgrounds"):
                    self._update_code_block_row_backgrounds()
                return

            # Case B: caret is ON the closing fence, and it's EOF → create a line and move to it
            if (
                b.text().strip().startswith("```")
                and self._is_inside_code_block(b)
                and not b.next().isValid()
            ):
                edit = QTextCursor(self.document())
                edit.setPosition(b.position() + len(b.text()))
                edit.insertText("\n")
                c.setPosition(b.position() + len(b.text()) + 1)
                self.setTextCursor(c)
                if hasattr(self, "_update_code_block_row_backgrounds"):
                    self._update_code_block_row_backgrounds()
                return

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
        """Toggle a checkbox only when the click lands on its icon."""
        if event.button() == Qt.LeftButton:
            pt = event.pos()

            # Cursor and block under the mouse
            cur = self.cursorForPosition(pt)
            block = cur.block()
            text = block.text()

            # The display tokens, e.g. "☐ " / "☑ " (icon + trailing space)
            unchecked = f"{self._CHECK_UNCHECKED_DISPLAY} "
            checked = f"{self._CHECK_CHECKED_DISPLAY} "

            # Helper: rect for a single character at a given doc position
            def char_rect_at(doc_pos, ch):
                c = QTextCursor(self.document())
                c.setPosition(doc_pos)
                # caret rect at char start (viewport coords)
                start_rect = self.cursorRect(c)

                # Use the actual font at this position for an accurate width
                fmt_font = (
                    c.charFormat().font() if c.charFormat().isValid() else self.font()
                )
                fm = QFontMetrics(fmt_font)
                w = max(1, fm.horizontalAdvance(ch))
                return QRect(start_rect.x(), start_rect.y(), w, start_rect.height())

            # Scan the line for any checkbox icons; toggle the one we clicked
            i = 0
            while i < len(text):
                icon = None
                if text.startswith(unchecked, i):
                    icon = self._CHECK_UNCHECKED_DISPLAY
                elif text.startswith(checked, i):
                    icon = self._CHECK_CHECKED_DISPLAY

                if icon:
                    # absolute document position of the icon
                    doc_pos = block.position() + i
                    r = char_rect_at(doc_pos, icon)

                    if r.contains(pt):
                        # Build the replacement: swap ☐ <-> ☑ (keep trailing space)
                        new_icon = (
                            self._CHECK_CHECKED_DISPLAY
                            if icon == self._CHECK_UNCHECKED_DISPLAY
                            else self._CHECK_UNCHECKED_DISPLAY
                        )
                        edit = QTextCursor(self.document())
                        edit.beginEditBlock()
                        edit.setPosition(doc_pos)
                        # icon + space
                        edit.movePosition(
                            QTextCursor.Right, QTextCursor.KeepAnchor, len(icon) + 1
                        )
                        edit.insertText(f"{new_icon} ")
                        edit.endEditBlock()
                        return  # handled

                    # advance past this token
                    i += len(icon) + 1
                else:
                    i += 1

        # Default handling for anything else
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
        """Insert a fenced code block, or navigate fences without creating inline backticks."""
        c = self.textCursor()
        doc = self.document()

        if c.hasSelection():
            # Wrap selection and ensure exactly one newline after the closing fence
            selected = c.selectedText().replace("\u2029", "\n")
            c.insertText(f"```\n{selected.rstrip()}\n```\n")
            if hasattr(self, "_update_code_block_row_backgrounds"):
                self._update_code_block_row_backgrounds()
            self.setFocus()
            return

        block = c.block()
        line = block.text()
        pos_in_block = c.position() - block.position()
        stripped = line.strip()

        # If we're on a fence line, be helpful but never insert inline fences
        if stripped.startswith("```"):
            # Is this fence opening or closing? (look at blocks above)
            inside_before = self._is_inside_code_block(block.previous())
            if inside_before:
                # This fence closes the block → ensure a line after, then move there
                endpos = block.position() + len(line)
                edit = QTextCursor(doc)
                edit.setPosition(endpos)
                if not block.next().isValid():
                    edit.insertText("\n")
                c.setPosition(endpos + 1)
                self.setTextCursor(c)
                if hasattr(self, "_update_code_block_row_backgrounds"):
                    self._update_code_block_row_backgrounds()
                self.setFocus()
                return
            else:
                # Opening fence → move caret to the next line (inside the block)
                nb = block.next()
                if not nb.isValid():
                    e = QTextCursor(doc)
                    e.setPosition(block.position() + len(line))
                    e.insertText("\n")
                    nb = block.next()
                c.setPosition(nb.position())
                self.setTextCursor(c)
                self.setFocus()
                return

        # If we're inside a block (but not on a fence), don't mutate text
        if self._is_inside_code_block(block):
            self.setFocus()
            return

        # Outside any block → create a clean template on its own lines (never inline)
        start_pos = c.position()
        before = line[:pos_in_block]

        edit = QTextCursor(doc)
        edit.beginEditBlock()

        # If there is text before the caret on the line, start the block on a new line
        lead_break = "\n" if before else ""
        # Insert the block; trailing newline guarantees you can Down-arrow out later
        insert = f"{lead_break}```\n\n```\n"
        edit.setPosition(start_pos)
        edit.insertText(insert)
        edit.endEditBlock()

        # Put caret on the blank line inside the block
        c.setPosition(start_pos + len(lead_break) + 4)  # after "```\n"
        self.setTextCursor(c)

        if hasattr(self, "_update_code_block_row_backgrounds"):
            self._update_code_block_row_backgrounds()
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

        # Read the original image file bytes for base64 encoding
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

        # Create image format with original base64
        img_format = QTextImageFormat()
        img_format.setName(f"data:image/{mime_type};base64,{b64_data}")
        img_format.setWidth(image.width())
        img_format.setHeight(image.height())

        # Add original image to document resources
        self.document().addResource(
            QTextDocument.ResourceType.ImageResource, img_format.name(), image
        )

        # Insert the image at original size
        cursor = self.textCursor()
        cursor.insertImage(img_format)
        cursor.insertText("\n")  # Add newline after image
