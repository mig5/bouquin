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

    db_path = tmp_path / "notebook.db"
    key = "test-secret-key"
    return DBConfig(
        path=db_path, key=key, idle_minutes=0, theme="light", move_todos=True
    )


@pytest.fixture
def fresh_db(tmp_db_cfg):
    from bouquin.db import DBManager

    db = DBManager(tmp_db_cfg)
    ok = db.connect()
    assert ok, "DB connect() should succeed"
    yield db
    db.close()
