from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QSettings, QStandardPaths

from .db import DBConfig

APP_ORG = "Bouquin"
APP_NAME = "Bouquin"


def get_settings() -> QSettings:
    return QSettings(APP_ORG, APP_NAME)


def load_db_config() -> DBConfig:
    s = get_settings()
    default_db_path = str(
        Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        / "notebook.db"
    )

    path = Path(s.value("db/path", default_db_path))
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
    s.setValue("db/path", str(cfg.path))
    s.setValue("db/key", str(cfg.key))
    s.setValue("ui/idle_minutes", str(cfg.idle_minutes))
    s.setValue("ui/theme", str(cfg.theme))
    s.setValue("ui/move_todos", str(cfg.move_todos))
    s.setValue("ui/locale", str(cfg.locale))
