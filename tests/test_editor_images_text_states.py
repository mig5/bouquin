import base64
from pathlib import Path
from PySide6.QtCore import QUrl, QByteArray
from PySide6.QtGui import QImage, QTextCursor, QTextImageFormat, QColor
from bouquin.theme import ThemeManager
from bouquin.editor import Editor


def _mk_editor(qapp, cfg):
    themes = ThemeManager(qapp, cfg)
    ed = Editor(themes)
    ed.resize(400, 300)
    return ed


def test_image_scale_and_reset(qapp, cfg):
    ed = _mk_editor(qapp, cfg)

    # Register an image resource and insert it at the cursor
    img = QImage(20, 10, QImage.Format_ARGB32)
    img.fill(QColor(200, 0, 0))
    url = QUrl("test://img")
    from PySide6.QtGui import QTextDocument

    ed.document().addResource(QTextDocument.ResourceType.ImageResource, url, img)

    fmt = QTextImageFormat()
    fmt.setName(url.toString())
    # No explicit width -> code should use original width
    tc = ed.textCursor()
    tc.insertImage(fmt)

    # Place cursor at start (on the image) and scale
    tc = ed.textCursor()
    tc.movePosition(QTextCursor.Start)
    ed.setTextCursor(tc)
    ed._scale_image_at_cursor(1.5)  # increases width
    ed._reset_image_size()  # restores to original width

    # Ensure resulting HTML contains an <img> tag
    html = ed.toHtml()
    assert "<img" in html


def test_apply_image_size_fallbacks(qapp, cfg):
    ed = _mk_editor(qapp, cfg)
    # Create a dummy image format with no width/height -> fallback branch inside _apply_image_size
    fmt = QTextImageFormat()
    fmt.setName("")  # no resource available
    tc = ed.textCursor()
    # Insert a single character to have a valid cursor
    tc.insertText("x")
    tc.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, 1)
    ed._apply_image_size(tc, fmt, new_w=100.0, orig_img=None)  # should not raise


def test_to_html_with_embedded_images_and_link_tint(qapp, cfg):
    ed = _mk_editor(qapp, cfg)

    # Insert an anchor + image and ensure HTML embedding + retint pass runs
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(0, 200, 0))
    url = QUrl("test://img2")
    from PySide6.QtGui import QTextDocument

    ed.document().addResource(QTextDocument.ResourceType.ImageResource, url, img)

    # Compose HTML with a link and an image referencing our resource
    ed.setHtml(
        f'<p><a href="http://example.com">link</a></p><p><img src="{url.toString()}"></p>'
    )

    html = ed.to_html_with_embedded_images()
    # Embedded data URL should appear for the image
    assert "data:image" in html
    # The link should still be present (retinted internally) without crashing
    assert "example.com" in html
