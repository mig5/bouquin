import pytest
from unittest.mock import Mock, patch
import subprocess
from bouquin.version_check import VersionChecker
from PySide6.QtWidgets import QMessageBox, QWidget
from PySide6.QtGui import QPixmap


def test_version_checker_init(app):
    """Test VersionChecker initialization."""
    parent = QWidget()
    checker = VersionChecker(parent)

    assert checker._parent is parent


def test_version_checker_init_no_parent(app):
    """Test VersionChecker initialization without parent."""
    checker = VersionChecker()

    assert checker._parent is None


def test_current_version_returns_version(app):
    """Test getting current version."""
    checker = VersionChecker()

    with patch("importlib.metadata.version", return_value="1.2.3"):
        version = checker.current_version()
        assert version == "1.2.3"


def test_current_version_fallback_on_error(app):
    """Test current version fallback when package not found."""
    checker = VersionChecker()

    import importlib.metadata

    with patch(
        "importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("Not found"),
    ):
        version = checker.current_version()
        assert version == "0.0.0"


def test_parse_version_simple(app):
    """Test parsing simple version string."""
    result = VersionChecker._parse_version("1.2.3")
    assert result == (1, 2, 3)


def test_parse_version_complex(app):
    """Test parsing complex version string with extra text."""
    result = VersionChecker._parse_version("v1.2.3-beta")
    assert result == (1, 2, 3)


def test_parse_version_no_numbers(app):
    """Test parsing version string with no numbers."""
    result = VersionChecker._parse_version("invalid")
    assert result == (0,)


def test_parse_version_single_number(app):
    """Test parsing version with single number."""
    result = VersionChecker._parse_version("5")
    assert result == (5,)


def test_is_newer_version_true(app):
    """Test detecting newer version."""
    checker = VersionChecker()

    assert checker._is_newer_version("1.2.3", "1.2.2") is True
    assert checker._is_newer_version("2.0.0", "1.9.9") is True
    assert checker._is_newer_version("1.3.0", "1.2.9") is True


def test_is_newer_version_false(app):
    """Test detecting same or older version."""
    checker = VersionChecker()

    assert checker._is_newer_version("1.2.3", "1.2.3") is False
    assert checker._is_newer_version("1.2.2", "1.2.3") is False
    assert checker._is_newer_version("0.9.9", "1.0.0") is False


def test_logo_pixmap(app):
    """Test generating logo pixmap."""
    checker = VersionChecker()

    pixmap = checker._logo_pixmap(96)

    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()


def test_logo_pixmap_different_sizes(app):
    """Test generating logo pixmap with different sizes."""
    checker = VersionChecker()

    pixmap_small = checker._logo_pixmap(48)
    pixmap_large = checker._logo_pixmap(128)

    assert not pixmap_small.isNull()
    assert not pixmap_large.isNull()


def test_show_version_dialog(qtbot, app):
    """Test showing version dialog."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    with patch.object(QMessageBox, "exec") as mock_exec:
        with patch("importlib.metadata.version", return_value="1.0.0"):
            checker.show_version_dialog()

            # Dialog should have been shown
            assert mock_exec.called


def test_check_for_updates_network_error(qtbot, app):
    """Test check for updates when network request fails."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    with patch("requests.get", side_effect=Exception("Network error")):
        with patch.object(QMessageBox, "warning") as mock_warning:
            checker.check_for_updates()

            # Should show warning
            assert mock_warning.called


def test_check_for_updates_empty_response(qtbot, app):
    """Test check for updates with empty version string."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.text = "   "
    mock_response.raise_for_status = Mock()

    with patch("requests.get", return_value=mock_response):
        with patch.object(QMessageBox, "warning") as mock_warning:
            checker.check_for_updates()

            # Should show warning about empty version
            assert mock_warning.called


def test_check_for_updates_already_latest(qtbot, app):
    """Test check for updates when already on latest version."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.text = "1.0.0"
    mock_response.raise_for_status = Mock()

    with patch("requests.get", return_value=mock_response):
        with patch("importlib.metadata.version", return_value="1.0.0"):
            with patch.object(QMessageBox, "information") as mock_info:
                checker.check_for_updates()

                # Should show info that we're on latest
                assert mock_info.called


def test_check_for_updates_new_version_available_declined(qtbot, app):
    """Test check for updates when new version is available but user declines."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.text = "2.0.0"
    mock_response.raise_for_status = Mock()

    with patch("requests.get", return_value=mock_response):
        with patch("importlib.metadata.version", return_value="1.0.0"):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
                # Should not proceed to download
                checker.check_for_updates()


def test_check_for_updates_new_version_available_accepted(qtbot, app):
    """Test check for updates when new version is available and user accepts."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.text = "2.0.0"
    mock_response.raise_for_status = Mock()

    with patch("requests.get", return_value=mock_response):
        with patch("importlib.metadata.version", return_value="1.0.0"):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                with patch.object(
                    checker, "_download_and_verify_appimage"
                ) as mock_download:
                    checker.check_for_updates()

                    # Should call download
                    mock_download.assert_called_once_with("2.0.0")


def test_download_file_success(qtbot, app, tmp_path):
    """Test downloading a file successfully."""
    checker = VersionChecker()

    mock_response = Mock()
    mock_response.headers = {"Content-Length": "1000"}
    mock_response.iter_content = Mock(return_value=[b"data" * 25])  # 100 bytes
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "test_file.bin"

    with patch("requests.get", return_value=mock_response):
        checker._download_file("http://example.com/file", dest_path)

        assert dest_path.exists()


def test_download_file_with_progress(qtbot, app, tmp_path):
    """Test downloading a file with progress dialog."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.headers = {"Content-Length": "1000"}
    mock_response.iter_content = Mock(return_value=[b"x" * 100, b"y" * 100])
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "test_file.bin"

    from PySide6.QtWidgets import QProgressDialog

    mock_progress = Mock(spec=QProgressDialog)
    mock_progress.wasCanceled = Mock(return_value=False)
    mock_progress.value = Mock(return_value=0)

    with patch("requests.get", return_value=mock_response):
        checker._download_file(
            "http://example.com/file", dest_path, progress=mock_progress
        )

        # Progress should have been updated
        assert mock_progress.setValue.called


def test_download_file_cancelled(qtbot, app, tmp_path):
    """Test cancelling a file download."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_response = Mock()
    mock_response.headers = {"Content-Length": "1000"}
    mock_response.iter_content = Mock(return_value=[b"x" * 100])
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "test_file.bin"

    from PySide6.QtWidgets import QProgressDialog

    mock_progress = Mock(spec=QProgressDialog)
    mock_progress.wasCanceled = Mock(return_value=True)
    mock_progress.value = Mock(return_value=0)

    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError):
            checker._download_file(
                "http://example.com/file", dest_path, progress=mock_progress
            )


def test_download_file_no_content_length(qtbot, app, tmp_path):
    """Test downloading file without Content-Length header."""
    checker = VersionChecker()

    mock_response = Mock()
    mock_response.headers = {}
    mock_response.iter_content = Mock(return_value=[b"data"])
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "test_file.bin"

    with patch("requests.get", return_value=mock_response):
        checker._download_file("http://example.com/file", dest_path)

        assert dest_path.exists()


def test_download_and_verify_appimage_download_cancelled(qtbot, app, tmp_path):
    """Test AppImage download when user cancels."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(
            checker, "_download_file", side_effect=RuntimeError("Download cancelled")
        ):
            with patch.object(QMessageBox, "information") as mock_info:
                checker._download_and_verify_appimage("2.0.0")

                # Should show cancellation message
                assert mock_info.called


def test_download_and_verify_appimage_download_error(qtbot, app, tmp_path):
    """Test AppImage download when download fails."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(
            checker, "_download_file", side_effect=Exception("Network error")
        ):
            with patch.object(QMessageBox, "critical") as mock_critical:
                checker._download_and_verify_appimage("2.0.0")

                # Should show error message
                assert mock_critical.called


def test_download_and_verify_appimage_gpg_key_error(qtbot, app, tmp_path):
    """Test AppImage verification when GPG key cannot be read."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(checker, "_download_file"):
            with patch(
                "importlib.resources.files", side_effect=Exception("Key not found")
            ):
                with patch.object(QMessageBox, "critical") as mock_critical:
                    checker._download_and_verify_appimage("2.0.0")

                    # Should show error about GPG key
                    assert mock_critical.called


def test_download_and_verify_appimage_gpg_not_found(qtbot, app, tmp_path):
    """Test AppImage verification when GPG is not installed."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_files = Mock()
    mock_files.read_bytes = Mock(return_value=b"fake key data")

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(checker, "_download_file"):
            with patch("importlib.resources.files", return_value=mock_files):
                with patch(
                    "subprocess.run", side_effect=FileNotFoundError("gpg not found")
                ):
                    with patch.object(QMessageBox, "critical") as mock_critical:
                        checker._download_and_verify_appimage("2.0.0")

                        # Should show error about GPG not found
                        assert mock_critical.called


def test_download_and_verify_appimage_verification_failed(qtbot, app, tmp_path):
    """Test AppImage verification when signature verification fails."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_files = Mock()
    mock_files.read_bytes = Mock(return_value=b"fake key data")

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(checker, "_download_file"):
            with patch("importlib.resources.files", return_value=mock_files):
                # First subprocess call (import) succeeds, second (verify) fails
                mock_error = subprocess.CalledProcessError(1, "gpg")
                mock_error.stderr = b"Verification failed"
                with patch("subprocess.run", side_effect=[None, mock_error]):
                    with patch.object(QMessageBox, "critical") as mock_critical:
                        checker._download_and_verify_appimage("2.0.0")

                        # Should show error about verification
                        assert mock_critical.called


def test_download_and_verify_appimage_success(qtbot, app, tmp_path):
    """Test successful AppImage download and verification."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_files = Mock()
    mock_files.read_bytes = Mock(return_value=b"fake key data")

    with patch(
        "bouquin.version_check.QStandardPaths.writableLocation",
        return_value=str(tmp_path),
    ):
        with patch.object(checker, "_download_file"):
            with patch("importlib.resources.files", return_value=mock_files):
                with patch("subprocess.run"):  # Both calls succeed
                    with patch.object(QMessageBox, "information") as mock_info:
                        checker._download_and_verify_appimage("2.0.0")

                        # Should show success message
                        assert mock_info.called


def test_version_comparison_edge_cases(app):
    """Test version comparison with edge cases."""
    checker = VersionChecker()

    # Different lengths
    assert checker._is_newer_version("1.0.0.1", "1.0.0") is True
    assert checker._is_newer_version("1.0", "1.0.0") is False

    # Large numbers
    assert checker._is_newer_version("10.0.0", "9.9.9") is True
    assert checker._is_newer_version("1.100.0", "1.99.0") is True


def test_download_file_creates_parent_directory(qtbot, app, tmp_path):
    """Test that download creates parent directory if needed."""
    checker = VersionChecker()

    mock_response = Mock()
    mock_response.headers = {}
    mock_response.iter_content = Mock(return_value=[b"data"])
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "subdir" / "nested" / "test_file.bin"

    with patch("requests.get", return_value=mock_response):
        checker._download_file("http://example.com/file", dest_path)

        assert dest_path.exists()
        assert dest_path.parent.exists()


def test_show_version_dialog_check_button_clicked(qtbot, app):
    """Test clicking 'Check for updates' button in version dialog."""
    parent = QWidget()
    qtbot.addWidget(parent)
    checker = VersionChecker(parent)

    mock_box = Mock(spec=QMessageBox)
    check_button = Mock()
    mock_box.clickedButton = Mock(return_value=check_button)
    mock_box.addButton = Mock(return_value=check_button)

    with patch("importlib.metadata.version", return_value="1.0.0"):
        with patch("bouquin.version_check.QMessageBox", return_value=mock_box):
            with patch.object(checker, "check_for_updates") as mock_check:
                checker.show_version_dialog()

                # check_for_updates should be called when button is clicked
                if mock_box.clickedButton() is check_button:
                    assert mock_check.called


def test_parse_version_with_letters(app):
    """Test parsing version strings with letters."""
    result = VersionChecker._parse_version("1.2.3rc1")
    assert 1 in result
    assert 2 in result
    assert 3 in result


def test_download_file_invalid_content_length(qtbot, app, tmp_path):
    """Test downloading file with invalid Content-Length header."""
    checker = VersionChecker()

    mock_response = Mock()
    mock_response.headers = {"Content-Length": "invalid"}
    mock_response.iter_content = Mock(return_value=[b"data"])
    mock_response.raise_for_status = Mock()

    dest_path = tmp_path / "test_file.bin"

    with patch("requests.get", return_value=mock_response):
        # Should handle gracefully
        checker._download_file("http://example.com/file", dest_path)

        assert dest_path.exists()
