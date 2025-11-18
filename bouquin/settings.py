from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QSettings, QStandardPaths

from .db import DBConfig

APP_ORG = "Bouquin"
APP_NAME = "Bouquin"


def get_settings() -> QSettings:
    return QSettings(APP_ORG, APP_NAME)


def _default_db_location() -> Path:
    """Where we put the notebook if nothing has been configured yet."""
    base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    base.mkdir(parents=True, exist_ok=True)
    return base / "notebook.db"


def load_db_config() -> DBConfig:
    s = get_settings()

    # --- DB Path -------------------------------------------------------
    # Prefer the new key; fall back to the legacy one.
    path_str = s.value("db/default_db", "", type=str)
    if not path_str:
        legacy = s.value("db/path", "", type=str)
        if legacy:
            path_str = legacy
            # migrate and clean up the old key
            s.setValue("db/default_db", legacy)
            s.remove("db/path")
    path = Path(path_str) if path_str else _default_db_location()

    # --- Other settings ------------------------------------------------
    key = s.value("db/key", "")

    idle = s.value("ui/idle_minutes", 15, type=int)
    theme = s.value("ui/theme", "system", type=str)
    move_todos = s.value("ui/move_todos", False, type=bool)
    locale = s.value("ui/locale", "en", type=str)
    return DBConfig(
        path=path,
        key=key,
        idle_minutes=idle,
        theme=theme,
        move_todos=move_todos,
        locale=locale,
    )


def save_db_config(cfg: DBConfig) -> None:
    s = get_settings()
    s.setValue("db/default_db", str(cfg.path))
    s.setValue("db/key", str(cfg.key))
    s.setValue("ui/idle_minutes", str(cfg.idle_minutes))
    s.setValue("ui/theme", str(cfg.theme))
    s.setValue("ui/move_todos", str(cfg.move_todos))
    s.setValue("ui/locale", str(cfg.locale))
