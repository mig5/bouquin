from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
)
from PySide6.QtWidgets import QDialog, QTextEdit

from . import strings
from .code_block_editor_dialog import CodeBlockEditorDialog
from .markdown_highlighter import MarkdownHighlighter
from .theme import ThemeManager


class MarkdownEditor(QTextEdit):
    """A QTextEdit that stores/loads markdown and provides live rendering."""

    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

    # ===== Collapsible sections (editor-only folding) =====
    # We represent a collapsed region as:
    #   <indent>▸ collapse
    #     ... hidden blocks ...
    #   <indent><!-- bouquin:collapse:end -->
    #
    # The end-marker line is always hidden in the editor but preserved in markdown.
    _COLLAPSE_ARROW_COLLAPSED = "▸"
    _COLLAPSE_ARROW_EXPANDED = "▾"
    _COLLAPSE_LABEL_COLLAPSE = "collapse"
    _COLLAPSE_LABEL_EXPAND = "expand"
    _COLLAPSE_END_MARKER = "<!-- bouquin:collapse:end -->"
    # Accept either "collapse" or "expand" in the header text
    _COLLAPSE_HEADER_RE = re.compile(r"^([ \t]*)([▸▾])\s+(?:collapse|expand)\s*$")
    _COLLAPSE_END_RE = re.compile(r"^([ \t]*)<!--\s*bouquin:collapse:end\s*-->\s*$")

    def __init__(self, theme_manager: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.theme_manager = theme_manager

        # Setup tab width
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        # We accept plain text, not rich text (markdown is plain text)
        self.setAcceptRichText(False)

        # Load in our preferred fonts
        base_dir = Path(__file__).resolve().parent

        # Load regular text font (primary)
        regular_font_path = base_dir / "fonts" / "DejaVuSans.ttf"
        regular_font_id = QFontDatabase.addApplicationFont(str(regular_font_path))

        # Load Symbols font (fallback)
        symbols_font_path = base_dir / "fonts" / "NotoSansSymbols2-Regular.ttf"
        symbols_font_id = QFontDatabase.addApplicationFont(str(symbols_font_path))
        symbols_families = QFontDatabase.applicationFontFamilies(symbols_font_id)
        self.symbols_font_family = symbols_families[0]

        # Use the regular Noto Sans family as the editor font
        regular_families = QFontDatabase.applicationFontFamilies(regular_font_id)
        if regular_families:
            self.text_font_family = regular_families[0]
            self.qfont = QFont(self.text_font_family, 11)
            self.setFont(self.qfont)

        self._apply_line_spacing()  # 1.25× initial spacing

        # Checkbox characters (Unicode for display, markdown for storage)
        self._CHECK_UNCHECKED_DISPLAY = "☐"
        self._CHECK_CHECKED_DISPLAY = "☑"
        self._CHECK_UNCHECKED_STORAGE = "[ ]"
        self._CHECK_CHECKED_STORAGE = "[x]"

        # Bullet character (Unicode for display, "- " for markdown)
        self._BULLET_DISPLAY = "•"
        self._BULLET_STORAGE = "-"

        # Install syntax highlighter
        self.highlighter = MarkdownHighlighter(self.document(), theme_manager, self)

        # Initialize code block metadata
        from .code_highlighter import CodeBlockMetadata

        self._code_metadata = CodeBlockMetadata()

        # Track current list type for smart enter handling
        self._last_enter_was_empty = False

        # Track "double-enter" behavior for indentation retention.
        # If we auto-insert indentation on a new line, the next Enter on that
        # now-empty indented line should remove the indentation and return to
        # column 0 (similar to how lists exit on a second Enter).
        self._last_enter_was_empty_indent = False

        # Track if we're currently updating text programmatically
        self._updating = False

        # Track pending inline marker insertion (e.g. Italic with no selection)
        self._pending_inline_marker: str | None = None

        # Help avoid double-click selecting of checkbox
        self._suppress_next_checkbox_double_click = False

        # Guard to avoid recursive selection tweaks
        self._adjusting_selection = False

        # Track when the current selection is being created via mouse drag,
        # so we can treat it differently from triple-click / keyboard selections.
        self._mouse_drag_selecting = False

        # After selections change, trim list prefixes from full-line selections
        # (e.g. after triple-clicking a list item to select the line).
        self.selectionChanged.connect(self._maybe_trim_list_prefix_from_line_selection)

        # Connect to text changes for smart formatting
        self.textChanged.connect(self._on_text_changed)
        self.textChanged.connect(self._update_code_block_row_backgrounds)
        self.theme_manager.themeChanged.connect(
            lambda *_: self._update_code_block_row_backgrounds()
        )

        # Enable mouse tracking for checkbox clicking
        self.viewport().setMouseTracking(True)
        # Also mark links as mouse-accessible
        flags = self.textInteractionFlags()
        self.setTextInteractionFlags(
            flags | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )

    def setDocument(self, doc):
        # Recreate the highlighter for the new document
        # (the old one gets deleted with the old document)
        if doc is None:
            return

        super().setDocument(doc)
        if hasattr(self, "highlighter") and hasattr(self, "theme_manager"):
            self.highlighter = MarkdownHighlighter(
                self.document(), self.theme_manager, self
            )
        self._apply_line_spacing()
        self._apply_code_block_spacing()
        QTimer.singleShot(0, self._update_code_block_row_backgrounds)

    def setFont(self, font: QFont) -> None:  # type: ignore[override]
        """
        Ensure that whenever the base editor font changes, our highlighter
        re-computes checkbox / bullet formats.
        """
        # Keep qfont in sync
        self.qfont = QFont(font)
        super().setFont(self.qfont)

        # If the highlighter is already attached, let it rebuild its formats
        highlighter = getattr(self, "highlighter", None)
        if highlighter is not None:
            refresh = getattr(highlighter, "refresh_for_font_change", None)
            if callable(refresh):
                refresh()

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

            # Transform markdown checkboxes and 'TODO' to unicode checkboxes
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

    def _update_code_block_row_backgrounds(self) -> None:
        """Paint a full-width background behind each fenced ``` code block."""

        doc = self.document()
        if doc is None:
            return

        if not hasattr(self, "highlighter") or self.highlighter is None:
            return

        bg_brush = self.highlighter.code_block_format.background()

        selections: list[QTextEdit.ExtraSelection] = []

        inside = False
        block = doc.begin()
        block_start_pos: int | None = None

        while block.isValid():
            text = block.text()
            stripped = text.strip()
            is_fence = stripped.startswith("```")

            if is_fence:
                if not inside:
                    # Opening fence: remember where this block starts
                    inside = True
                    block_start_pos = block.position()
                else:
                    # Closing fence: create ONE selection from opening fence
                    # to the end of this closing fence block.
                    inside = False
                    if block_start_pos is not None:
                        sel = QTextEdit.ExtraSelection()
                        fmt = QTextCharFormat()
                        fmt.setBackground(bg_brush)
                        fmt.setProperty(QTextFormat.FullWidthSelection, True)
                        fmt.setProperty(QTextFormat.UserProperty, "codeblock_bg")
                        sel.format = fmt

                        cursor = QTextCursor(doc)
                        cursor.setPosition(block_start_pos)
                        # extend to the end of the closing fence block
                        cursor.setPosition(
                            block.position() + block.length() - 1,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        sel.cursor = cursor

                        selections.append(sel)
                        block_start_pos = None

            block = block.next()

        # If the document ends while we're still inside a code block,
        # extend the selection to the end of the document.
        if inside and block_start_pos is not None:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(bg_brush)
            fmt.setProperty(QTextFormat.FullWidthSelection, True)
            fmt.setProperty(QTextFormat.UserProperty, "codeblock_bg")
            sel.format = fmt

            cursor = QTextCursor(doc)
            cursor.setPosition(block_start_pos)
            cursor.movePosition(QTextCursor.End, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor

            selections.append(sel)

        # Keep any other extraSelections (current-line highlight etc.)
        others = [
            s
            for s in self.extraSelections()
            if s.format.property(QTextFormat.UserProperty) != "codeblock_bg"
        ]
        self.setExtraSelections(others + selections)

    def _find_code_block_bounds(
        self, block: QTextBlock
    ) -> Optional[Tuple[QTextBlock, QTextBlock]]:
        """
        Given a block that is either inside a fenced code block or on a fence,
        return (opening_fence_block, closing_fence_block).
        Returns None if we can't find a proper pair.
        """
        if not block.isValid():
            return None

        def is_fence(b: QTextBlock) -> bool:
            return b.isValid() and b.text().strip().startswith("```")

        # If we're on a fence line, decide if it's opening or closing
        if is_fence(block):
            # If we're "inside" just before this fence, this one closes.
            if self._is_inside_code_block(block.previous()):
                close_block = block
                open_block = block.previous()
                while open_block.isValid() and not is_fence(open_block):
                    open_block = open_block.previous()
                if not is_fence(open_block):
                    return None
                return open_block, close_block
            else:
                # Treat as opening fence; search downward for the closing one.
                open_block = block
                close_block = open_block.next()
                while close_block.isValid() and not is_fence(close_block):
                    close_block = close_block.next()
                if not is_fence(close_block):
                    return None
                return open_block, close_block

        # Normal interior line: search up for opening fence, down for closing.
        open_block = block.previous()
        while open_block.isValid() and not is_fence(open_block):
            open_block = open_block.previous()
        if not is_fence(open_block):
            return None

        close_block = open_block.next()
        while close_block.isValid() and not is_fence(close_block):
            close_block = close_block.next()
        if not is_fence(close_block):
            return None

        return open_block, close_block

    def _get_code_block_text(
        self, open_block: QTextBlock, close_block: QTextBlock
    ) -> str:
        """Return the inner text (between fences) as a normal '\\n'-joined string."""
        lines = []
        b = open_block.next()
        while b.isValid() and b != close_block:
            lines.append(b.text())
            b = b.next()
        return "\n".join(lines)

    def _replace_code_block_text(
        self, open_block: QTextBlock, close_block: QTextBlock, new_text: str
    ) -> None:
        """
        Replace everything between the two fences with `new_text`.
        Fences themselves are left untouched.
        """
        doc = self.document()
        if doc is None:
            return

        cursor = QTextCursor(doc)

        # Start just after the opening fence's newline
        start_pos = open_block.position() + len(open_block.text())
        # End at the start of the closing fence
        end_pos = close_block.position()

        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)

        cursor.beginEditBlock()
        # Normalise trailing newline(s)
        new_text = new_text.rstrip("\n")
        if new_text:
            cursor.removeSelectedText()
            cursor.insertText("\n" + new_text + "\n")
        else:
            # Empty block - keep one blank line inside the fences
            cursor.removeSelectedText()
            cursor.insertText("\n\n")
        cursor.endEditBlock()

        # Re-apply spacing and backgrounds
        if hasattr(self, "_apply_code_block_spacing"):
            self._apply_code_block_spacing()
        if hasattr(self, "_update_code_block_row_backgrounds"):
            self._update_code_block_row_backgrounds()

        # Trigger rehighlight
        if hasattr(self, "highlighter"):
            self.highlighter.rehighlight()

    def _edit_code_block(self, block: QTextBlock) -> bool:
        """Open a popup editor for the code block containing `block`.

        Returns True if a dialog was shown (regardless of OK/Cancel),
        False if no well-formed fenced block was found.
        """
        bounds = self._find_code_block_bounds(block)
        if not bounds:
            return False

        open_block, close_block = bounds

        # Current language from metadata (if any)
        lang = None
        if hasattr(self, "_code_metadata"):
            lang = self._code_metadata.get_language(open_block.blockNumber())

        code_text = self._get_code_block_text(open_block, close_block)

        dlg = CodeBlockEditorDialog(code_text, lang, parent=self, allow_delete=True)
        result = dlg.exec()
        if result != QDialog.DialogCode.Accepted:
            # Dialog was shown but user cancelled; event is "handled".
            return True

        # If the user requested deletion, remove the whole block
        if hasattr(dlg, "was_deleted") and dlg.was_deleted():
            self._delete_code_block(open_block)
            return True

        new_code = dlg.code()
        new_lang = dlg.language()

        # Update document text but keep fences
        self._replace_code_block_text(open_block, close_block, new_code)

        # Update metadata language if changed
        if new_lang is not None:
            if not hasattr(self, "_code_metadata"):
                from .code_highlighter import CodeBlockMetadata

                self._code_metadata = CodeBlockMetadata()
            self._code_metadata.set_language(open_block.blockNumber(), new_lang)
            if hasattr(self, "highlighter"):
                self.highlighter.rehighlight()

        return True

    def _delete_code_block(self, block: QTextBlock) -> bool:
        """Delete the fenced code block containing `block`.

        Returns True if a block was deleted, False otherwise.
        """
        bounds = self._find_code_block_bounds(block)
        if not bounds:
            return False

        open_block, close_block = bounds
        fence_block_num = open_block.blockNumber()

        doc = self.document()
        if doc is None:
            return False

        # Remove from the opening fence down to just before the block after
        # the closing fence (so we also remove the trailing blank line).
        start_pos = open_block.position()
        after_block = close_block.next()
        if after_block.isValid():
            end_pos = after_block.position()
        else:
            end_pos = close_block.position() + len(close_block.text())

        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.endEditBlock()

        # Clear language metadata for this block, if supported
        if hasattr(self, "_code_metadata"):
            clear = getattr(self._code_metadata, "clear_language", None)
            if clear is not None and fence_block_num != -1:
                clear(fence_block_num)

        # Refresh visuals (spacing + backgrounds + syntax)
        if hasattr(self, "_apply_code_block_spacing"):
            self._apply_code_block_spacing()
        if hasattr(self, "_update_code_block_row_backgrounds"):
            self._update_code_block_row_backgrounds()
        if hasattr(self, "highlighter"):
            self.highlighter.rehighlight()

        # Move caret to where the block used to be
        cursor = self.textCursor()
        cursor.setPosition(start_pos)
        self.setTextCursor(cursor)
        self.setFocus()

        return True

    def _apply_line_spacing(self, height: float = 125.0):
        """Apply proportional line spacing to the whole document."""
        doc = self.document()
        if doc is None:
            return

        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)

        fmt = QTextBlockFormat()
        fmt.setLineHeight(
            height,  # 125.0 = 1.25×
            QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
        )
        cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()

    def _apply_code_block_spacing(self):
        """
        Make all fenced code-block lines (including ``` fences) single-spaced
        and give them a solid background.
        """
        doc = self.document()
        if doc is None:
            return

        cursor = QTextCursor(doc)
        cursor.beginEditBlock()

        bg_brush = self.highlighter.code_block_format.background()

        inside = False
        block = doc.begin()
        while block.isValid():
            text = block.text()
            stripped = text.strip()
            is_fence = stripped.startswith("```")
            is_code_line = is_fence or inside

            fmt = block.blockFormat()

            if is_code_line:
                # Single spacing for code lines
                fmt.setLineHeight(
                    0.0,
                    QTextBlockFormat.LineHeightTypes.SingleHeight.value,
                )
                # Solid background for the whole line (no seams)
                fmt.setBackground(bg_brush)
            else:
                # Not in a code block → clear any stale background
                fmt.clearProperty(QTextFormat.BackgroundBrush)

            cursor.setPosition(block.position())
            cursor.setBlockFormat(fmt)

            if is_fence:
                inside = not inside

            block = block.next()

        cursor.endEditBlock()

    def _ensure_escape_line_after_closing_fence(self, fence_block: QTextBlock) -> None:
        """
        Ensure there is at least one block *after* the given closing fence line.

        If the fence is the last block in the document, we append a newline,
        so the caret can always move outside the code block.
        """
        doc = self.document()
        if doc is None or not fence_block.isValid():
            return

        after = fence_block.next()
        if after.isValid():
            # There's already a block after the fence; nothing to do.
            return

        # No block after fence → create a blank line
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        endpos = fence_block.position() + len(fence_block.text())
        cursor.setPosition(endpos)
        cursor.insertText("\n")
        cursor.endEditBlock()

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

        # Convert Unicode bullets back to "- " at the start of a line
        text = re.sub(
            rf"(?m)^(\s*){re.escape(self._BULLET_DISPLAY)}\s+",
            rf"\1{self._BULLET_STORAGE} ",
            text,
        )

        # Append code block metadata if present
        if hasattr(self, "_code_metadata"):
            metadata_str = self._code_metadata.serialize()
            if metadata_str:
                text = text.rstrip() + "\n\n" + metadata_str

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
        # Extract and load code block metadata if present
        from .code_highlighter import CodeBlockMetadata

        if not hasattr(self, "_code_metadata"):
            self._code_metadata = CodeBlockMetadata()

        self._code_metadata.deserialize(markdown_text)
        # Remove metadata comment from displayed text
        markdown_text = re.sub(r"\s*<!-- code-langs: [^>]+ -->\s*$", "", markdown_text)

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

        # Convert simple markdown bullets ("- ", "* ", "+ ") to Unicode bullets,
        # but skip checkbox lines (- [ ] / - [x])
        display_text = re.sub(
            r"(?m)^([ \t]*)[-*+]\s+(?!\[[ xX]\])",
            rf"\1{self._BULLET_DISPLAY} ",
            display_text,
        )

        self._updating = True
        try:
            self.setPlainText(display_text)
            if hasattr(self, "highlighter") and self.highlighter:
                self.highlighter.rehighlight()
        finally:
            self._updating = False

        self._apply_line_spacing()
        self._apply_code_block_spacing()

        # Render any embedded images
        self._render_images()

        # Apply folding for any collapse regions present in the markdown
        self._refresh_collapse_folding()

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

    def _list_prefix_length_for_block(self, block) -> int:
        """Return the length (in chars) of the visual list prefix for the given
        block (including leading indentation), or 0 if it's not a list item.
        """
        line = block.text()
        stripped = line.lstrip()
        leading_spaces = len(line) - len(stripped)

        # Checkbox (Unicode display)
        if stripped.startswith(
            f"{self._CHECK_UNCHECKED_DISPLAY} "
        ) or stripped.startswith(f"{self._CHECK_CHECKED_DISPLAY} "):
            return leading_spaces + 2  # icon + space

        # Unicode bullet
        if stripped.startswith(f"{self._BULLET_DISPLAY} "):
            return leading_spaces + 2  # bullet + space

        # Markdown bullet list (-, *, +)
        if re.match(r"^[-*+]\s", stripped):
            return leading_spaces + 2  # marker + space

        # Numbered list: e.g. "1. "
        m = re.match(r"^(\d+\.\s)", stripped)
        if m:
            return leading_spaces + leading_spaces + (len(m.group(1)) - leading_spaces)

        return 0

    def _maybe_trim_list_prefix_from_line_selection(self) -> None:
        """
        If the current selection looks like a full-line selection on a list item
        (for example, from a triple-click), trim the selection so that it starts
        just *after* the visual list prefix (checkbox / bullet / number), and
        ends at the end of the text on that line (not on the next line's newline).
        """
        # When the user is actively dragging with the mouse, we *do* want the
        # checkbox/bullet to be part of the selection (for deleting whole rows).
        # So don't rewrite the selection in that case.
        if getattr(self, "_mouse_drag_selecting", False):
            return

        # Avoid re-entry when we move the cursor ourselves.
        if getattr(self, "_adjusting_selection", False):
            return

        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            return

        doc = self.document()
        # 'end' is exclusive; use end - 1 so we land in the last selected block.
        start_block = doc.findBlock(start)
        end_block = doc.findBlock(end - 1)
        if not start_block.isValid() or start_block != end_block:
            # Only adjust single-line selections.
            return

        # How much list prefix (indent + checkbox/bullet/number) this block has
        prefix_len = self._list_prefix_length_for_block(start_block)
        if prefix_len <= 0:
            return

        block_start = start_block.position()
        prefix_end = block_start + prefix_len

        # If the selection already starts after the prefix, nothing to do.
        if start >= prefix_end:
            return

        line_text = start_block.text()
        line_end = block_start + len(line_text)  # end of visible text on this line

        # Only treat it as a "full line" selection if it reaches the end of the
        # visible text. Triple-click usually selects to at least here (often +1 for
        # the newline).
        if end < line_end:
            return

        # Clamp the selection so that it ends at the end of this line's text,
        # *not* at the newline / start of the next block. This keeps the caret
        # blinking on the selected line instead of the next line.
        visual_end = line_end

        self._adjusting_selection = True
        try:
            new_cursor = self.textCursor()
            new_cursor.setPosition(prefix_end)
            new_cursor.setPosition(visual_end, QTextCursor.KeepAnchor)
            self.setTextCursor(new_cursor)
        finally:
            self._adjusting_selection = False

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

        # Bullet list - Unicode bullet
        if line.startswith(f"{self._BULLET_DISPLAY} "):
            return ("bullet", f"{self._BULLET_DISPLAY} ")

        # Bullet list - markdown bullet
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

    def _url_at_pos(self, pos) -> str | None:
        """
        Return the URL under the given widget position, or None if there isn't one.
        """
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        text = block.text()
        if not text:
            return None

        # Position of the cursor inside this block
        pos_in_block = cursor.position() - block.position()

        # Same pattern as in MarkdownHighlighter
        url_pattern = re.compile(r"(https?://[^\s<>()]+)")
        for m in url_pattern.finditer(text):
            start, end = m.span(1)
            if start <= pos_in_block < end:
                return m.group(1)

        return None

    def _maybe_skip_over_marker_run(self, key: Qt.Key) -> bool:
        """Skip over common markdown marker runs when navigating with Left/Right.

        This prevents the caret from landing *inside* runs like '**', '***', '__', '___' or '~~',
        which can cause temporary toolbar-state flicker and makes navigation feel like it takes
        "two presses" to get past closing markers.

        Hold any modifier key (Shift/Ctrl/Alt/Meta) to disable this behavior.
        """
        c = self.textCursor()
        if c.hasSelection():
            return False

        p = c.position()
        doc_max = self._doc_max_pos()

        # Right: run starts at the caret
        if key == Qt.Key.Key_Right:
            if p >= doc_max:
                return False
            ch = self._text_range(p, p + 1)
            if ch not in ("*", "_", "~"):
                return False

            run = 0
            while p + run < doc_max and self._text_range(p + run, p + run + 1) == ch:
                run += 1

            # Only skip multi-char runs (bold/strong/emphasis runs or strike)
            if ch in ("*", "_") and run >= 2:
                c.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, run)
                self.setTextCursor(c)
                return True
            if ch == "~" and run == 2:
                c.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, 2)
                self.setTextCursor(c)
                return True

            return False

        # Left: run ends at the caret
        if key == Qt.Key.Key_Left:
            if p <= 0:
                return False
            ch = self._text_range(p - 1, p)
            if ch not in ("*", "_", "~"):
                return False

            run = 0
            while p - 1 - run >= 0 and self._text_range(p - 1 - run, p - run) == ch:
                run += 1

            if ch in ("*", "_") and run >= 2:
                c.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, run)
                self.setTextCursor(c)
                return True
            if ch == "~" and run == 2:
                c.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 2)
                self.setTextCursor(c)
                return True

        return False

    def keyPressEvent(self, event):
        """Handle special key events for markdown editing."""
        c = self.textCursor()
        block = c.block()

        in_code = self._is_inside_code_block(block)
        is_fence_line = block.text().strip().startswith("```")

        # Only when we're *not* already in a code block or on a fence line.
        if event.text() == "`" and not (in_code or is_fence_line):
            line = block.text()
            pos_in_block = c.position() - block.position()
            before = line[:pos_in_block]

            # "before" currently contains whatever's before the *third* backtick.
            # Trigger when the user types a *third consecutive* backtick anywhere on the line.
            # (We require the run immediately before the caret to be exactly two backticks,
            # so we don't trigger on 4+ backticks.)
            if before.endswith("``") and (len(before) < 3 or before[-3] != "`"):
                doc = self.document()
                if doc is not None:
                    # Remove the two backticks that were already typed
                    start = block.position() + pos_in_block - 2
                    edit = QTextCursor(doc)
                    edit.beginEditBlock()
                    edit.setPosition(start)
                    edit.setPosition(start + 2, QTextCursor.KeepAnchor)
                    edit.removeSelectedText()
                    edit.endEditBlock()

                    # Move caret to where the code block should start
                    c.setPosition(start)
                    self.setTextCursor(c)

                # Now behave exactly like the </> toolbar button
                self.apply_code()
                return
        # ------------------------------------------------------------

        # If we're anywhere in a fenced code block (including the fences),
        # treat the text as read-only and route edits through the dialog.
        if in_code or is_fence_line:
            key = event.key()

            # Navigation keys that are safe to pass through.
            nav_keys_no_down = (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Home,
                Qt.Key.Key_End,
                Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown,
            )

            # Let these through:
            #   - pure navigation (except Down, which we handle specially later)
            #   - Enter/Return and Down, which are handled by dedicated logic below
            if key in nav_keys_no_down:
                super().keyPressEvent(event)
                return

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                # Let the existing Enter/Down code see these.
                pass
            else:
                # Any other key (Backspace, Delete, characters, Tab, etc.)
                # opens the code-block editor instead of editing inline.
                if not self._edit_code_block(block):
                    # Fallback if bounds couldn't be found for some reason.
                    super().keyPressEvent(event)
                return

        if (
            event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and not self.textCursor().hasSelection()
        ):
            if self._maybe_skip_over_marker_run(event.key()):
                return

        # --- Step out of a code block with Down at EOF ---
        if event.key() == Qt.Key.Key_Down:
            c = self.textCursor()
            b = c.block()
            pos_in_block = c.position() - b.position()
            line = b.text()

            def next_is_closing(bb):
                nb = bb.next()
                return nb.isValid() and nb.text().strip().startswith("```")

            # Case A: caret is on the line BEFORE the closing fence, at EOL
            # → jump after the fence
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

            # Case B: caret is ON the closing fence, and it's EOF
            # → create a line and move to it
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

        # Handle Backspace on empty list items so the marker itself can be deleted
        if event.key() == Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            # Let Backspace behave normally when deleting a selection.
            if not cursor.hasSelection():
                block = cursor.block()
                prefix_len = self._list_prefix_length_for_block(block)

                if prefix_len > 0:
                    block_start = block.position()
                    line = block.text()
                    pos_in_block = cursor.position() - block_start
                    after_text = line[prefix_len:]

                    # If there is no real content after the marker, treat Backspace
                    # as "remove the list marker".
                    if after_text.strip() == "" and pos_in_block >= prefix_len:
                        cursor.beginEditBlock()
                        cursor.setPosition(block_start)
                        cursor.setPosition(
                            block_start + prefix_len, QTextCursor.KeepAnchor
                        )
                        cursor.removeSelectedText()
                        cursor.endEditBlock()
                        self.setTextCursor(cursor)
                        return

        # Handle Home and Left arrow keys to keep the caret to the *right*
        # of list prefixes (checkboxes / bullets / numbers).
        if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_Left):
            # Let Ctrl+Home / Ctrl+Left keep their usual meaning (start of
            # document / word-left) - we don't interfere with those.
            if event.modifiers() & Qt.ControlModifier:
                pass
            else:
                cursor = self.textCursor()
                block = cursor.block()
                prefix_len = self._list_prefix_length_for_block(block)

                if prefix_len > 0:
                    block_start = block.position()
                    pos_in_block = cursor.position() - block_start
                    target = block_start + prefix_len

                    if event.key() == Qt.Key.Key_Home:
                        # Home should jump to just after the prefix; with Shift
                        # it should *select* back to that position.
                        if event.modifiers() & Qt.ShiftModifier:
                            cursor.setPosition(target, QTextCursor.KeepAnchor)
                        else:
                            cursor.setPosition(target)
                        self.setTextCursor(cursor)
                        return

                    # Left arrow: don't allow the caret to move into the prefix
                    # region; snap it to just after the marker instead.
                    if event.key() == Qt.Key.Key_Left and pos_in_block <= prefix_len:
                        if event.modifiers() & Qt.ShiftModifier:
                            cursor.setPosition(target, QTextCursor.KeepAnchor)
                        else:
                            cursor.setPosition(target)
                        self.setTextCursor(cursor)
                        return

        # After moving vertically, make sure we don't land *inside* a list
        # prefix. We let QTextEdit perform the move first and then adjust.
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not (
            event.modifiers() & Qt.ControlModifier
        ):
            super().keyPressEvent(event)

            cursor = self.textCursor()
            block = cursor.block()

            # Don't interfere with code blocks (they can contain literal
            # markdown-looking text).
            if self._is_inside_code_block(block):
                return

            prefix_len = self._list_prefix_length_for_block(block)
            if prefix_len > 0:
                block_start = block.position()
                pos_in_block = cursor.position() - block_start
                if pos_in_block < prefix_len:
                    target = block_start + prefix_len
                    if event.modifiers() & Qt.ShiftModifier:
                        # Preserve the current anchor while snapping the visual
                        # caret to just after the marker.
                        anchor = cursor.anchor()
                        cursor.setPosition(anchor)
                        cursor.setPosition(target, QTextCursor.KeepAnchor)
                    else:
                        cursor.setPosition(target)
                    self.setTextCursor(cursor)

            return

        # Handle Enter key for smart list continuation AND code blocks
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            cursor = self.textCursor()
            current_line = self._get_current_line()

            # Leading indentation (tabs/spaces) on the current line.
            m_indent = re.match(r"^([ \t]*)", current_line)
            line_indent = m_indent.group(1) if m_indent else ""

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

            stripped = current_line.strip()
            is_fence_line = stripped.startswith("```")

            if is_fence_line:
                # Work out if this fence is closing (inside block before it)
                inside_before = self._is_inside_code_block(current_block.previous())

                # Insert the newline as usual
                super().keyPressEvent(event)

                if inside_before:
                    # We were on the *closing* fence; the new line is outside the block.
                    # Give that new block normal 1.25× spacing.
                    new_block = self.textCursor().block()
                    fmt = new_block.blockFormat()
                    fmt.setLineHeight(
                        125.0,
                        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
                    )
                    cur2 = self.textCursor()
                    cur2.setBlockFormat(fmt)
                    self.setTextCursor(cur2)

                return

            # Inside a code block (but not on a fence): open the popup editor
            if block_state == 1:
                if not self._edit_code_block(current_block):
                    # Fallback if something is malformed
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
                    # First enter on empty list item - just insert newline without prefix
                    super().keyPressEvent(event)
                    self._last_enter_was_empty = True
                    return
                else:
                    # Not empty - continue the list
                    self._last_enter_was_empty = True

                # Insert newline and continue the list
                super().keyPressEvent(event)
                cursor = self.textCursor()
                # Preserve any leading indentation so nested lists keep their level.
                cursor.insertText(line_indent + prefix)
                self._last_enter_was_empty_indent = False
                return
            else:
                # Not a list: support indentation retention. If a line starts
                # with indentation (tabs/spaces), carry that indentation to the
                # next line. A *second* Enter on an empty indented line resets
                # back to column 0.
                if line_indent:
                    rest = current_line[len(line_indent) :]
                    indent_only = rest.strip() == ""

                    if indent_only and self._last_enter_was_empty_indent:
                        # Second Enter on an empty indented line: remove the
                        # indentation-only line and start a fresh, unindented line.
                        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                        cursor.removeSelectedText()
                        cursor.insertText("\n")
                        self._last_enter_was_empty_indent = False
                        self._last_enter_was_empty = False
                        return

                    # First Enter (or a non-empty indented line): keep the indent.
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText(line_indent)
                    self._last_enter_was_empty_indent = True
                    self._last_enter_was_empty = False
                    return

                self._last_enter_was_empty = False
                self._last_enter_was_empty_indent = False
        else:
            # Any other key resets the empty enter flag
            self._last_enter_was_empty = False
            self._last_enter_was_empty_indent = False

        # Default handling
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        # If the left button is down while the mouse moves, we consider this
        # a drag selection (as opposed to a simple click).
        if event.buttons() & Qt.LeftButton:
            self._mouse_drag_selecting = True
        else:
            self._mouse_drag_selecting = False

        # Change cursor when hovering a link
        url = self._url_at_pos(event.pos())
        if url:
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Let QTextEdit handle caret/selection first
        super().mouseReleaseEvent(event)

        if event.button() == Qt.LeftButton:
            # At this point the drag (if any) has finished and the final
            # selection is already in place (and selectionChanged has fired).
            # Clear the drag flag for future interactions.
            self._mouse_drag_selecting = False

        if event.button() != Qt.LeftButton:
            return

        # If the user dragged to select text, don't treat it as a click
        if self.textCursor().hasSelection():
            return

        url_str = self._url_at_pos(event.pos())
        if not url_str:
            return

        url = QUrl(url_str)
        if not url.scheme():
            url.setScheme("https")

        QDesktopServices.openUrl(url)

    def mousePressEvent(self, event):
        """Toggle a checkbox only when the click lands on its icon."""
        # default: don't suppress any upcoming double-click
        self._suppress_next_checkbox_double_click = False

        # Fresh left-button press starts with "no drag" yet.
        if event.button() == Qt.LeftButton:
            self._mouse_drag_selecting = False

            pt = event.pos()

            # Cursor and block under the mouse
            cur = self.cursorForPosition(pt)
            block = cur.block()
            text = block.text()

            # Click-to-toggle collapse regions: clicking the arrow on a
            # "▸ collapse" / "▾ collapse" line expands/collapses the section.
            parsed = self._parse_collapse_header(text)
            if parsed:
                indent, _is_collapsed = parsed
                arrow_idx = len(indent)
                if arrow_idx < len(text):
                    arrow = text[arrow_idx]
                    if arrow in (
                        self._COLLAPSE_ARROW_COLLAPSED,
                        self._COLLAPSE_ARROW_EXPANDED,
                    ):
                        doc_pos = block.position() + arrow_idx
                        c_arrow = QTextCursor(self.document())
                        c_arrow.setPosition(
                            max(
                                0,
                                min(
                                    doc_pos,
                                    max(0, self.document().characterCount() - 1),
                                ),
                            )
                        )
                        r = self.cursorRect(c_arrow)

                        fmt_font = (
                            c_arrow.charFormat().font()
                            if c_arrow.charFormat().isValid()
                            else self.font()
                        )
                        fm = QFontMetrics(fmt_font)
                        w = max(1, fm.horizontalAdvance(arrow))

                        # Make the hit area a bit generous.
                        hit_rect = QRect(r.x(), r.y(), w + (w // 2), r.height())
                        if hit_rect.contains(pt):
                            self._toggle_collapse_at_block(block)
                            return

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
                    r_icon = char_rect_at(doc_pos, icon)

                    # --- Find where the first non-space "real text" starts ---
                    first_idx = i + len(icon) + 1  # skip icon + trailing space
                    while first_idx < len(text) and text[first_idx].isspace():
                        first_idx += 1

                    # Start with some padding around the icon itself
                    left_pad = r_icon.width() // 2
                    right_pad = r_icon.width() // 2

                    hit_left = r_icon.left() - left_pad

                    # If there's actual text after the checkbox, clamp the
                    # clickable area so it stops *before* the first letter.
                    if first_idx < len(text):
                        first_doc_pos = block.position() + first_idx
                        c_first = QTextCursor(self.document())
                        c_first.setPosition(first_doc_pos)
                        first_x = self.cursorRect(c_first).x()

                        expanded_right = r_icon.right() + right_pad
                        hit_right = min(expanded_right, first_x)
                    else:
                        # No text after the checkbox on this line
                        hit_right = r_icon.right() + right_pad

                    # Make sure the rect is at least 1px wide
                    if hit_right <= hit_left:
                        hit_right = r_icon.right()

                    hit_rect = QRect(
                        hit_left,
                        r_icon.top(),
                        max(1, hit_right - hit_left),
                        r_icon.height(),
                    )

                    if hit_rect.contains(pt):
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
                            QTextCursor.Right,
                            QTextCursor.KeepAnchor,
                            len(icon) + 1,
                        )
                        edit.insertText(f"{new_icon} ")
                        edit.endEditBlock()

                        # if a double-click comes next, ignore it
                        self._suppress_next_checkbox_double_click = True
                        return  # handled

                    # advance past this token
                    i += len(icon) + 1
                else:
                    i += 1

        # Default handling for anything else
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # If the previous press toggled a checkbox, swallow this double-click
        # so the base class does NOT turn it into a selection.
        if getattr(self, "_suppress_next_checkbox_double_click", False):
            self._suppress_next_checkbox_double_click = False
            event.accept()
            return

        cursor = self.cursorForPosition(event.pos())
        block = cursor.block()

        # If we're on or inside a code block, open the editor instead
        if self._is_inside_code_block(block) or block.text().strip().startswith("```"):
            # Only swallow the double-click if we actually opened a dialog.
            if not self._edit_code_block(block):
                super().mouseDoubleClickEvent(event)
            return

        # Otherwise, let normal double-click behaviour happen
        super().mouseDoubleClickEvent(event)

    # ------------------------ Toolbar action handlers ------------------------

    # ------------------------ Inline markdown helpers ------------------------

    def _doc_max_pos(self) -> int:
        # QTextDocument includes a trailing null character; cursor positions stop before it.
        doc = self.document()
        return max(0, doc.characterCount() - 1)

    def _text_range(self, start: int, end: int) -> str:
        """Return document text between [start, end) using QTextCursor indexing."""
        doc_max = self._doc_max_pos()
        start = max(0, min(start, doc_max))
        end = max(0, min(end, doc_max))
        if end < start:
            start, end = end, start
        tc = QTextCursor(self.document())
        tc.setPosition(start)
        tc.setPosition(end, QTextCursor.KeepAnchor)
        return tc.selectedText()

    def _selection_wrapped_by(
        self,
        markers: tuple[str, ...],
        *,
        require_singletons: bool = False,
    ) -> str | None:
        """
        If the current selection is wrapped by any marker in `markers`, return the marker.

        Supports both cases:
          1) the selection itself includes the markers, e.g. "**bold**"
          2) the selection is the inner text, with markers immediately adjacent in the doc.
        """
        c = self.textCursor()
        if not c.hasSelection():
            return None

        sel = c.selectedText()
        start = c.selectionStart()
        end = c.selectionEnd()
        doc_max = self._doc_max_pos()

        # Case 1: selection includes markers
        for m in markers:
            lm = len(m)
            if len(sel) >= 2 * lm and sel.startswith(m) and sel.endswith(m):
                return m

        # Case 2: markers adjacent to selection
        for m in markers:
            lm = len(m)
            if start < lm or end + lm > doc_max:
                continue
            before = self._text_range(start - lm, start)
            after = self._text_range(end, end + lm)
            if before != m or after != m:
                continue

            if require_singletons and lm == 1:
                # Ensure the single marker isn't part of a double/triple (e.g. "**" or "__")
                ch = m
                left_marker_pos = start - 1
                right_marker_pos = end

                if (
                    left_marker_pos - 1 >= 0
                    and self._text_range(left_marker_pos - 1, left_marker_pos) == ch
                ):
                    continue
                if (
                    right_marker_pos + 1 <= doc_max
                    and self._text_range(right_marker_pos + 1, right_marker_pos + 2)
                    == ch
                ):
                    continue

            return m

        return None

    def _caret_between_markers(
        self, marker: str, *, require_singletons: bool = False
    ) -> bool:
        """True if the caret is exactly between an opening and closing marker (e.g. **|**)."""
        c = self.textCursor()
        if c.hasSelection():
            return False

        p = c.position()
        lm = len(marker)
        doc_max = self._doc_max_pos()
        if p < lm or p + lm > doc_max:
            return False

        before = self._text_range(p - lm, p)
        after = self._text_range(p, p + lm)
        if before != marker or after != marker:
            return False

        if require_singletons and lm == 1:
            # Disallow if either side is adjacent to the same char (part of "**", "__", "***", etc.)
            ch = marker
            if p - 2 >= 0 and self._text_range(p - 2, p - 1) == ch:
                return False
            if p + 1 <= doc_max and self._text_range(p + 1, p + 2) == ch:
                return False

        return True

    def _caret_before_marker(
        self, marker: str, *, require_singletons: bool = False
    ) -> bool:
        """True if the caret is immediately before `marker` (e.g. |**)."""
        c = self.textCursor()
        if c.hasSelection():
            return False

        p = c.position()
        lm = len(marker)
        doc_max = self._doc_max_pos()
        if p + lm > doc_max:
            return False

        after = self._text_range(p, p + lm)
        if after != marker:
            return False

        if require_singletons and lm == 1:
            # Disallow if it's part of a run like "**" or "___".
            ch = marker
            if p - 1 >= 0 and self._text_range(p - 1, p) == ch:
                return False
            if p + 1 <= doc_max and self._text_range(p + 1, p + 2) == ch:
                return False

        return True

    def _unwrap_selection(
        self, marker: str, *, replacement_marker: str | None = None
    ) -> bool:
        """
        Remove `marker` wrapping from the selection.
        If replacement_marker is provided, replace marker with that (e.g. ***text*** -> *text*).
        """
        c = self.textCursor()
        if not c.hasSelection():
            return False

        sel = c.selectedText()
        start = c.selectionStart()
        end = c.selectionEnd()
        lm = len(marker)
        doc_max = self._doc_max_pos()

        def _select_inner(
            edit_cursor: QTextCursor, inner_start: int, inner_len: int
        ) -> None:
            edit_cursor.setPosition(inner_start)
            edit_cursor.setPosition(inner_start + inner_len, QTextCursor.KeepAnchor)
            self.setTextCursor(edit_cursor)

        # Case 1: selection includes markers
        if len(sel) >= 2 * lm and sel.startswith(marker) and sel.endswith(marker):
            inner = sel[lm:-lm]
            new_text = (
                f"{replacement_marker}{inner}{replacement_marker}"
                if replacement_marker is not None
                else inner
            )
            c.beginEditBlock()
            c.insertText(new_text)
            c.endEditBlock()

            # Re-select the inner content (not the markers)
            inner_start = c.position() - len(new_text)
            if replacement_marker is not None:
                inner_start += len(replacement_marker)
            _select_inner(c, inner_start, len(inner))
            return True

        # Case 2: marker is adjacent to selection
        if start >= lm and end + lm <= doc_max:
            before = self._text_range(start - lm, start)
            after = self._text_range(end, end + lm)
            if before == marker and after == marker:
                new_text = (
                    f"{replacement_marker}{sel}{replacement_marker}"
                    if replacement_marker is not None
                    else sel
                )
                edit = QTextCursor(self.document())
                edit.beginEditBlock()
                edit.setPosition(start - lm)
                edit.setPosition(end + lm, QTextCursor.KeepAnchor)
                edit.insertText(new_text)
                edit.endEditBlock()

                inner_start = (start - lm) + (
                    len(replacement_marker) if replacement_marker else 0
                )
                _select_inner(edit, inner_start, len(sel))
                return True

        return False

    def _wrap_selection(self, marker: str) -> None:
        """Wrap the current selection with `marker` and keep the content selected."""
        c = self.textCursor()
        if not c.hasSelection():
            return
        sel = c.selectedText()
        start = c.selectionStart()
        lm = len(marker)

        c.beginEditBlock()
        c.insertText(f"{marker}{sel}{marker}")
        c.endEditBlock()

        # Re-select the original content
        edit = QTextCursor(self.document())
        edit.setPosition(start + lm)
        edit.setPosition(start + lm + len(sel), QTextCursor.KeepAnchor)
        self.setTextCursor(edit)

    def _pos_inside_inline_span(
        self,
        patterns: list[tuple[re.Pattern, int]],
        start_in_block: int,
        end_in_block: int,
    ) -> bool:
        """True if [start_in_block, end_in_block] lies within the content region of any pattern match."""
        block_text = self.textCursor().block().text()
        for pat, mlen in patterns:
            for m in pat.finditer(block_text):
                s, e = m.span()
                cs, ce = s + mlen, e - mlen
                if cs <= start_in_block and end_in_block <= ce:
                    return True
        return False

    def is_markdown_bold_active(self) -> bool:
        c = self.textCursor()
        bold_markers = ("***", "___", "**", "__")

        if c.hasSelection():
            if self._selection_wrapped_by(bold_markers) is not None:
                return True
            block = c.block()
            start_in_block = c.selectionStart() - block.position()
            end_in_block = c.selectionEnd() - block.position()
            patterns = [
                (re.compile(r"(?<!\*)\*\*\*(.+?)(?<!\*)\*\*\*"), 3),
                (re.compile(r"(?<!_)___(.+?)(?<!_)___"), 3),
                (re.compile(r"(?<!\*)\*\*(?!\*)(.+?)(?<!\*)\*\*(?!\*)"), 2),
                (re.compile(r"(?<!_)__(?!_)(.+?)(?<!_)__(?!_)"), 2),
            ]
            return self._pos_inside_inline_span(patterns, start_in_block, end_in_block)

        # Caret (no selection)
        if any(self._caret_between_markers(m) for m in ("**", "__")):
            return True
        block = c.block()
        pos_in_block = c.position() - block.position()
        patterns = [
            (re.compile(r"(?<!\*)\*\*\*(.+?)(?<!\*)\*\*\*"), 3),
            (re.compile(r"(?<!_)___(.+?)(?<!_)___"), 3),
            (re.compile(r"(?<!\*)\*\*(?!\*)(.+?)(?<!\*)\*\*(?!\*)"), 2),
            (re.compile(r"(?<!_)__(?!_)(.+?)(?<!_)__(?!_)"), 2),
        ]
        return self._pos_inside_inline_span(patterns, pos_in_block, pos_in_block)

    def is_markdown_italic_active(self) -> bool:
        c = self.textCursor()
        italic_markers = ("*", "_", "***", "___")

        if c.hasSelection():
            if (
                self._selection_wrapped_by(italic_markers, require_singletons=True)
                is not None
            ):
                return True
            block = c.block()
            start_in_block = c.selectionStart() - block.position()
            end_in_block = c.selectionEnd() - block.position()
            patterns = [
                (re.compile(r"(?<!\*)\*\*\*(.+?)(?<!\*)\*\*\*"), 3),
                (re.compile(r"(?<!_)___(.+?)(?<!_)___"), 3),
                (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), 1),
                (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), 1),
            ]
            return self._pos_inside_inline_span(patterns, start_in_block, end_in_block)

        pending = getattr(self, "_pending_inline_marker", None)
        if pending in ("*", "_") and self._caret_between_markers(
            pending, require_singletons=True
        ):
            return True
        if pending in ("*", "_"):
            # caret moved away from the empty pair; stop treating it as "pending"
            self._pending_inline_marker = None

        block = c.block()
        pos_in_block = c.position() - block.position()
        patterns = [
            (re.compile(r"(?<!\*)\*\*\*(.+?)(?<!\*)\*\*\*"), 3),
            (re.compile(r"(?<!_)___(.+?)(?<!_)___"), 3),
            (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), 1),
            (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), 1),
        ]
        return self._pos_inside_inline_span(patterns, pos_in_block, pos_in_block)

    def is_markdown_strike_active(self) -> bool:
        c = self.textCursor()
        if c.hasSelection():
            if self._selection_wrapped_by(("~~",)) is not None:
                return True
            block = c.block()
            start_in_block = c.selectionStart() - block.position()
            end_in_block = c.selectionEnd() - block.position()
            patterns = [(re.compile(r"~~(.+?)~~"), 2)]
            return self._pos_inside_inline_span(patterns, start_in_block, end_in_block)

        if self._caret_between_markers("~~"):
            return True
        block = c.block()
        pos_in_block = c.position() - block.position()
        patterns = [(re.compile(r"~~(.+?)~~"), 2)]
        return self._pos_inside_inline_span(patterns, pos_in_block, pos_in_block)

    # ------------------------ Toolbar action handlers ------------------------

    def apply_weight(self):
        """Toggle bold formatting (markdown ** / __, and *** / ___)."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            # If bold+italic, toggling bold should leave italic: ***text*** -> *text*
            m = self._selection_wrapped_by(("***", "___"))
            if m is not None:
                repl = "*" if m == "***" else "_"
                if self._unwrap_selection(m, replacement_marker=repl):
                    self.setFocus()
                    return

            # Normal bold: **text** / __text__
            m = self._selection_wrapped_by(("**", "__"))
            if m is not None:
                if self._unwrap_selection(m):
                    self.setFocus()
                    return

            # Not bold: wrap selection with **
            self._wrap_selection("**")
            self.setFocus()
            return

        # No selection:
        #   - If we're between an empty pair (**|**), remove them.
        #   - If we're inside bold and sitting right before the closing marker (**text|**),
        #     jump the caret *past* the marker (end-bold) instead of inserting more.
        #   - Otherwise, insert a new empty pair and place the caret between.
        if self._caret_between_markers("**") or self._caret_between_markers("__"):
            marker = "**" if self._caret_between_markers("**") else "__"
            p = cursor.position()
            lm = len(marker)
            edit = QTextCursor(self.document())
            edit.beginEditBlock()
            edit.setPosition(p - lm)
            edit.setPosition(p + lm, QTextCursor.KeepAnchor)
            edit.insertText("")
            edit.endEditBlock()
            edit.setPosition(p - lm)
            self.setTextCursor(edit)
        elif self.is_markdown_bold_active() and (
            self._caret_before_marker("**") or self._caret_before_marker("__")
        ):
            marker = "**" if self._caret_before_marker("**") else "__"
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                len(marker),
            )
            self.setTextCursor(cursor)
            self._pending_inline_marker = None
        else:
            # No selection - just insert markers
            cursor.insertText("****")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 2
            )
            self.setTextCursor(cursor)
            self._pending_inline_marker = "*"

        # Return focus to editor
        self.setFocus()

    def apply_italic(self):
        """Toggle italic formatting (markdown * / _, and *** / ___)."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            # If bold+italic, toggling italic should leave bold: ***text*** -> **text**
            m = self._selection_wrapped_by(("***", "___"))
            if m is not None:
                repl = "**" if m == "***" else "__"
                if self._unwrap_selection(m, replacement_marker=repl):
                    self.setFocus()
                    return

            m = self._selection_wrapped_by(("*", "_"), require_singletons=True)
            if m is not None:
                if self._unwrap_selection(m):
                    self.setFocus()
                    return

            self._wrap_selection("*")
            self.setFocus()
            return

        # No selection:
        #   - If we're between an empty pair (*|*), remove them.
        #   - If we're inside italic and sitting right before the closing marker (*text|*),
        #     jump the caret past the marker (end-italic) instead of inserting more.
        #   - Otherwise, insert a new empty pair and place the caret between.
        if self._caret_between_markers(
            "*", require_singletons=True
        ) or self._caret_between_markers("_", require_singletons=True):
            marker = (
                "*"
                if self._caret_between_markers("*", require_singletons=True)
                else "_"
            )
            p = cursor.position()
            lm = len(marker)
            edit = QTextCursor(self.document())
            edit.beginEditBlock()
            edit.setPosition(p - lm)
            edit.setPosition(p + lm, QTextCursor.KeepAnchor)
            edit.insertText("")
            edit.endEditBlock()
            edit.setPosition(p - lm)
            self.setTextCursor(edit)
            self._pending_inline_marker = None
        elif self.is_markdown_italic_active() and (
            self._caret_before_marker("*", require_singletons=True)
            or self._caret_before_marker("_", require_singletons=True)
        ):
            marker = (
                "*" if self._caret_before_marker("*", require_singletons=True) else "_"
            )
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                len(marker),
            )
            self.setTextCursor(cursor)
            self._pending_inline_marker = None
        else:
            cursor.insertText("**")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 1
            )
            self.setTextCursor(cursor)
            self._pending_inline_marker = "*"

        # Return focus to editor
        self.setFocus()

    def apply_strikethrough(self):
        """Toggle strikethrough formatting (markdown ~~)."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            m = self._selection_wrapped_by(("~~",))
            if m is not None:
                if self._unwrap_selection(m):
                    self.setFocus()
                    return
            self._wrap_selection("~~")
            self.setFocus()
            return

        # No selection:
        #   - If we're between an empty pair (~~|~~), remove them.
        #   - If we're inside strike and sitting right before the closing marker (~~text|~~),
        #     jump the caret past the marker (end-strike) instead of inserting more.
        #   - Otherwise, insert a new empty pair and place the caret between.
        if self._caret_between_markers("~~"):
            p = cursor.position()
            edit = QTextCursor(self.document())
            edit.beginEditBlock()
            edit.setPosition(p - 2)
            edit.setPosition(p + 2, QTextCursor.KeepAnchor)
            edit.insertText("")
            edit.endEditBlock()
            edit.setPosition(p - 2)
            self.setTextCursor(edit)
        elif self.is_markdown_strike_active() and self._caret_before_marker("~~"):
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                2,
            )
            self.setTextCursor(cursor)
            self._pending_inline_marker = None
        else:
            cursor.insertText("~~~~")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 2
            )
            self.setTextCursor(cursor)

        # Return focus to editor
        self.setFocus()

    def apply_code(self):
        """
        Toolbar handler for the </> button.

        - If the caret is on / inside an existing fenced block, open the editor for it.
        - Otherwise open the editor prefilled with any selected text, then insert a new
          fenced block containing whatever the user typed.
        """
        cursor = self.textCursor()
        doc = self.document()
        if doc is None:
            return

        block = cursor.block()

        # --- Case 1: already in a code block -> just edit that block ---
        if self._is_inside_code_block(block) or block.text().strip().startswith("```"):
            self._edit_code_block(block)
            return

        # --- Case 2: creating a new block (optional selection) ---
        if cursor.hasSelection():
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            # QTextEdit joins lines with U+2029 in selectedText()
            initial_code = cursor.selectedText().replace("\u2029", "\n")
        else:
            start_pos = cursor.position()
            end_pos = start_pos
            initial_code = ""

        # Let the user type/edit the code in the popup first
        dlg = CodeBlockEditorDialog(initial_code, language=None, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        code_text = dlg.code()
        language = dlg.language()

        # Don't insert an entirely empty block
        if not code_text.strip():
            return

        code_text = code_text.rstrip("\n")

        edit = QTextCursor(doc)
        edit.beginEditBlock()

        # Remove selection (if any) so we can insert the new fenced block
        edit.setPosition(start_pos)
        edit.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        edit.removeSelectedText()

        # Work out whether we're mid-line and need to break before the fence
        block = doc.findBlock(start_pos)
        line = block.text()
        pos_in_block = start_pos - block.position()
        before = line[:pos_in_block]

        # If there's text before the caret on this line, put the fence on a new line
        lead_break = "\n" if before else ""
        insert_str = f"{lead_break}```\n{code_text}\n```\n"

        edit.setPosition(start_pos)
        edit.insertText(insert_str)
        edit.endEditBlock()

        # Find the opening fence block we just inserted
        open_block = doc.findBlock(start_pos + len(lead_break))

        # Find the closing fence block
        close_block = open_block.next()
        while close_block.isValid() and not close_block.text().strip().startswith(
            "```"
        ):
            close_block = close_block.next()

        if close_block.isValid():
            # Make sure there's always at least one line *after* the block
            self._ensure_escape_line_after_closing_fence(close_block)

        # Store language metadata if the user chose one
        if language is not None:
            if not hasattr(self, "_code_metadata"):
                from .code_highlighter import CodeBlockMetadata

                self._code_metadata = CodeBlockMetadata()
            self._code_metadata.set_language(open_block.blockNumber(), language)

        # Refresh visuals
        self._apply_code_block_spacing()
        self._update_code_block_row_backgrounds()
        if hasattr(self, "highlighter"):
            self.highlighter.rehighlight()

        # Put caret just after the code block so the user can keep writing normal text
        after_block = close_block.next() if close_block.isValid() else None
        if after_block and after_block.isValid():
            cursor = self.textCursor()
            cursor.setPosition(after_block.position())
            self.setTextCursor(cursor)

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
        stripped = line.lstrip()

        # Consider existing markdown markers OR our Unicode bullet as "a bullet"
        if (
            stripped.startswith(f"{self._BULLET_DISPLAY} ")
            or stripped.startswith("- ")
            or stripped.startswith("* ")
        ):
            # Remove any of those bullet markers
            pattern = rf"^\s*([{re.escape(self._BULLET_DISPLAY)}\-*])\s+"
            new_line = re.sub(pattern, "", line)
        else:
            new_line = f"{self._BULLET_DISPLAY} " + stripped

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

    # ========== Collapse / Expand (folding) ==========

    def _parse_collapse_header(self, line: str) -> Optional[tuple[str, bool]]:
        # If line is a collapse header, return (indent, is_collapsed)
        m = self._COLLAPSE_HEADER_RE.match(line)
        if not m:
            return None
        indent = m.group(1)
        arrow = m.group(2)
        return (indent, arrow == self._COLLAPSE_ARROW_COLLAPSED)

    def _is_collapse_end_marker(self, line: str) -> bool:
        return bool(self._COLLAPSE_END_RE.match(line))

    def _set_block_visible(self, block: QTextBlock, visible: bool) -> None:
        """Hide/show a QTextBlock and nudge layout to update.

        When folding, we set lineCount=0 for hidden blocks (standard Qt recipe).
        When showing again, we restore a sensible lineCount based on the block's
        current layout so the document relayout doesn't glitch.
        """
        if not block.isValid():
            return
        if block.isVisible() == visible:
            return

        block.setVisible(visible)

        try:
            if not visible:
                # Hidden blocks should contribute no height.
                block.setLineCount(0)  # type: ignore[attr-defined]
            else:
                # Restore an accurate lineCount if we can.
                layout = block.layout()
                lc = 1
                try:
                    lc = int(layout.lineCount()) if layout is not None else 1
                except Exception:
                    lc = 1
                block.setLineCount(max(1, lc))  # type: ignore[attr-defined]
        except Exception:
            pass

        doc = self.document()
        if doc is not None:
            doc.markContentsDirty(block.position(), block.length())

    def _find_collapse_end_block(
        self, header_block: QTextBlock
    ) -> Optional[QTextBlock]:
        # Find matching end marker for a header (supports nesting)
        if not header_block.isValid():
            return None

        depth = 1
        b = header_block.next()
        while b.isValid():
            line = b.text()
            if self._COLLAPSE_HEADER_RE.match(line):
                depth += 1
            elif self._is_collapse_end_marker(line):
                depth -= 1
                if depth == 0:
                    return b
            b = b.next()
        return None

    def _set_collapse_header_state(
        self, header_block: QTextBlock, collapsed: bool
    ) -> None:
        parsed = self._parse_collapse_header(header_block.text())
        if not parsed:
            return
        indent, _ = parsed
        arrow = (
            self._COLLAPSE_ARROW_COLLAPSED
            if collapsed
            else self._COLLAPSE_ARROW_EXPANDED
        )
        label = (
            self._COLLAPSE_LABEL_EXPAND if collapsed else self._COLLAPSE_LABEL_COLLAPSE
        )
        new_line = f"{indent}{arrow} {label}"

        # Replace *only* the text inside this block (not the paragraph separator),
        # to avoid any chance of the header visually "joining" adjacent lines.
        doc = self.document()
        if doc is None:
            return

        cursor = QTextCursor(doc)
        cursor.setPosition(header_block.position())
        cursor.beginEditBlock()
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.insertText(new_line)
        cursor.endEditBlock()

    def _toggle_collapse_at_block(self, header_block: QTextBlock) -> None:
        parsed = self._parse_collapse_header(header_block.text())
        if not parsed:
            return

        doc = self.document()
        if doc is None:
            return

        block_num = header_block.blockNumber()
        _, is_collapsed = parsed

        end_block = self._find_collapse_end_block(header_block)
        if end_block is None:
            return

        # Flip header arrow
        self._set_collapse_header_state(header_block, collapsed=not is_collapsed)

        # Refresh folding so nested regions keep their state
        self._refresh_collapse_folding()

        # Re-resolve the header block after edits/layout changes
        hb = doc.findBlockByNumber(block_num)
        pos = hb.position() if hb.isValid() else header_block.position()

        # Keep caret on the header (start of line)
        c = self.textCursor()
        c.setPosition(max(0, min(pos, max(0, doc.characterCount() - 1))))
        self.setTextCursor(c)
        self.setFocus()

    def _remove_collapse_at_block(self, header_block: QTextBlock) -> None:
        # Remove a collapse wrapper (keep content, delete header + end marker)
        end_block = self._find_collapse_end_block(header_block)
        if end_block is None:
            return

        doc = self.document()
        if doc is None:
            return

        # Ensure content visible
        b = header_block.next()
        while b.isValid() and b != end_block:
            self._set_block_visible(b, True)
            b = b.next()

        cur = QTextCursor(doc)
        cur.beginEditBlock()

        # Delete header block
        cur.setPosition(header_block.position())
        cur.select(QTextCursor.SelectionType.BlockUnderCursor)
        cur.removeSelectedText()
        cur.deleteChar()  # paragraph separator

        # Find and delete the end marker block (scan forward)
        probe = doc.findBlock(end_block.position())
        b2 = probe
        for _ in range(0, 50):
            if not b2.isValid():
                break
            if self._is_collapse_end_marker(b2.text()):
                cur.setPosition(b2.position())
                cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                cur.removeSelectedText()
                cur.deleteChar()
                break
            b2 = b2.next()

        cur.endEditBlock()

        self._refresh_collapse_folding()

    def collapse_selection(self) -> None:
        # Wrap the current selection in a collapsible region and collapse it
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        doc = self.document()
        if doc is None:
            return

        sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
        sel_end = max(cursor.selectionStart(), cursor.selectionEnd())

        # Defensive clamp (prevents QTextCursor::setPosition out-of-range in edge cases)
        doc_end = max(0, doc.characterCount() - 1)
        sel_start = max(0, min(sel_start, doc_end))
        sel_end = max(0, min(sel_end, doc_end))

        c1 = QTextCursor(doc)
        c1.setPosition(sel_start)
        start_block = c1.block()

        c2 = QTextCursor(doc)
        c2.setPosition(sel_end)
        end_block = c2.block()

        # If the selection ends exactly at the start of a block, treat the
        # previous block as the "end" (Qt selections often report the start
        # of the next block as selectionEnd()).
        if (
            sel_end > sel_start
            and end_block.isValid()
            and sel_end == end_block.position()
            and sel_end > 0
        ):
            c2.setPosition(sel_end - 1)
            end_block = c2.block()

        # Expand to whole blocks
        start_pos = start_block.position()
        end_pos_raw = end_block.position() + end_block.length()
        end_pos = min(end_pos_raw, max(0, doc.characterCount() - 1))

        # Inherit indentation from the first selected line (useful inside lists)
        m = re.match(r"^[ \t]*", start_block.text())
        indent = m.group(0) if m else ""

        header_line = (
            f"{indent}{self._COLLAPSE_ARROW_COLLAPSED} {self._COLLAPSE_LABEL_EXPAND}"
        )
        end_marker_line = f"{indent}{self._COLLAPSE_END_MARKER}"

        edit = QTextCursor(doc)
        edit.beginEditBlock()

        # Insert end marker AFTER selection first (keeps start positions stable)
        edit.setPosition(end_pos)

        # If the computed end position fell off the end of the document (common
        # when the selection includes the last line without a trailing newline),
        # ensure the end marker starts on its own line.
        if end_pos_raw > end_pos and edit.position() > 0:
            prev = doc.characterAt(edit.position() - 1)
            if prev not in ("\n", "\u2029"):
                edit.insertText("\n")

        # Also ensure we are not mid-line (marker should be its own block).
        if edit.position() > 0:
            prev = doc.characterAt(edit.position() - 1)
            if prev not in ("\n", "\u2029"):
                edit.insertText("\n")

        edit.insertText(end_marker_line + "\n")

        # Insert header BEFORE selection
        edit.setPosition(start_pos)
        edit.insertText(header_line + "\n")
        edit.endEditBlock()

        self._refresh_collapse_folding()

        # Caret on header
        header_block = doc.findBlock(start_pos)
        c = self.textCursor()
        c.setPosition(header_block.position())
        self.setTextCursor(c)
        self.setFocus()

    def _refresh_collapse_folding(self) -> None:
        # Apply folding to all collapse regions based on their arrow state
        doc = self.document()
        if doc is None:
            return

        # Show everything except end markers (always hidden)
        b = doc.begin()
        while b.isValid():
            if self._is_collapse_end_marker(b.text()):
                self._set_block_visible(b, False)
            else:
                self._set_block_visible(b, True)
            b = b.next()

        # Hide content for any header that is currently collapsed
        b = doc.begin()
        while b.isValid():
            parsed = self._parse_collapse_header(b.text())
            if parsed and parsed[1] is True:
                end_block = self._find_collapse_end_block(b)
                if end_block is None:
                    b = b.next()
                    continue

                inner = b.next()
                while inner.isValid() and inner != end_block:
                    self._set_block_visible(inner, False)
                    inner = inner.next()

                self._set_block_visible(end_block, False)
                b = end_block
            b = b.next()

        # Force a full relayout after visibility changes (prevents visual jitter)
        doc.markContentsDirty(0, doc.characterCount())
        self.viewport().update()

    # ========== Context Menu Support ==========

    def contextMenuEvent(self, event):
        """Override context menu to add custom actions."""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        cursor = self.cursorForPosition(event.pos())

        # Check if we're in a code block
        block = cursor.block()
        if self._is_inside_code_block(block):
            # Add language selection submenu
            lang_menu = menu.addMenu(strings._("set_code_language"))

            languages = [
                "bash",
                "css",
                "html",
                "javascript",
                "php",
                "python",
            ]
            for lang in languages:
                action = QAction(lang.capitalize(), self)
                action.triggered.connect(
                    lambda checked, l=lang: self._set_code_block_language(block, l)
                )
                lang_menu.addAction(action)

            menu.addSeparator()

            edit_action = QAction(strings._("edit_code_block"), self)
            edit_action.triggered.connect(lambda: self._edit_code_block(block))
            menu.addAction(edit_action)

            delete_action = QAction(strings._("delete_code_block"), self)
            delete_action.triggered.connect(lambda: self._delete_code_block(block))
            menu.addAction(delete_action)

            menu.addSeparator()

        # Collapse / Expand actions
        header_parsed = self._parse_collapse_header(block.text())
        if header_parsed:
            _indent, is_collapsed = header_parsed

            menu.addSeparator()

            toggle_label = (
                strings._("expand") if is_collapsed else strings._("collapse")
            )
            toggle_action = QAction(toggle_label, self)
            toggle_action.triggered.connect(
                lambda checked=False, b=block: self._toggle_collapse_at_block(b)
            )
            menu.addAction(toggle_action)

            remove_action = QAction(strings._("remove_collapse"), self)
            remove_action.triggered.connect(
                lambda checked=False, b=block: self._remove_collapse_at_block(b)
            )
            menu.addAction(remove_action)

            menu.addSeparator()

        if self.textCursor().hasSelection():
            collapse_sel_action = QAction(strings._("collapse_selection"), self)
            collapse_sel_action.triggered.connect(self.collapse_selection)
            menu.addAction(collapse_sel_action)
            menu.addSeparator()

        # Add standard context menu actions
        if self.textCursor().hasSelection():
            menu.addAction(strings._("cut"), self.cut)
            menu.addAction(strings._("copy"), self.copy)

        menu.addAction(strings._("paste"), self.paste)

        menu.exec(event.globalPos())

    def _set_code_block_language(self, block, language: str):
        """Set the language for a code block and store metadata."""
        if not hasattr(self, "_code_metadata"):
            from .code_highlighter import CodeBlockMetadata

            self._code_metadata = CodeBlockMetadata()

        # Find the opening fence block for this code block
        fence_block = block
        while fence_block.isValid() and not fence_block.text().strip().startswith(
            "```"
        ):
            fence_block = fence_block.previous()

        if fence_block.isValid():
            self._code_metadata.set_language(fence_block.blockNumber(), language)
            # Trigger rehighlight
            self.highlighter.rehighlight()

    def get_current_line_text(self) -> str:
        """Get the text of the current line."""
        cursor = self.textCursor()
        block = cursor.block()
        return block.text()

    def get_current_line_task_text(self) -> str:
        """
        Like get_current_line_text(), but with list / checkbox / number
        prefixes stripped off for use in Pomodoro notes, etc.
        """
        line = self.get_current_line_text()

        text = re.sub(
            r"^\s*(?:"
            r"-\s\[(?: |x|X)\]\s+"  # markdown checkbox
            r"|[☐☑]\s+"  # Unicode checkbox
            r"|•\s+"  # Unicode bullet
            r"|[-*+]\s+"  # markdown bullets
            r"|\d+\.\s+"  # numbered 1. 2. etc
            r")",
            "",
            line,
        )
        return text.strip()
