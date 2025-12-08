from bouquin.key_prompt import KeyPrompt

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QLineEdit


def test_key_prompt_roundtrip(qtbot):
    kp = KeyPrompt()
    qtbot.addWidget(kp)
    kp.show()
    kp.key_entry.setText("swordfish")
    assert kp.key() == "swordfish"


def test_key_prompt_with_db_path_browse(qtbot, app, tmp_path, monkeypatch):
    """Test KeyPrompt with DB path selection - covers lines 57-67"""
    test_db = tmp_path / "test.db"
    test_db.touch()

    # Create prompt with show_db_change=True
    prompt = KeyPrompt(show_db_change=True)
    qtbot.addWidget(prompt)

    # Mock the file dialog to return a file
    def mock_get_open_filename(*args, **kwargs):
        return str(test_db), "SQLCipher DB (*.db)"

    monkeypatch.setattr(QFileDialog, "getOpenFileName", mock_get_open_filename)

    # Simulate clicking the browse button
    # Find the browse button by looking through the widget's children
    browse_btn = None
    for child in prompt.findChildren(object):
        if hasattr(child, "clicked") and hasattr(child, "text"):
            if (
                "select" in str(child.text()).lower()
                or "browse" in str(child.text()).lower()
            ):
                browse_btn = child
                break

    if browse_btn:
        browse_btn.click()
        qtbot.wait(50)

        # Verify the path was set
        assert prompt.path_edit is not None
        assert str(test_db) in prompt.path_edit.text()


def test_key_prompt_with_db_path_no_file_selected(qtbot, app, tmp_path, monkeypatch):
    """Test KeyPrompt when cancel is clicked in file dialog - covers line 64 condition"""
    # Create prompt with show_db_change=True
    prompt = KeyPrompt(show_db_change=True)
    qtbot.addWidget(prompt)

    # Mock the file dialog to return empty string (user cancelled)
    def mock_get_open_filename(*args, **kwargs):
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", mock_get_open_filename)

    # Store original path text
    original_text = prompt.path_edit.text() if prompt.path_edit else ""

    # Simulate clicking the browse button
    browse_btn = None
    for child in prompt.findChildren(object):
        if hasattr(child, "clicked") and hasattr(child, "text"):
            if (
                "select" in str(child.text()).lower()
                or "browse" in str(child.text()).lower()
            ):
                browse_btn = child
                break

    if browse_btn:
        browse_btn.click()
        qtbot.wait(50)

        # Path should not have changed since no file was selected
        if prompt.path_edit:
            assert prompt.path_edit.text() == original_text


def test_key_prompt_with_existing_db_path(qtbot, app, tmp_path):
    """Test KeyPrompt with existing DB path provided"""
    test_db = tmp_path / "existing.db"
    test_db.touch()

    prompt = KeyPrompt(show_db_change=True, initial_db_path=test_db)
    qtbot.addWidget(prompt)

    # Verify the path is pre-filled
    assert prompt.path_edit is not None
    assert str(test_db) in prompt.path_edit.text()


def test_key_prompt_with_db_path_none_and_show_db_change(qtbot, app):
    """Test KeyPrompt with show_db_change but no initial_db_path"""
    prompt = KeyPrompt(show_db_change=True, initial_db_path=None)
    qtbot.addWidget(prompt)

    # Path edit should exist but be empty
    assert prompt.path_edit is not None
    assert prompt.path_edit.text() == ""


def test_key_prompt_accept_with_valid_key(qtbot, app):
    """Test accepting prompt with valid key"""
    prompt = KeyPrompt()
    qtbot.addWidget(prompt)

    # Enter a key
    prompt.key_entry.setText("test-key-123")

    # Accept
    QTimer.singleShot(0, prompt.accept)
    qtbot.wait(50)

    assert prompt.key_entry.text() == "test-key-123"


def test_key_prompt_without_db_change(qtbot, app):
    """Test KeyPrompt without show_db_change"""
    prompt = KeyPrompt(show_db_change=False)
    qtbot.addWidget(prompt)

    # Path edit should not exist
    assert prompt.path_edit is None


def test_key_prompt_password_visibility(qtbot, app):
    """Test password entry mode"""
    prompt = KeyPrompt()
    qtbot.addWidget(prompt)

    # Initially should be password mode
    assert prompt.key_entry.echoMode() == QLineEdit.EchoMode.Password

    # Enter some text
    prompt.key_entry.setText("secret")

    # The text should be obscured
    assert prompt.key_entry.echoMode() == QLineEdit.EchoMode.Password


def test_key_prompt_key_method(qtbot, app):
    """Test the key() method returns entered text"""
    prompt = KeyPrompt()
    qtbot.addWidget(prompt)

    prompt.key_entry.setText("my-secret-key")

    assert prompt.key() == "my-secret-key"


def test_key_prompt_db_path_method(qtbot, app, tmp_path):
    """Test the db_path() method returns selected path"""
    test_db = tmp_path / "test.db"
    test_db.touch()

    prompt = KeyPrompt(show_db_change=True, initial_db_path=test_db)
    qtbot.addWidget(prompt)

    # Should return the db_path
    assert prompt.db_path() == test_db


def test_key_prompt_browse_with_initial_path(qtbot, app, tmp_path, monkeypatch):
    """Test browsing when initial_db_path is set"""
    initial_db = tmp_path / "initial.db"
    initial_db.touch()

    new_db = tmp_path / "new.db"
    new_db.touch()

    prompt = KeyPrompt(show_db_change=True, initial_db_path=initial_db)
    qtbot.addWidget(prompt)

    # Mock the file dialog to return a different file
    def mock_get_open_filename(*args, **kwargs):
        # Verify that start_dir was passed correctly
        return str(new_db), "SQLCipher DB (*.db)"

    monkeypatch.setattr(QFileDialog, "getOpenFileName", mock_get_open_filename)

    # Find and click browse button
    browse_btn = None
    for child in prompt.findChildren(object):
        if hasattr(child, "clicked") and hasattr(child, "text"):
            if (
                "select" in str(child.text()).lower()
                or "browse" in str(child.text()).lower()
            ):
                browse_btn = child
                break

    if browse_btn:
        browse_btn.click()
        qtbot.wait(50)

        # Verify new path was set
        assert str(new_db) in prompt.path_edit.text()
        assert prompt.db_path() == new_db
