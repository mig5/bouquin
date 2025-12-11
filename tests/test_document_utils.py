import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget


def test_open_document_from_db_success(qtbot, app, fresh_db):
    """Test successfully opening a document."""
    # Import here to avoid circular import issues
    from bouquin.document_utils import open_document_from_db

    # Add a project and document
    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".txt"))
    doc_path.write_text("test content for document")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        # Mock QDesktopServices.openUrl
        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            # Call the function
            success = open_document_from_db(
                fresh_db, doc_id, doc_path.name, parent_widget=None
            )

            # Verify success
            assert success is True

            # Verify openUrl was called with a QUrl
            assert mock_open.called
            args = mock_open.call_args[0]
            assert isinstance(args[0], QUrl)

            # Verify the URL points to a local file
            url_string = args[0].toString()
            assert url_string.startswith("file://")
            assert "bouquin_doc_" in url_string
            assert doc_path.suffix in url_string
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_with_parent_widget(qtbot, app, fresh_db):
    """Test opening a document with a parent widget provided."""
    from bouquin.document_utils import open_document_from_db

    # Create a parent widget
    parent = QWidget()
    qtbot.addWidget(parent)

    # Add a project and document
    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".pdf"))
    doc_path.write_text("PDF content")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            success = open_document_from_db(
                fresh_db, doc_id, doc_path.name, parent_widget=parent
            )

            assert success is True
            assert mock_open.called
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_nonexistent_document(qtbot, app, fresh_db):
    """Test opening a non-existent document returns False."""
    from bouquin.document_utils import open_document_from_db

    # Try to open a document that doesn't exist
    success = open_document_from_db(
        fresh_db, doc_id=99999, file_name="nonexistent.txt", parent_widget=None
    )

    # Should return False
    assert success is False


def test_open_document_from_db_shows_error_with_parent(qtbot, app, fresh_db):
    """Test that error dialog is shown when parent widget is provided."""
    from bouquin.document_utils import open_document_from_db

    parent = QWidget()
    qtbot.addWidget(parent)

    # Mock QMessageBox.warning
    with patch.object(QMessageBox, "warning") as mock_warning:
        success = open_document_from_db(
            fresh_db, doc_id=99999, file_name="nonexistent.txt", parent_widget=parent
        )

        # Should return False and show warning
        assert success is False
        assert mock_warning.called

        # Verify warning was shown with correct parent
        call_args = mock_warning.call_args[0]
        assert call_args[0] is parent


def test_open_document_from_db_no_error_dialog_without_parent(qtbot, app, fresh_db):
    """Test that no error dialog is shown when parent widget is None."""
    from bouquin.document_utils import open_document_from_db

    with patch.object(QMessageBox, "warning") as mock_warning:
        success = open_document_from_db(
            fresh_db, doc_id=99999, file_name="nonexistent.txt", parent_widget=None
        )

        # Should return False but NOT show warning
        assert success is False
        assert not mock_warning.called


def test_open_document_from_db_preserves_file_extension(qtbot, app, fresh_db):
    """Test that the temporary file has the correct extension."""
    from bouquin.document_utils import open_document_from_db

    # Test various file extensions
    extensions = [".txt", ".pdf", ".docx", ".xlsx", ".jpg", ".png"]

    for ext in extensions:
        proj_id = fresh_db.add_project(f"Project for {ext}")
        doc_path = Path(tempfile.mktemp(suffix=ext))
        doc_path.write_text(f"content for {ext}")

        try:
            doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

            with patch.object(
                QDesktopServices, "openUrl", return_value=True
            ) as mock_open:
                open_document_from_db(fresh_db, doc_id, doc_path.name)

                # Get the URL that was opened
                url = mock_open.call_args[0][0]
                url_string = url.toString()

                # Verify the extension is preserved
                assert ext in url_string, f"Extension {ext} not found in {url_string}"
        finally:
            doc_path.unlink(missing_ok=True)


def test_open_document_from_db_file_without_extension(qtbot, app, fresh_db):
    """Test opening a document without a file extension."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp())  # No suffix
    doc_path.write_text("content without extension")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            success = open_document_from_db(fresh_db, doc_id, doc_path.name)

            # Should still succeed
            assert success is True
            assert mock_open.called
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_desktop_services_failure(qtbot, app, fresh_db):
    """Test handling when QDesktopServices.openUrl returns False."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".txt"))
    doc_path.write_text("test content")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        # Mock openUrl to return False (failure)
        with patch.object(QDesktopServices, "openUrl", return_value=False):
            success = open_document_from_db(fresh_db, doc_id, doc_path.name)

            # Should return False
            assert success is False
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_binary_content(qtbot, app, fresh_db):
    """Test opening a document with binary content."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".bin"))

    # Write some binary data
    binary_data = bytes([0, 1, 2, 3, 255, 254, 253])
    doc_path.write_bytes(binary_data)

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            success = open_document_from_db(fresh_db, doc_id, doc_path.name)

            assert success is True
            assert mock_open.called
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_large_file(qtbot, app, fresh_db):
    """Test opening a large document."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".bin"))

    # Create a 1MB file
    large_data = b"x" * (1024 * 1024)
    doc_path.write_bytes(large_data)

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            success = open_document_from_db(fresh_db, doc_id, doc_path.name)

            assert success is True
            assert mock_open.called
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_temp_file_prefix(qtbot, app, fresh_db):
    """Test that temporary files have the correct prefix."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".txt"))
    doc_path.write_text("test")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            open_document_from_db(fresh_db, doc_id, doc_path.name)

            url = mock_open.call_args[0][0]
            url_path = url.toLocalFile()

            # Verify the temp file has the bouquin_doc_ prefix
            assert "bouquin_doc_" in url_path
    finally:
        doc_path.unlink(missing_ok=True)


def test_open_document_from_db_multiple_calls(qtbot, app, fresh_db):
    """Test opening the same document multiple times."""
    from bouquin.document_utils import open_document_from_db

    proj_id = fresh_db.add_project("Test Project")
    doc_path = Path(tempfile.mktemp(suffix=".txt"))
    doc_path.write_text("test content")

    try:
        doc_id = fresh_db.add_document_from_path(proj_id, str(doc_path))

        with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open:
            # Open the same document 3 times
            for _ in range(3):
                success = open_document_from_db(fresh_db, doc_id, doc_path.name)
                assert success is True

            # Should have been called 3 times
            assert mock_open.call_count == 3

            # Each call should create a different temp file
            call_urls = [call[0][0].toString() for call in mock_open.call_args_list]
            # All URLs should be different (different temp files)
            assert len(set(call_urls)) == 3
    finally:
        doc_path.unlink(missing_ok=True)
