from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess  # nosec
import tempfile
from importlib.resources import files
from pathlib import Path

import requests
from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from . import strings
from .settings import APP_NAME

# Where to fetch the latest version string from
VERSION_URL = "https://mig5.net/bouquin/version.txt"

# Name of the installed distribution according to pyproject.toml
# (used with importlib.metadata.version)
DIST_NAME = "bouquin"

# Base URL where AppImages are hosted
APPIMAGE_BASE_URL = "https://git.mig5.net/mig5/bouquin/releases/download"

# Where we expect to find the bundled public key, relative to the *installed* package.
GPG_PUBKEY_RESOURCE = ("bouquin", "keys", "mig5.asc")


class VersionChecker:
    """
    Handles:
      * showing the version dialog
      * checking for updates
      * downloading & verifying a new AppImage

    All dialogs use `parent` as their parent widget.
    """

    def __init__(self, parent: QWidget | None = None):
        self._parent = parent

    # ---------- Version helpers ---------- #

    def _logo_pixmap(self, logical_size: int = 96) -> QPixmap:
        """
        Render the SVG logo to a high-DPI-aware QPixmap so it stays crisp.
        """
        svg_path = Path(__file__).resolve().parent / "icons" / "bouquin.svg"

        # Logical size (what Qt layouts see)
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        img_size = int(logical_size * dpr)

        image = QImage(img_size, img_size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        renderer = QSvgRenderer(str(svg_path))
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()

        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def current_version(self) -> str:
        """
        Return the current app version as reported by importlib.metadata
        """
        try:
            return importlib.metadata.version(DIST_NAME)
        except importlib.metadata.PackageNotFoundError:
            # Fallback for editable installs / dev trees
            return "0.0.0"

    @staticmethod
    def _parse_version(v: str) -> tuple[int, ...]:
        """
        Very small helper to compare simple semantic versions like 1.2.3.
        Extracts numeric components and returns them as a tuple.
        """
        parts = re.findall(r"\d+", v)
        if not parts:
            return (0,)
        return tuple(int(p) for p in parts)

    def _is_newer_version(self, available: str, current: str) -> bool:
        """
        True if `available` > `current` according to _parse_version.
        """
        return self._parse_version(available) > self._parse_version(current)

    def _running_in_appimage(self) -> bool:
        return "APPIMAGE" in os.environ

    # ---------- Public entrypoint for Help → Version ---------- #

    def show_version_dialog(self) -> None:
        """
        Show the Version dialog with a 'Check for updates' button.
        """
        version = self.current_version()
        version_formatted = f"{APP_NAME} {version}"

        box = QMessageBox(self._parent)
        box.setWindowTitle(strings._("version"))

        box.setIconPixmap(self._logo_pixmap(96))

        box.setText(version_formatted)

        check_button = box.addButton(
            strings._("check_for_updates"), QMessageBox.ActionRole
        )

        box.addButton(QMessageBox.Close)
        box.exec()

        if box.clickedButton() is check_button:
            self.check_for_updates()

    # ---------- Core update logic ---------- #

    def check_for_updates(self) -> None:
        """
        Fetch VERSION_URL, compare against the current version, and optionally
        download + verify a new AppImage.
        """
        current = self.current_version()

        try:
            resp = requests.get(VERSION_URL, timeout=10)
            resp.raise_for_status()
            available_raw = resp.text.strip()
        except Exception as e:
            QMessageBox.warning(
                self._parent,
                strings._("update"),
                strings._("could_not_check_for_updates") + str(e),
            )
            return

        if not available_raw:
            QMessageBox.warning(
                self._parent,
                strings._("update"),
                strings._("update_server_returned_an_empty_version_string"),
            )
            return

        if not self._is_newer_version(available_raw, current):
            QMessageBox.information(
                self._parent,
                strings._("update"),
                strings._("you_are_running_the_latest_version") + f"({current}).",
            )
            return

        # Newer version is available

        if self._running_in_appimage():
            # If running in an AppImage, offer to download the new AppImage
            reply = QMessageBox.question(
                self._parent,
                strings._("update"),
                (
                    strings._("there_is_a_new_version_available")
                    + available_raw
                    + "\n\n"
                    + strings._("download_the_appimage")
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            self._download_and_verify_appimage(available_raw)
        else:
            # If not running in an AppImage, just report that there's a new version.
            QMessageBox.information(
                self._parent,
                strings._("update"),
                (strings._("there_is_a_new_version_available") + available_raw),
            )
            return

    # ---------- Download + verification helpers ---------- #
    def _download_file(
        self,
        url: str,
        dest_path: Path,
        timeout: int = 30,
        progress: QProgressDialog | None = None,
        label: str | None = None,
    ) -> None:
        """
        Stream a URL to a local file, optionally updating a QProgressDialog.
        If the user cancels via the dialog, raises RuntimeError.
        """
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        total_bytes: int | None = None
        content_length = resp.headers.get("Content-Length")
        if content_length is not None:
            try:
                total_bytes = int(content_length)
            except ValueError:
                total_bytes = None

        if progress is not None:
            progress.setLabelText(
                label or strings._("downloading") + f" {dest_path.name}..."
            )
            # Unknown size → busy indicator; known size → real range
            if total_bytes is not None and total_bytes > 0:
                progress.setRange(0, total_bytes)
            else:
                progress.setRange(0, 0)  # pragma: no cover
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()

        downloaded = 0
        with dest_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue  # pragma: no cover

                f.write(chunk)
                downloaded += len(chunk)

                if progress is not None:
                    if total_bytes is not None and total_bytes > 0:
                        progress.setValue(downloaded)
                    else:
                        # Just bump a little so the dialog looks alive
                        progress.setValue(progress.value() + 1)  # pragma: no cover
                    QApplication.processEvents()

                    if progress.wasCanceled():
                        raise RuntimeError(strings._("download_cancelled"))

        if progress is not None and total_bytes is not None and total_bytes > 0:
            progress.setValue(total_bytes)
            QApplication.processEvents()

    def _download_and_verify_appimage(self, version: str) -> None:
        """
        Download the AppImage + its GPG signature to the user's Downloads dir,
        then verify it with a bundled public key.
        """
        # Where to put the file
        download_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not download_dir:
            download_dir = os.path.expanduser("~/Downloads")
        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        # Construct AppImage filename and URLs
        appimage_path = download_dir / "Bouquin.AppImage"
        sig_path = Path(str(appimage_path) + ".asc")

        appimage_url = f"{APPIMAGE_BASE_URL}/{version}/Bouquin.AppImage"
        sig_url = f"{appimage_url}.asc"

        # Progress dialog covering both downloads
        progress = QProgressDialog(
            "Downloading update...",
            "Cancel",
            0,
            100,
            self._parent,
        )
        progress.setWindowTitle(strings._("update"))
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        try:
            # AppImage download
            self._download_file(
                appimage_url,
                appimage_path,
                progress=progress,
                label=strings._("downloading") + " Bouquin.AppImage...",
            )
            # Signature download (usually tiny, but we still show it)
            self._download_file(
                sig_url,
                sig_path,
                progress=progress,
                label=strings._("downloading") + " signature...",
            )
        except RuntimeError:
            # User cancelled
            for p in (appimage_path, sig_path):
                try:
                    if p.exists():
                        p.unlink()  # pragma: no cover
                except OSError:  # pragma: no cover
                    pass

            progress.close()
            QMessageBox.information(
                self._parent,
                strings._("update"),
                strings._("download_cancelled"),
            )
            return
        except Exception as e:
            # Other error
            for p in (appimage_path, sig_path):
                try:
                    if p.exists():
                        p.unlink()  # pragma: no cover
                except OSError:  # pragma: no cover
                    pass

            progress.close()
            QMessageBox.critical(
                self._parent,
                strings._("update"),
                strings._("failed_to_download_update") + str(e),
            )
            return

        progress.close()

        # Load the bundled public key
        try:
            pkg, *rel = GPG_PUBKEY_RESOURCE
            pubkey_bytes = (files(pkg) / "/".join(rel)).read_bytes()
        except Exception as e:  # pragma: no cover
            QMessageBox.critical(
                self._parent,
                strings._("update"),
                strings._("could_not_read_bundled_gpg_public_key") + str(e),
            )
            # On failure, delete the downloaded files for safety
            for p in (appimage_path, sig_path):
                try:
                    if p.exists():
                        p.unlink()
                except OSError:  # pragma: no cover
                    pass
            return

        # Use a temporary GNUPGHOME so we don't touch the user's main keyring
        try:
            with tempfile.TemporaryDirectory() as gnupg_home:
                pubkey_path = Path(gnupg_home) / "pubkey.asc"
                pubkey_path.write_bytes(pubkey_bytes)

                # Import the key
                subprocess.run(
                    ["gpg", "--homedir", gnupg_home, "--import", str(pubkey_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )  # nosec

                # Verify the signature
                subprocess.run(
                    [
                        "gpg",
                        "--homedir",
                        gnupg_home,
                        "--verify",
                        str(sig_path),
                        str(appimage_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )  # nosec
        except FileNotFoundError:
            # gpg not installed / not on PATH
            for p in (appimage_path, sig_path):
                try:
                    if p.exists():
                        p.unlink()  # pragma: no cover
                except OSError:  # pragma: no cover
                    pass

            QMessageBox.critical(
                self._parent,
                strings._("update"),
                strings._("could_not_find_gpg_executable"),
            )
            return
        except subprocess.CalledProcessError as e:
            for p in (appimage_path, sig_path):
                try:
                    if p.exists():
                        p.unlink()  # pragma: no cover
                except OSError:  # pragma: no cover
                    pass

            QMessageBox.critical(
                self._parent,
                strings._("update"),
                strings._("gpg_signature_verification_failed")
                + e.stderr.decode(errors="ignore"),
            )
            return

        # Success
        QMessageBox.information(
            self._parent,
            strings._("update"),
            strings._("downloaded_and_verified_new_appimage") + str(appimage_path),
        )
