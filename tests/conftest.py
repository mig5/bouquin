import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

# Ensure the nested package directory (repo_root/bouquin) is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_PARENT = PROJECT_ROOT / "bouquin"
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(scope="session", autouse=True)
def isolate_qsettings(tmp_path_factory):
    cfgdir = tmp_path_factory.mktemp("qt_cfg")
    os.environ["XDG_CONFIG_HOME"] = str(cfgdir)
    yield


@pytest.fixture
def tmp_db_cfg(tmp_path):
    from bouquin.db import DBConfig

    default_db = tmp_path / "notebook.db"
    key = "test-secret-key"
    return DBConfig(
        path=default_db,
        key=key,
        idle_minutes=0,
        theme="light",
        move_todos=True,
        tags=True,
        time_log=True,
        reminders=True,
        locale="en",
        font_size=11,
    )


@pytest.fixture
def fresh_db(tmp_db_cfg):
    from bouquin.db import DBManager

    db = DBManager(tmp_db_cfg)
    ok = db.connect()
    assert ok, "DB connect() should succeed"
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _stub_code_block_editor_dialog(monkeypatch):
    """
    In tests, replace the interactive CodeBlockEditorDialog with a tiny stub
    that never shows a real QDialog and never blocks on exec().
    """
    import bouquin.markdown_editor as markdown_editor
    from PySide6.QtWidgets import QDialog

    class _TestCodeBlockEditorDialog:
        def __init__(
            self, code: str, language: str | None, parent=None, allow_delete=False
        ):
            # Simulate what the real dialog would “start with”
            self._code = code
            self._language = language

        def exec(self) -> int:
            # Pretend the user clicked OK immediately.
            # (If you prefer “Cancel by default”, return Rejected instead.)
            return QDialog.DialogCode.Accepted

        def code(self) -> str:
            # In tests we just return the initial code unchanged.
            return self._code

        def language(self) -> str | None:
            # Ditto for language.
            return self._language

    # MarkdownEditor imported CodeBlockEditorDialog into its own module,
    # so patch that name – everything in MarkdownEditor will use this stub.
    monkeypatch.setattr(
        markdown_editor, "CodeBlockEditorDialog", _TestCodeBlockEditorDialog
    )


# --- Freeze Qt time helper (for alarm parsing tests) ---
@pytest.fixture
def freeze_qt_time(monkeypatch):
    """Freeze QDateTime.currentDateTime/QTime.currentTime to midday today.

    This avoids flakiness when tests run close to midnight, so that
    QTime.currentTime().addSecs(3600) is still the same calendar day.
    """
    import bouquin.main_window as _mwmod
    from PySide6.QtCore import QDate, QTime, QDateTime

    today = QDate.currentDate()
    fixed_time = QTime(12, 0)
    fixed_dt = QDateTime(today, fixed_time)

    # Patch the *imported* Qt symbols that main_window uses
    monkeypatch.setattr(
        _mwmod.QDateTime, "currentDateTime", staticmethod(lambda: QDateTime(fixed_dt))
    )
    monkeypatch.setattr(
        _mwmod.QTime, "currentTime", staticmethod(lambda: QTime(fixed_time))
    )
    yield
