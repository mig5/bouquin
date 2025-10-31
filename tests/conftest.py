import os
import pytest

# Run Qt without a visible display (CI-safe)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def fake_key_prompt_cls():
    """A KeyPrompt stand-in that immediately returns Accepted with a fixed key."""
    from PySide6.QtWidgets import QDialog

    class FakeKeyPrompt:
        accepted_count = 0

        def __init__(self, *a, **k):
            self._key = "sekret"

        def exec(self):
            FakeKeyPrompt.accepted_count += 1
            return QDialog.Accepted

        def key(self):
            return self._key

    return FakeKeyPrompt


@pytest.fixture
def fake_db_cls():
    """In-memory DB fake that mimics the subset of DBManager used by the UI."""
    class FakeDB:
        def __init__(self, cfg):
            self.cfg = cfg
            self.data = {}
            self.connected_key = None
            self.closed = False

        def connect(self):
            # record the key that UI supplied
            self.connected_key = self.cfg.key
            return True

        def get_entry(self, date_iso: str) -> str:
            return self.data.get(date_iso, "")

        def upsert_entry(self, date_iso: str, content: str) -> None:
            self.data[date_iso] = content

        def dates_with_content(self) -> list[str]:
            return [d for d, t in self.data.items() if t.strip()]

        def close(self) -> None:
            self.closed = True

    return FakeDB
