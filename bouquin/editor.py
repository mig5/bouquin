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
)
from PySide6.QtWidgets import QTextEdit


class Editor(QTextEdit):
    linkActivated = Signal(str)

    _URL_RX = QRegularExpression(r'((?:https?://|www\.)[^\s<>"\'<>]+)')
    _CODE_BG = QColor(245, 245, 245)
    _CODE_FRAME_PROP = int(QTextFrameFormat.UserProperty) + 100  # marker for our frames
    _HEADING_SIZES = (24.0, 18.0, 14.0)
    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
    _DATA_IMG_RX = re.compile(r'src=["\']data:image/[^;]+;base64,([^"\']+)["\']', re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )

        self.setAcceptRichText(True)

        # Turn raw URLs into anchors
        self._linkifying = False
        self.textChanged.connect(self._linkify_document)
        self.viewport().setMouseTracking(True)

    def _approx(self, a: float, b: float, eps: float = 0.5) -> bool:
        return abs(float(a) - float(b)) <= eps

    def _is_heading_typing(self) -> bool:
        """Is the current *insertion* format using a heading size?"""
        s = self.currentCharFormat().fontPointSize() or self.font().pointSizeF()
        return any(self._approx(s, h) for h in self._HEADING_SIZES)

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

    def _is_code_block(self, block) -> bool:
        if not block.isValid():
            return False
        bf = block.blockFormat()
        return bool(
            bf.nonBreakableLines()
            and bf.background().color().rgb() == self._CODE_BG.rgb()
        )

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
                fmt.setForeground(Qt.blue)

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
                self._insert_qimage_at_cursor(self, img, autoscale=True)
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

    def keyPressEvent(self, e):
        key = e.key()

        # Pre-insert: stop link/format bleed for “word boundary” keys
        if key in (Qt.Key_Space, Qt.Key_Tab):
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

            # Follow-on style: if we typed a heading and press Enter at end of block,
            # new paragraph should revert to Normal.
            if not c.hasSelection() and c.atBlockEnd() and self._is_heading_typing():
                super().keyPressEvent(e)  # insert the new paragraph
                self._apply_normal_typing()  # make the *new* paragraph Normal for typing
                return

        # otherwise default handling
        return super().keyPressEvent(e)

    def _clear_insertion_char_format(self):
        """Reset inline typing format (keeps lists, alignment, margins, etc.)."""
        nf = QTextCharFormat()
        self.setCurrentCharFormat(nf)

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
        if not (ins_fmt.isAnchor() or cur_fmt.isAnchor()):
            return

        nf = QTextCharFormat(ins_fmt)
        nf.setAnchor(False)
        nf.setAnchorHref("")

        self.setCurrentCharFormat(nf)

    def merge_on_sel(self, fmt):
        """
        Sets the styling on the selected characters or the insertion position.
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

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
        base_size = size if size else self.font().pointSizeF()
        c = self.textCursor()

        # Update the typing (insertion) format to be size only, but don't represent
        # it as if the Bold style has been toggled on
        ins = QTextCharFormat()
        ins.setFontPointSize(base_size)
        self.mergeCurrentCharFormat(ins)

        # If user selected text, style that text visually as a heading
        if c.hasSelection():
            sel = QTextCharFormat(ins)
            sel.setFontWeight(QFont.Weight.Bold if size else QFont.Weight.Normal)
            c.mergeCharFormat(sel)

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
