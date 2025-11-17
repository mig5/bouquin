import bouquin.bug_report_dialog as bugmod
from bouquin.bug_report_dialog import BugReportDialog


def test_bug_report_truncates_text_to_max_chars(qtbot):
    dlg = BugReportDialog()
    qtbot.addWidget(dlg)
    dlg.show()

    max_chars = getattr(dlg, "MAX_CHARS", 5000)

    # Make a string longer than the allowed maximum
    long_text = "x" * (max_chars + 50)

    # Setting the text should trigger textChanged -> _enforce_max_length
    dlg.text_edit.setPlainText(long_text)

    # Let Qt process the signal/slot if needed
    qtbot.wait(10)

    current = dlg.text_edit.toPlainText()
    assert len(current) == max_chars
    assert current == long_text[:max_chars]


def test_bug_report_allows_up_to_max_chars_unchanged(qtbot):
    dlg = BugReportDialog()
    qtbot.addWidget(dlg)
    dlg.show()

    max_chars = getattr(dlg, "MAX_CHARS", 5000)
    exact_text = "y" * max_chars

    dlg.text_edit.setPlainText(exact_text)
    qtbot.wait(10)

    current = dlg.text_edit.toPlainText()
    # Should not be trimmed if it's exactly the limit
    assert len(current) == max_chars
    assert current == exact_text


def test_bug_report_send_success_201_shows_info_and_accepts(qtbot, monkeypatch):
    dlg = BugReportDialog()
    qtbot.addWidget(dlg)
    dlg.show()

    # Non-empty message so we don't hit the "empty" warning branch
    dlg.text_edit.setPlainText("Hello, something broke.")
    qtbot.wait(10)

    # Make version() deterministic
    def fake_version(pkg_name):
        assert pkg_name == "bouquin"
        return "1.2.3"

    monkeypatch.setattr(
        bugmod.importlib.metadata, "version", fake_version, raising=True
    )

    # Capture the POST call and fake a 201 Created response
    calls = {}

    class DummyResp:
        status_code = 201

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return DummyResp()

    monkeypatch.setattr(bugmod.requests, "post", fake_post, raising=True)

    # Capture information / critical message boxes
    info_called = {}
    crit_called = {}

    def fake_info(parent, title, text, *a, **k):
        info_called["title"] = title
        info_called["text"] = str(text)
        return 0

    def fake_critical(parent, title, text, *a, **k):
        crit_called["title"] = title
        crit_called["text"] = str(text)
        return 0

    monkeypatch.setattr(
        bugmod.QMessageBox, "information", staticmethod(fake_info), raising=True
    )
    monkeypatch.setattr(
        bugmod.QMessageBox, "critical", staticmethod(fake_critical), raising=True
    )

    # Don't actually close the dialog in the test; just record that accept() was called
    accepted = {}

    def fake_accept():
        accepted["called"] = True

    dlg.accept = fake_accept

    # Call the send logic directly
    dlg._send()

    # --- Assertions ---------------------------------------------------------

    # POST was called with the expected URL and JSON payload
    assert calls["url"] == f"{bugmod.BUG_REPORT_HOST}/{bugmod.ROUTE}"
    assert calls["json"]["message"] == "Hello, something broke."
    assert calls["json"]["version"] == "1.2.3"
    # No attachment fields expected any more

    # Success path: information dialog shown, critical not shown
    assert "title" in info_called
    assert "text" in info_called
    assert crit_called == {}

    # Dialog accepted
    assert accepted.get("called") is True


def test_bug_report_send_failure_non_201_shows_critical_and_not_accepted(
    qtbot, monkeypatch
):
    dlg = BugReportDialog()
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.text_edit.setPlainText("Broken again.")
    qtbot.wait(10)

    # Stub version() again
    monkeypatch.setattr(
        bugmod.importlib.metadata,
        "version",
        lambda name: "9.9.9",
        raising=True,
    )

    # Fake a non-201 response (e.g. 500)
    calls = {}

    class DummyResp:
        status_code = 500

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return DummyResp()

    monkeypatch.setattr(bugmod.requests, "post", fake_post, raising=True)

    info_called = {}
    crit_called = {}

    def fake_info(parent, title, text, *a, **k):
        info_called["title"] = title
        info_called["text"] = str(text)
        return 0

    def fake_critical(parent, title, text, *a, **k):
        crit_called["title"] = title
        crit_called["text"] = str(text)
        return 0

    monkeypatch.setattr(
        bugmod.QMessageBox, "information", staticmethod(fake_info), raising=True
    )
    monkeypatch.setattr(
        bugmod.QMessageBox, "critical", staticmethod(fake_critical), raising=True
    )

    accepted = {}

    def fake_accept():
        accepted["called"] = True

    dlg.accept = fake_accept

    dlg._send()

    # POST still called with JSON payload
    assert calls["url"] == f"{bugmod.BUG_REPORT_HOST}/{bugmod.ROUTE}"
    assert calls["json"]["message"] == "Broken again."
    assert calls["json"]["version"] == "9.9.9"

    # Failure path: critical dialog shown, information not shown
    assert crit_called  # non-empty
    assert info_called == {}

    # Dialog should NOT be accepted on failure
    assert accepted.get("called") is not True
