from bouquin.settings import (
    get_settings,
    load_db_config,
    save_db_config,
)
from bouquin.db import DBConfig


def _clear_db_settings():
    s = get_settings()
    for k in [
        "db/default_db",
        "db/path",  # legacy key
        "db/key",
        "ui/idle_minutes",
        "ui/theme",
        "ui/move_todos",
        "ui/tags",
        "ui/time_log",
        "ui/reminders",
        "ui/locale",
        "ui/font_size",
    ]:
        s.remove(k)


def test_load_and_save_db_config_roundtrip(app, tmp_path):
    _clear_db_settings()

    cfg = DBConfig(
        path=tmp_path / "notes.db",
        key="abc123",
        idle_minutes=7,
        theme="dark",
        move_todos=True,
        tags=True,
        time_log=True,
        reminders=True,
        locale="en",
        font_size=11,
    )
    save_db_config(cfg)

    loaded = load_db_config()
    assert loaded.path == cfg.path
    assert loaded.key == cfg.key
    assert loaded.idle_minutes == cfg.idle_minutes
    assert loaded.theme == cfg.theme
    assert loaded.move_todos == cfg.move_todos
    assert loaded.tags == cfg.tags
    assert loaded.time_log == cfg.time_log
    assert loaded.reminders == cfg.reminders
    assert loaded.locale == cfg.locale
    assert loaded.font_size == cfg.font_size


def test_load_db_config_migrates_legacy_db_path(app, tmp_path):
    _clear_db_settings()
    s = get_settings()

    legacy_path = tmp_path / "legacy.db"
    s.setValue("db/path", str(legacy_path))

    cfg = load_db_config()

    # Uses the legacy value…
    assert cfg.path == legacy_path

    # …but also migrates to the new key and clears the old one.
    assert s.value("db/default_db", "", type=str) == str(legacy_path)
    assert s.value("db/path", "", type=str) == ""
