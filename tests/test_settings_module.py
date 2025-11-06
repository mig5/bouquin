from bouquin.db import DBConfig
import bouquin.settings as settings


class FakeSettings:
    def __init__(self):
        self.store = {}

    def value(self, key, default=None, type=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value


def test_save_and_load_db_config_roundtrip(monkeypatch, tmp_path):
    fake = FakeSettings()
    monkeypatch.setattr(settings, "get_settings", lambda: fake)

    cfg = DBConfig(path=tmp_path / "db.sqlite", key="k", idle_minutes=7, theme="dark")
    settings.save_db_config(cfg)

    # Now read back into a new DBConfig
    cfg2 = settings.load_db_config()
    assert cfg2.path == cfg.path
    assert cfg2.key == "k"
    assert cfg2.idle_minutes == "7"
    assert cfg2.theme == "dark"
