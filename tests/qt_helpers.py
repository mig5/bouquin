import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QAbstractButton,
    QListWidget,
)

# ---------- robust widget finders ----------


def _visible_widgets():
    for w in QApplication.topLevelWidgets():
        if w.isVisible():
            yield w
        for c in w.findChildren(QWidget):
            if c.isWindow() and c.isVisible():
                yield c


def wait_for_widget(cls=None, predicate=lambda w: True, timeout_ms: int = 15000):
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for w in _visible_widgets():
            if (cls is None or isinstance(w, cls)) and predicate(w):
                return w
        QTest.qWait(25)
    raise TimeoutError(f"Timed out waiting for {cls} matching predicate")


# ---------- generic ui helpers ----------


def click_button_by_text(container: QWidget, contains: str) -> bool:
    """Click any QAbstractButton whose label contains the substring."""
    target = contains.lower()
    for btn in container.findChildren(QAbstractButton):
        text = (btn.text() or "").lower()
        if target in text:
            from PySide6.QtTest import QTest

            if not btn.isEnabled():
                QTest.qWait(50)  # give UI a tick to enable
            QTest.mouseClick(btn, Qt.LeftButton)
            return True
    return False


def _first_line_edit(dlg: QDialog) -> QLineEdit | None:
    edits = dlg.findChildren(QLineEdit)
    return edits[0] if edits else None


def fill_first_line_edit_and_accept(dlg: QDialog, text: str | None):
    le = _first_line_edit(dlg)
    assert le is not None, "Expected a QLineEdit in the dialog"
    if text is not None:
        le.clear()
        QTest.keyClicks(le, text)
    # Prefer 'OK'; fallback to Return
    ok = None
    for btn in dlg.findChildren(QPushButton):
        t = btn.text().lower().lstrip("&")
        if t == "ok" or btn.isDefault():
            ok = btn
            break
    if ok:
        QTest.mouseClick(ok, Qt.LeftButton)
    else:
        QTest.keyClick(le, Qt.Key_Return)


def accept_all_message_boxes(limit: int = 5) -> bool:
    """
    Accept every visible QMessageBox, preferring Yes/Accept/Ok.
    Returns True if at least one box was accepted.
    """
    accepted_any = False
    for _ in range(limit):
        accepted_this_round = False
        for w in _visible_widgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                # Prefer "Yes", then any Accept/Apply role, then Ok, then default/first.
                btn = (
                    w.button(QMessageBox.Yes)
                    or next(
                        (
                            b
                            for b in w.buttons()
                            if w.buttonRole(b)
                            in (
                                QMessageBox.YesRole,
                                QMessageBox.AcceptRole,
                                QMessageBox.ApplyRole,
                            )
                        ),
                        None,
                    )
                    or w.button(QMessageBox.Ok)
                    or w.defaultButton()
                    or (w.buttons()[0] if w.buttons() else None)
                )
                if btn:
                    QTest.mouseClick(btn, Qt.LeftButton)
                    accepted_this_round = True
                    accepted_any = True
        if not accepted_this_round:
            break
        QTest.qWait(30)  # give the next box a tick to appear
    return accepted_any


def trigger_menu_action(win, text_contains: str) -> QAction:
    for act in win.findChildren(QAction):
        if text_contains in act.text():
            act.trigger()
            return act
    raise AssertionError(f"Action containing '{text_contains}' not found")


def find_line_edit_by_placeholder(container: QWidget, needle: str) -> QLineEdit | None:
    n = needle.lower()
    for le in container.findChildren(QLineEdit):
        if n in (le.placeholderText() or "").lower():
            return le
    return None


class AutoResponder:
    def __init__(self):
        self._seen: set[int] = set()
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def prehandle_key_prompts_if_present(self):
        for w in _visible_widgets():
            if isinstance(w, QDialog) and (
                _looks_like_set_key_dialog(w) or _looks_like_unlock_dialog(w)
            ):
                fill_first_line_edit_and_accept(w, "ci-secret-key")

    def _tick(self):
        if accept_all_message_boxes(limit=3):
            return

        for w in _visible_widgets():
            if not isinstance(w, QDialog) or not w.isVisible():
                continue

            wid = id(w)
            # Handle first-run / unlock / save-name prompts
            if _looks_like_set_key_dialog(w) or _looks_like_unlock_dialog(w):
                fill_first_line_edit_and_accept(w, "ci-secret-key")
                self._seen.add(wid)
                continue

            if _looks_like_save_version_dialog(w):
                fill_first_line_edit_and_accept(w, None)
                self._seen.add(wid)
                continue

            if _is_history_dialog(w):
                # Don't mark as seen until we've actually clicked the button.
                if _click_revert_in_history(w):
                    accept_all_message_boxes(limit=5)
                    self._seen.add(wid)
                continue


# ---------- dialog classifiers ----------


def _looks_like_set_key_dialog(dlg: QDialog) -> bool:
    labels = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel)).lower()
    title = (dlg.windowTitle() or "").lower()
    has_line = bool(dlg.findChildren(QLineEdit))
    return has_line and (
        "set an encryption key" in title
        or "create a strong passphrase" in labels
        or "encrypts your data" in labels
    )


def _looks_like_unlock_dialog(dlg: QDialog) -> bool:
    labels = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel)).lower()
    title = (dlg.windowTitle() or "").lower()
    has_line = bool(dlg.findChildren(QLineEdit))
    return has_line and ("unlock" in labels or "unlock" in title) and "key" in labels


# ---------- version prompt ----------
def _looks_like_save_version_dialog(dlg: QDialog) -> bool:
    labels = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel)).lower()
    title = (dlg.windowTitle() or "").lower()
    has_line = bool(dlg.findChildren(QLineEdit))
    return has_line and (
        "enter a name" in labels or "name for this version" in labels or "save" in title
    )


# ---------- QFileDialog driver ----------


def drive_qfiledialog_save(path: Path, name_filter: str | None = None):
    dlg = wait_for_widget(QFileDialog, timeout_ms=20000)
    if name_filter:
        try:
            dlg.selectNameFilter(name_filter)
        except Exception:
            pass

    # Prefer typing in the filename edit so Save enables on all styles
    filename_edit = None
    for le in dlg.findChildren(QLineEdit):
        if le.echoMode() == QLineEdit.Normal:
            filename_edit = le
            break

    if filename_edit is not None:
        filename_edit.clear()
        QTest.keyClicks(filename_edit, str(path))
        # Return usually triggers Save in non-native dialogs
        QTest.keyClick(filename_edit, Qt.Key_Return)
    else:
        dlg.selectFile(str(path))
        QTimer.singleShot(0, dlg.accept)

    # Some themes still need an explicit Save click
    _ = click_button_by_text(dlg, "save")


def _is_history_dialog(dlg: QDialog) -> bool:
    if not isinstance(dlg, QDialog) or not dlg.isVisible():
        return False
    title = (dlg.windowTitle() or "").lower()
    if "history" in title:
        return True
    return bool(dlg.findChildren(QListWidget))


def _click_revert_in_history(dlg: QDialog) -> bool:
    """
    Returns True if we successfully clicked an enabled 'Revert' button.
    Ensures a row is actually clicked first so the button enables.
    """
    lists = dlg.findChildren(QListWidget)
    if not lists:
        return False
    versions = max(lists, key=lambda lw: lw.count())
    if versions.count() < 2:
        return False

    # Click the older row (index 1); real click so the dialog enables the button.
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    rect = versions.visualItemRect(versions.item(1))
    QTest.mouseClick(versions.viewport(), Qt.LeftButton, pos=rect.center())
    QTest.qWait(60)

    # Find any enabled button that looks like "revert"
    for btn in dlg.findChildren(QAbstractButton):
        meta = " ".join(
            [(btn.text() or ""), (btn.toolTip() or ""), (btn.objectName() or "")]
        ).lower()
        if "revert" in meta and btn.isEnabled():
            QTest.mouseClick(btn, Qt.LeftButton)
            return True
    return False
