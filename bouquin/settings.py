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
    move_todos_include_weekends = s.value(
        "ui/move_todos_include_weekends", False, type=bool
    )
    tags = s.value("ui/tags", True, type=bool)
    time_log = s.value("ui/time_log", True, type=bool)
    reminders = s.value("ui/reminders", True, type=bool)
    reminders_webhook_url = s.value("ui/reminders_webhook_url", None, type=str)
    reminders_webhook_secret = s.value("ui/reminders_webhook_secret", None, type=str)
    documents = s.value("ui/documents", True, type=bool)
    invoicing = s.value("ui/invoicing", False, type=bool)
    locale = s.value("ui/locale", "en", type=str)
    font_size = s.value("ui/font_size", 11, type=int)
    return DBConfig(
        path=path,
        key=key,
        idle_minutes=idle,
        theme=theme,
        move_todos=move_todos,
        move_todos_include_weekends=move_todos_include_weekends,
        tags=tags,
        time_log=time_log,
        reminders=reminders,
        reminders_webhook_url=reminders_webhook_url,
        reminders_webhook_secret=reminders_webhook_secret,
        documents=documents,
        invoicing=invoicing,
        locale=locale,
        font_size=font_size,
    )


def save_db_config(cfg: DBConfig) -> None:
    s = get_settings()
    s.setValue("db/default_db", str(cfg.path))
    s.setValue("db/key", str(cfg.key))
    s.setValue("ui/idle_minutes", str(cfg.idle_minutes))
    s.setValue("ui/theme", str(cfg.theme))
    s.setValue("ui/move_todos", str(cfg.move_todos))
    s.setValue("ui/move_todos_include_weekends", str(cfg.move_todos_include_weekends))
    s.setValue("ui/tags", str(cfg.tags))
    s.setValue("ui/time_log", str(cfg.time_log))
    s.setValue("ui/reminders", str(cfg.reminders))
    s.setValue("ui/reminders_webhook_url", str(cfg.reminders_webhook_url))
    s.setValue("ui/reminders_webhook_secret", str(cfg.reminders_webhook_secret))
    s.setValue("ui/documents", str(cfg.documents))
    s.setValue("ui/invoicing", str(cfg.invoicing))
    s.setValue("ui/locale", str(cfg.locale))
    s.setValue("ui/font_size", str(cfg.font_size))
