"""
Utility functions for document operations.

This module provides shared functionality for document handling across
different widgets (TodaysDocumentsWidget, DocumentsDialog, SearchResultsDialog,
and TagBrowserDialog).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from . import strings

if TYPE_CHECKING:
    from .db import DBManager


def open_document_from_db(
    db: DBManager, doc_id: int, file_name: str, parent_widget: Optional[QWidget] = None
) -> bool:
    """
    Open a document by fetching it from the database and opening with system default app.
    """
    # Fetch document data from database
    try:
        data = db.document_data(doc_id)
    except Exception as e:
        # Show error dialog if parent widget is provided
        if parent_widget:
            QMessageBox.warning(
                parent_widget,
                strings._("project_documents_title"),
                strings._("documents_open_failed").format(error=str(e)),
            )
        return False

    # Extract file extension
    suffix = Path(file_name).suffix or ""

    # Create temporary file with same extension
    tmp = tempfile.NamedTemporaryFile(
        prefix="bouquin_doc_",
        suffix=suffix,
        delete=False,
    )

    # Write data to temp file
    try:
        tmp.write(data)
        tmp.flush()
    finally:
        tmp.close()

    # Open with system default application
    success = QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))

    return success
