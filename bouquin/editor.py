from __future__ import annotations

from pathlib import Path
import base64, re

from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QImage,
    QImageReader,
    QPalette,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
    QTextFrameFormat,
    QTextListFormat,
    QTextBlockFormat,
    QTextImageFormat,
    QTextDocument,
)
from PySide6.QtCore import (
    Qt,
    QUrl,
    Signal,
    Slot,
    QRegularExpression,
    QBuffer,
    QByteArray,
    QIODevice,
    QTimer,
)
from PySide6.QtWidgets import QTextEdit, QApplication

from .theme import Theme, ThemeManager


class Editor(QTextEdit):
    linkActivated = Signal(str)

    _URL_RX = QRegularExpression(r'((?:https?://|www\.)[^\s<>"\'<>]+)')
    _CODE_BG = QColor(245, 245, 245)
    _CODE_FRAME_PROP = int(QTextFrameFormat.UserProperty) + 100  # marker for our frames
    _HEADING_SIZES = (24.0, 18.0, 14.0)
    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
    _DATA_IMG_RX = re.compile(r'src=["\']data:image/[^;]+;base64,([^"\']+)["\']', re.I)
    # --- Checkbox hack --- #
    _CHECK_UNCHECKED = "\u2610"  # ☐
    _CHECK_CHECKED = "\u2611"  # ☑
    _CHECK_RX = re.compile(r"^\s*([\u2610\u2611])\s")  # ☐/☑ plus a space
    _CHECKBOX_SCALE = 1.35

    def __init__(self, theme_manager: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )

        self.setAcceptRichText(True)

        # If older docs have a baked-in color, normalize once:
        self._retint_anchors_to_palette()

        self._themes = theme_manager
        self._apply_code_theme()  # set initial code colors
        # Refresh on theme change
        self._themes.themeChanged.connect(self._on_theme_changed)
        self._themes.themeChanged.connect(
            lambda _t: QTimer.singleShot(0, self._apply_code_theme)
        )

        self._linkifying = False
        self.textChanged.connect(self._linkify_document)
        self.viewport().setMouseTracking(True)

    def _approx(self, a: float, b: float, eps: float = 0.5) -> bool:
        return abs(float(a) - float(b)) <= eps

    def _is_heading_typing(self) -> bool:
        """Is the current *insertion* format using a heading size?"""
        bf = self.textCursor().blockFormat()
        if bf.headingLevel() > 0:
            return True

    def _apply_normal_typing(self):
        """Switch the *insertion* format to Normal (default size, normal weight)."""
        nf = QTextCharFormat()
        nf.setFontPointSize(self.font().pointSizeF())
        nf.setFontWeight(QFont.Weight.Normal)
        self.mergeCurrentCharFormat(nf)

    def _find_code_frame(self, cursor=None):
        """Return the nearest ancestor frame that's one of our code frames, else None."""
        if cursor is None:
            cursor = self.textCursor()
        f = cursor.currentFrame()
        while f:
            if f.frameFormat().property(self._CODE_FRAME_PROP):
                return f
            f = f.parentFrame()
        return None

    def _looks_like_code_frame(self, frame) -> bool:
        """
        Heuristic: treat a frame as 'code' if
          - it still has our property, OR
          - it has the classic light code bg (≈245,245,245) or our dark bg, OR
          - most blocks inside are non-wrapping (NonBreakableLines=True),
            which we set in apply_code() and which survives HTML round-trip.
        """
        ff = frame.frameFormat()
        if ff.property(self._CODE_FRAME_PROP):
            return True

        # Background check
        bg = ff.background()
        if bg.style() != Qt.NoBrush:
            c = bg.color()
            if c.isValid():
                if (
                    abs(c.red() - 245) <= 2
                    and abs(c.green() - 245) <= 2
                    and abs(c.blue() - 245) <= 2
                ):
                    return True
                if (
                    abs(c.red() - 43) <= 2
                    and abs(c.green() - 43) <= 2
                    and abs(c.blue() - 43) <= 2
                ):
                    return True

        # Block formatting check (survives toHtml/fromHtml)
        doc = self.document()
        bc = QTextCursor(doc)
        bc.setPosition(frame.firstPosition())
        blocks = codeish = 0
        while bc.position() < frame.lastPosition():
            b = bc.block()
            if not b.isValid():
                break
            blocks += 1
            bf = b.blockFormat()
            if bf.nonBreakableLines():
                codeish += 1
            bc.setPosition(b.position() + b.length())
        return blocks > 0 and (codeish / blocks) >= 0.6

    def _code_theme_colors(self):
        """Return (bg, fg) for code blocks based on the effective palette."""
        pal = QApplication.instance().palette()
        # simple luminance check on the window color
        win = pal.color(QPalette.Window)
        is_dark = win.value() < 128
        if is_dark:
            bg = QColor(43, 43, 43)  # dark code background
            fg = pal.windowText().color()  # readable on dark
        else:
            bg = QColor(245, 245, 245)  # light code background
            fg = pal.text().color()  # readable on light
        return bg, fg

    def _apply_code_theme(self):
        """Retint all code frames (even those reloaded from HTML) to match the current theme."""
        bg, fg = self._code_theme_colors()
        self._CODE_BG = bg  # used by future apply_code() calls

        doc = self.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        try:
            # Traverse all frames reliably (iterator-based, works after reload)
            stack = [doc.rootFrame()]
            while stack:
                f = stack.pop()
                it = f.begin()
                while not it.atEnd():
                    cf = it.currentFrame()
                    if cf is not None:
                        stack.append(cf)
                    it += 1

                # Retint frames that look like code
                if f is not doc.rootFrame() and self._looks_like_code_frame(f):
                    ff = f.frameFormat()
                    ff.setBackground(bg)
                    f.setFrameFormat(ff)

                    # Make sure the text inside stays readable and monospaced
                    mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
                    bc = QTextCursor(doc)
                    bc.setPosition(f.firstPosition())
                    while bc.position() < f.lastPosition():
                        bc.select(QTextCursor.BlockUnderCursor)

                        bf = QTextBlockFormat()
                        bf.setTopMargin(0)
                        bf.setBottomMargin(0)
                        bf.setLeftMargin(12)
                        bf.setRightMargin(12)
                        bf.setNonBreakableLines(True)

                        cf = QTextCharFormat()
                        cf.setFont(mono)
                        cf.setFontFixedPitch(True)
                        cf.setForeground(fg)

                        bc.mergeBlockFormat(bf)
                        bc.mergeBlockCharFormat(cf)
                        if not bc.movePosition(QTextCursor.NextBlock):
                            break
        finally:
            cur.endEditBlock()
            self.viewport().update()

    def _safe_select(self, cur: QTextCursor, start: int, end: int):
        """Select [start, end] inclusive without exceeding document bounds."""
        doc_max = max(0, self.document().characterCount() - 1)
        s = max(0, min(start, doc_max))
        e = max(0, min(end, doc_max))
        if e < s:
            s, e = e, s
        cur.setPosition(s)
        cur.setPosition(e, QTextCursor.KeepAnchor)

    def _trim_url_end(self, url: str) -> str:
        # strip common trailing punctuation not part of the URL
        trimmed = url.rstrip(".,;:!?\"'")
        # drop an unmatched closing ) or ] at the very end
        if trimmed.endswith(")") and trimmed.count("(") < trimmed.count(")"):
            trimmed = trimmed[:-1]
        if trimmed.endswith("]") and trimmed.count("[") < trimmed.count("]"):
            trimmed = trimmed[:-1]
        return trimmed

    def _linkify_document(self):
        if self._linkifying:
            return
        self._linkifying = True

        try:
            block = self.textCursor().block()
            start_pos = block.position()
            text = block.text()

            cur = QTextCursor(self.document())
            cur.beginEditBlock()

            it = self._URL_RX.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s = start_pos + m.capturedStart()
                raw = m.captured(0)
                url = self._trim_url_end(raw)
                if not url:
                    continue

                e = s + len(url)
                cur.setPosition(s)
                cur.setPosition(e, QTextCursor.KeepAnchor)

                if url.startswith("www."):
                    href = "https://" + url
                else:
                    href = url

                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(href)  # always refresh to the latest full URL
                fmt.setFontUnderline(True)
                fmt.setForeground(self.palette().brush(QPalette.Link))

                cur.mergeCharFormat(fmt)  # merge so we don’t clobber other styling

            cur.endEditBlock()
        finally:
            self._linkifying = False

    def _to_qimage(self, obj) -> QImage | None:
        if isinstance(obj, QImage):
            return None if obj.isNull() else obj
        if isinstance(obj, QPixmap):
            qi = obj.toImage()
            return None if qi.isNull() else qi
        if isinstance(obj, (bytes, bytearray)):
            qi = QImage.fromData(obj)
            return None if qi.isNull() else qi
        return None

    def _qimage_to_data_url(self, img: QImage, fmt: str = "PNG") -> str:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, fmt.upper())
        b64 = base64.b64encode(bytes(ba)).decode("ascii")
        mime = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
        return f"data:{mime};base64,{b64}"

    def _image_name_to_qimage(self, name: str) -> QImage | None:
        res = self.document().resource(QTextDocument.ImageResource, QUrl(name))
        return res if isinstance(res, QImage) and not res.isNull() else None

    def to_html_with_embedded_images(self) -> str:
        """
        Return the document HTML with all image src's replaced by data: URLs,
        so it is self-contained for storage in the DB.
        """
        # 1) Walk the document collecting name -> data: URL
        name_to_data = {}
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.Start)
        while True:
            cur.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
            fmt = cur.charFormat()
            if fmt.isImageFormat():
                imgfmt = QTextImageFormat(fmt)
                name = imgfmt.name()
                if name and name not in name_to_data:
                    img = self._image_name_to_qimage(name)
                    if img:
                        name_to_data[name] = self._qimage_to_data_url(img, "PNG")
            if cur.atEnd():
                break
            cur.clearSelection()

        # 2) Serialize and replace names with data URLs
        html = self.document().toHtml()
        for old, data_url in name_to_data.items():
            html = html.replace(f'src="{old}"', f'src="{data_url}"')
            html = html.replace(f"src='{old}'", f"src='{data_url}'")
        return html

    def _insert_qimage_at_cursor(self, img: QImage, autoscale=True):
        c = self.textCursor()

        # Don’t drop inside a code frame
        frame = self._find_code_frame(c)
        if frame:
            out = QTextCursor(self.document())
            out.setPosition(frame.lastPosition())
            self.setTextCursor(out)
            c = self.textCursor()

        # Start a fresh paragraph if mid-line
        if c.positionInBlock() != 0:
            c.insertBlock()

        if autoscale and self.viewport():
            max_w = int(self.viewport().width() * 0.92)
            if img.width() > max_w:
                img = img.scaledToWidth(max_w, Qt.SmoothTransformation)

        c.insertImage(img)
        c.insertBlock()  # one blank line after the image

    def _image_info_at_cursor(self):
        """
        Returns (cursorSelectingImageChar, QTextImageFormat, originalQImage) or (None, None, None)
        """
        # Try current position (select 1 char forward)
        tc = QTextCursor(self.textCursor())
        tc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
        fmt = tc.charFormat()
        if fmt.isImageFormat():
            imgfmt = QTextImageFormat(fmt)
            img = self._resolve_image_resource(imgfmt)
            return tc, imgfmt, img

        # Try previous char (if caret is just after the image)
        tc = QTextCursor(self.textCursor())
        if tc.position() > 0:
            tc.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 1)
            tc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
            fmt = tc.charFormat()
            if fmt.isImageFormat():
                imgfmt = QTextImageFormat(fmt)
                img = self._resolve_image_resource(imgfmt)
                return tc, imgfmt, img

        return None, None, None

    def _resolve_image_resource(self, imgfmt: QTextImageFormat) -> QImage | None:
        """
        Fetch the original QImage backing the inline image, if available.
        """
        name = imgfmt.name()
        if name:
            try:
                img = self.document().resource(QTextDocument.ImageResource, QUrl(name))
                if isinstance(img, QImage) and not img.isNull():
                    return img
            except Exception:
                pass
        return None  # fallback handled by callers

    def _apply_image_size(
        self,
        tc: QTextCursor,
        imgfmt: QTextImageFormat,
        new_w: float,
        orig_img: QImage | None,
    ):
        # compute height proportionally
        if orig_img and orig_img.width() > 0:
            ratio = new_w / orig_img.width()
            new_h = max(1.0, orig_img.height() * ratio)
        else:
            # fallback: keep current aspect ratio if we have it
            cur_w = imgfmt.width() if imgfmt.width() > 0 else new_w
            cur_h = imgfmt.height() if imgfmt.height() > 0 else new_w
            ratio = new_w / max(1.0, cur_w)
            new_h = max(1.0, cur_h * ratio)

        imgfmt.setWidth(max(1.0, new_w))
        imgfmt.setHeight(max(1.0, new_h))
        tc.mergeCharFormat(imgfmt)

    def _scale_image_at_cursor(self, factor: float):
        tc, imgfmt, orig = self._image_info_at_cursor()
        if not imgfmt:
            return
        base_w = imgfmt.width()
        if base_w <= 0 and orig:
            base_w = orig.width()
        if base_w <= 0:
            return
        self._apply_image_size(tc, imgfmt, base_w * factor, orig)

    def _fit_image_to_editor_width(self):
        tc, imgfmt, orig = self._image_info_at_cursor()
        if not imgfmt:
            return
        if not self.viewport():
            return
        target = int(self.viewport().width() * 0.92)
        self._apply_image_size(tc, imgfmt, target, orig)

    def _set_image_width_dialog(self):
        from PySide6.QtWidgets import QInputDialog

        tc, imgfmt, orig = self._image_info_at_cursor()
        if not imgfmt:
            return
        # propose current display width or original width
        cur_w = (
            int(imgfmt.width())
            if imgfmt.width() > 0
            else (orig.width() if orig else 400)
        )
        w, ok = QInputDialog.getInt(
            self, "Set image width", "Width (px):", cur_w, 1, 10000, 10
        )
        if ok:
            self._apply_image_size(tc, imgfmt, float(w), orig)

    def _reset_image_size(self):
        tc, imgfmt, orig = self._image_info_at_cursor()
        if not imgfmt or not orig:
            return
        self._apply_image_size(tc, imgfmt, float(orig.width()), orig)

    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu()
        tc, imgfmt, orig = self._image_info_at_cursor()
        if imgfmt:
            menu.addSeparator()
            sub = menu.addMenu("Image size")
            sub.addAction("Shrink 10%", lambda: self._scale_image_at_cursor(0.9))
            sub.addAction("Grow 10%", lambda: self._scale_image_at_cursor(1.1))
            sub.addAction("Fit to editor width", self._fit_image_to_editor_width)
            sub.addAction("Set width…", self._set_image_width_dialog)
            sub.addAction("Reset to original", self._reset_image_size)
        menu.exec(e.globalPos())

    def insertFromMimeData(self, source):
        # 1) Direct image from clipboard
        if source.hasImage():
            img = self._to_qimage(source.imageData())
            if img is not None:
                self._insert_qimage_at_cursor(img, autoscale=True)
                return

        # 2) File URLs (drag/drop or paste)
        if source.hasUrls():
            paths = []
            non_local_urls = []
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path.lower().endswith(self._IMAGE_EXTS):
                        paths.append(path)
                    else:
                        # Non-image file: insert as link
                        self.textCursor().insertHtml(
                            f'<a href="{url.toString()}">{Path(path).name}</a>'
                        )
                        self.textCursor().insertBlock()
                else:
                    non_local_urls.append(url)

            if paths:
                self.insert_images(paths)

            for url in non_local_urls:
                self.textCursor().insertHtml(
                    f'<a href="{url.toString()}">{url.toString()}</a>'
                )
                self.textCursor().insertBlock()

            if paths or non_local_urls:
                return

        # 3) HTML with data: image
        if source.hasHtml():
            html = source.html()
            m = self._DATA_IMG_RX.search(html or "")
            if m:
                try:
                    data = base64.b64decode(m.group(1))
                    img = QImage.fromData(data)
                    if not img.isNull():
                        self._insert_qimage_at_cursor(self, img, autoscale=True)
                        return
                except Exception:
                    pass  # fall through

        # 4) Everything else → default behavior
        super().insertFromMimeData(source)

    @Slot(list)
    def insert_images(self, paths: list[str], autoscale=True):
        """
        Insert one or more images at the cursor. Large images can be auto-scaled
        to fit the viewport width while preserving aspect ratio.
        """
        c = self.textCursor()

        # Avoid dropping images inside a code frame
        frame = self._find_code_frame(c)
        if frame:
            out = QTextCursor(self.document())
            out.setPosition(frame.lastPosition())
            self.setTextCursor(out)
            c = self.textCursor()

        # Ensure there's a paragraph break if we're mid-line
        if c.positionInBlock() != 0:
            c.insertBlock()

        for path in paths:
            reader = QImageReader(path)
            img = reader.read()
            if img.isNull():
                continue

            if autoscale and self.viewport():
                max_w = int(self.viewport().width() * 0.92)  # ~92% of editor width
                if img.width() > max_w:
                    img = img.scaledToWidth(max_w, Qt.SmoothTransformation)

            c.insertImage(img)
            c.insertBlock()  # put each image on its own line

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and (e.modifiers() & Qt.ControlModifier):
            href = self.anchorAt(e.pos())
            if href:
                QDesktopServices.openUrl(QUrl.fromUserInput(href))
                self.linkActivated.emit(href)
                return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self.anchorAt(e.pos()):
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            cur = self.cursorForPosition(e.pos())
            b = cur.block()
            state, pref = self._checkbox_info_for_block(b)
            if state is not None:
                col = cur.position() - b.position()
                if col <= max(1, pref):  # clicked on ☐/☑ (and the following space)
                    self._set_block_checkbox_state(b, not state)
                    return
        return super().mousePressEvent(e)

    def keyPressEvent(self, e):
        key = e.key()

        if key in (Qt.Key_Space, Qt.Key_Tab):
            c = self.textCursor()
            b = c.block()
            pos_in_block = c.position() - b.position()

            if (
                pos_in_block >= 4
                and b.text().startswith("TODO")
                and b.text()[:pos_in_block] == "TODO"
                and self._checkbox_info_for_block(b)[0] is None
            ):
                tcur = QTextCursor(self.document())
                tcur.setPosition(b.position())  # start of block
                tcur.setPosition(
                    b.position() + 4, QTextCursor.KeepAnchor
                )  # select "TODO"
                tcur.beginEditBlock()
                tcur.removeSelectedText()
                tcur.insertText(self._CHECK_UNCHECKED + " ")  # insert "☐ "
                tcur.endEditBlock()

                # visuals: size bump
                if hasattr(self, "_style_checkbox_glyph"):
                    self._style_checkbox_glyph(b)

                # caret after the inserted prefix; swallow the key (we already added a space)
                c.setPosition(b.position() + 2)
                self.setTextCursor(c)
                return

            # not a TODO-at-start case
            self._break_anchor_for_next_char()
            return super().keyPressEvent(e)

        if key in (Qt.Key_Return, Qt.Key_Enter):
            c = self.textCursor()

            # If we're on an empty line inside a code frame, consume Enter and jump out
            if c.block().length() == 1:
                frame = self._find_code_frame(c)
                if frame:
                    out = QTextCursor(self.document())
                    out.setPosition(frame.lastPosition())  # after the frame's contents
                    self.setTextCursor(out)
                    super().insertPlainText("\n")  # start a normal paragraph
                    return

            # --- CHECKBOX handling: continue on Enter; "escape" on second Enter ---
            b = c.block()
            state, pref = self._checkbox_info_for_block(b)
            if state is not None and not c.hasSelection():
                text_after = b.text()[pref:].strip()
                if c.atBlockEnd() and text_after == "":
                    # Empty checkbox item -> remove the prefix and insert a plain new line
                    cur = QTextCursor(self.document())
                    cur.setPosition(b.position())
                    cur.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, pref)
                    cur.removeSelectedText()
                    return super().keyPressEvent(e)
                else:
                    # Normal continuation: new checkbox on the next line
                    super().keyPressEvent(e)  # make the new block
                    super().insertPlainText(self._CHECK_UNCHECKED + " ")
                    if hasattr(self, "_style_checkbox_glyph"):
                        self._style_checkbox_glyph(self.textCursor().block())
                    return

            # Follow-on style: if we typed a heading and press Enter at end of block,
            # new paragraph should revert to Normal.
            if not c.hasSelection() and c.atBlockEnd() and self._is_heading_typing():
                super().keyPressEvent(e)  # insert the new paragraph
                self._apply_normal_typing()  # make the *new* paragraph Normal for typing
                return

        # otherwise default handling
        return super().keyPressEvent(e)

    def _break_anchor_for_next_char(self):
        """
        Ensure the *next* typed character is not part of a hyperlink.
        Only strips link-specific attributes; leaves bold/italic/underline etc intact.
        """
        # What we're about to type with
        ins_fmt = self.currentCharFormat()
        # What the cursor is sitting on
        cur_fmt = self.textCursor().charFormat()

        # Do nothing unless either side indicates we're in/propagating an anchor
        if not (
            ins_fmt.isAnchor()
            or cur_fmt.isAnchor()
            or ins_fmt.fontUnderline()
            or ins_fmt.foreground().style() != Qt.NoBrush
        ):
            return

        nf = QTextCharFormat(ins_fmt)
        # stop the link itself
        nf.setAnchor(False)
        nf.setAnchorHref("")
        # also stop the link *styling*
        nf.setFontUnderline(False)
        nf.clearForeground()

        self.setCurrentCharFormat(nf)

    def merge_on_sel(self, fmt):
        """
        Sets the styling on the selected characters or the insertion position.
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    # ====== Checkbox core ======
    def _base_point_size_for_block(self, block) -> float:
        # Try the block’s char format, then editor font
        sz = block.charFormat().fontPointSize()
        if sz <= 0:
            sz = self.fontPointSize()
        if sz <= 0:
            sz = self.font().pointSizeF() or 12.0
        return float(sz)

    def _style_checkbox_glyph(self, block):
        """Apply larger size (and optional symbol font) to the single ☐/☑ char."""
        state, _ = self._checkbox_info_for_block(block)
        if state is None:
            return
        doc = self.document()
        c = QTextCursor(doc)
        c.setPosition(block.position())
        c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)  # select ☐/☑ only

        base = self._base_point_size_for_block(block)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(base * self._CHECKBOX_SCALE)
        # keep the glyph centered on the text baseline
        fmt.setVerticalAlignment(QTextCharFormat.AlignMiddle)

        c.mergeCharFormat(fmt)

    def _checkbox_info_for_block(self, block):
        """Return (state, prefix_len): state in {None, False, True}, prefix_len in chars."""
        text = block.text()
        m = self._CHECK_RX.match(text)
        if not m:
            return None, 0
        ch = m.group(1)
        state = True if ch == self._CHECK_CHECKED else False
        return state, m.end()

    def _set_block_checkbox_present(self, block, present: bool):
        state, pref = self._checkbox_info_for_block(block)
        doc = self.document()
        c = QTextCursor(doc)
        c.setPosition(block.position())
        c.beginEditBlock()
        try:
            if present and state is None:
                c.insertText(self._CHECK_UNCHECKED + " ")
                state = False
                self._style_checkbox_glyph(block)
            else:
                if state is not None:
                    c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, pref)
                    c.removeSelectedText()
                    state = None
        finally:
            c.endEditBlock()

        return state

    def _set_block_checkbox_state(self, block, checked: bool):
        """Switch ☐/☑ at the start of the block."""
        state, pref = self._checkbox_info_for_block(block)
        if state is None:
            return
        doc = self.document()
        c = QTextCursor(doc)
        c.setPosition(block.position())
        c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)  # just the symbol
        c.beginEditBlock()
        try:
            c.removeSelectedText()
            c.insertText(self._CHECK_CHECKED if checked else self._CHECK_UNCHECKED)
            self._style_checkbox_glyph(block)
        finally:
            c.endEditBlock()

    # Public API used by toolbar
    def toggle_checkboxes(self):
        """
        Toggle checkbox prefix on/off for the current block(s).
        If all targeted blocks already have a checkbox, remove them; otherwise add.
        """
        c = self.textCursor()
        doc = self.document()

        if c.hasSelection():
            start = doc.findBlock(c.selectionStart())
            end = doc.findBlock(c.selectionEnd() - 1)
        else:
            start = end = c.block()

        # Decide intent: add or remove?
        b = start
        all_have = True
        while True:
            state, _ = self._checkbox_info_for_block(b)
            if state is None:
                all_have = False
                break
            if b == end:
                break
            b = b.next()

        # Apply
        b = start
        while True:
            self._set_block_checkbox_present(b, present=not all_have)
            if b == end:
                break
            b = b.next()

    def toggle_current_checkbox_state(self):
        """Tick/untick the current line if it starts with a checkbox."""
        b = self.textCursor().block()
        state, _ = self._checkbox_info_for_block(b)
        if state is None:
            return
        self._set_block_checkbox_state(b, not state)

    @Slot()
    def apply_weight(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        weight = (
            QFont.Weight.Normal
            if cur.fontWeight() == QFont.Weight.Bold
            else QFont.Weight.Bold
        )
        fmt.setFontWeight(weight)
        self.merge_on_sel(fmt)

    @Slot()
    def apply_italic(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontItalic(not cur.fontItalic())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_underline(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not cur.fontUnderline())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_strikethrough(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not cur.fontStrikeOut())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_code(self):
        c = self.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.BlockUnderCursor)

        # Wrap the selection in a single frame (no per-block padding/margins).
        ff = QTextFrameFormat()
        ff.setBackground(self._CODE_BG)
        ff.setPadding(6)  # visual padding for the WHOLE block
        ff.setBorder(0)
        ff.setLeftMargin(0)
        ff.setRightMargin(0)
        ff.setTopMargin(0)
        ff.setBottomMargin(0)
        ff.setProperty(self._CODE_FRAME_PROP, True)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        c.beginEditBlock()
        try:
            c.insertFrame(ff)  # with a selection, this wraps the selection

            # Format all blocks inside the new frame: zero vertical margins, mono font, no wrapping
            frame = self._find_code_frame(c)
            bc = QTextCursor(self.document())
            bc.setPosition(frame.firstPosition())

            while bc.position() < frame.lastPosition():
                bc.select(QTextCursor.BlockUnderCursor)

                bf = QTextBlockFormat()
                bf.setTopMargin(0)
                bf.setBottomMargin(0)
                bf.setLeftMargin(12)
                bf.setRightMargin(12)
                bf.setNonBreakableLines(True)

                cf = QTextCharFormat()
                cf.setFont(mono)
                cf.setFontFixedPitch(True)

                bc.mergeBlockFormat(bf)
                bc.mergeBlockCharFormat(cf)

                bc.setPosition(bc.block().position() + bc.block().length())
        finally:
            c.endEditBlock()

    @Slot(int)
    def apply_heading(self, size: int):
        """
        Set heading point size for typing. If there's a selection, also apply bold
        to that selection (for H1..H3). "Normal" clears bold on the selection.
        """
        # Map toolbar's sizes to heading levels
        level = 1 if size >= 24 else 2 if size >= 18 else 3 if size >= 14 else 0

        c = self.textCursor()

        # On-screen look
        ins = QTextCharFormat()
        if size:
            ins.setFontPointSize(float(size))
            ins.setFontWeight(QFont.Weight.Bold)
        else:
            ins.setFontPointSize(self.font().pointSizeF())
            ins.setFontWeight(QFont.Weight.Normal)
        self.mergeCurrentCharFormat(ins)

        # Apply heading level to affected block(s)
        def set_level_for_block(cur):
            bf = cur.blockFormat()
            if hasattr(bf, "setHeadingLevel"):
                bf.setHeadingLevel(level)  # 0 clears heading
                cur.mergeBlockFormat(bf)

        if c.hasSelection():
            start, end = c.selectionStart(), c.selectionEnd()
            bc = QTextCursor(self.document())
            bc.setPosition(start)
            while True:
                set_level_for_block(bc)
                if bc.position() >= end:
                    break
                bc.movePosition(QTextCursor.EndOfBlock)
                if bc.position() >= end:
                    break
                bc.movePosition(QTextCursor.NextBlock)
        else:
            bc = QTextCursor(c)
            set_level_for_block(bc)

    def toggle_bullets(self):
        c = self.textCursor()
        lst = c.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDisc:
            lst.remove(c.block())
            return
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDisc)
        c.createList(fmt)

    def toggle_numbers(self):
        c = self.textCursor()
        lst = c.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDecimal:
            lst.remove(c.block())
            return
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDecimal)
        c.createList(fmt)

    @Slot(Theme)
    def _on_theme_changed(self, _theme: Theme):
        # Defer one event-loop tick so widgets have the new palette
        QTimer.singleShot(0, self._retint_anchors_to_palette)
        QTimer.singleShot(0, self._apply_code_theme)

    @Slot()
    def _retint_anchors_to_palette(self, *_):
        # Always read from the *application* palette to avoid stale widget palette
        app = QApplication.instance()
        link_brush = app.palette().brush(QPalette.Link)
        doc = self.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fmt = frag.charFormat()
                    if fmt.isAnchor():
                        new_fmt = QTextCharFormat(fmt)
                        new_fmt.setForeground(link_brush)  # force palette link color
                        start = frag.position()
                        cur.setPosition(start)
                        cur.movePosition(
                            QTextCursor.NextCharacter,
                            QTextCursor.KeepAnchor,
                            frag.length(),
                        )  # select exactly this fragment
                        cur.setCharFormat(new_fmt)
                it += 1
            block = block.next()
        cur.endEditBlock()
        self.viewport().update()

    def setHtml(self, html: str) -> None:
        super().setHtml(html)

        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            self._style_checkbox_glyph(block)  # Apply checkbox styling to each block
            block = block.next()

        # Ensure anchors adopt the palette color on startup
        self._retint_anchors_to_palette()
        self._apply_code_theme()
