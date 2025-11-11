from bouquin.settings import (
    get_settings,
    load_db_config,
    save_db_config,
)
from bouquin.db import DBConfig


def test_load_and_save_db_config_roundtrip(app, tmp_path):
    s = get_settings()
    for k in ["db/path", "db/key", "ui/idle_minutes", "ui/theme", "ui/move_todos"]:
        s.remove(k)

    cfg = DBConfig(
        path=tmp_path / "notes.db",
        key="abc123",
        idle_minutes=7,
        theme="dark",
        move_todos=True,
    )
    save_db_config(cfg)

    loaded = load_db_config()
    assert loaded.path == cfg.path
    assert loaded.key == cfg.key
    assert loaded.idle_minutes == cfg.idle_minutes
    assert loaded.theme == cfg.theme
    assert loaded.move_todos == cfg.move_todos
