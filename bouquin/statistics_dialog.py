from __future__ import annotations

import datetime as _dt
from typing import Dict

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QGroupBox,
    QHBoxLayout,
    QComboBox,
    QScrollArea,
    QWidget,
    QSizePolicy,
)

from . import strings
from .db import DBManager


# ---------- Activity heatmap ----------


class DateHeatmap(QWidget):
    """
    Small calendar heatmap for activity by date.

    Data is a mapping: datetime.date -> integer value.
    """

    date_clicked = Signal(_dt.date)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Dict[_dt.date, int] = {}
        self._start: _dt.date | None = None
        self._end: _dt.date | None = None
        self._max_value: int = 0

        self._cell = 12
        self._gap = 3
        self._margin_left = 30
        self._margin_top = 10
        self._margin_bottom = 24
        self._margin_right = 10

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_data(self, data: Dict[_dt.date, int]) -> None:
        """Replace dataset and recompute layout."""
        self._data = {k: int(v) for k, v in (data or {}).items() if v is not None}
        if not self._data:
            self._start = self._end = None
            self._max_value = 0
        else:
            earliest = min(self._data.keys())
            latest = max(self._data.keys())
            self._start = earliest - _dt.timedelta(days=earliest.weekday())
            self._end = latest
            self._max_value = max(self._data.values()) if self._data else 0

        self.updateGeometry()
        self.update()

    # QWidget overrides ---------------------------------------------------

    def sizeHint(self) -> QSize:
        if not self._start or not self._end:
            height = (
                self._margin_top + self._margin_bottom + 7 * (self._cell + self._gap)
            )
            # some default width
            width = (
                self._margin_left + self._margin_right + 20 * (self._cell + self._gap)
            )
            return QSize(width, height)

        day_count = (self._end - self._start).days + 1
        weeks = (day_count + 6) // 7  # ceil

        width = (
            self._margin_left
            + self._margin_right
            + weeks * (self._cell + self._gap)
            + self._gap
        )
        height = (
            self._margin_top
            + self._margin_bottom
            + 7 * (self._cell + self._gap)
            + self._gap
        )
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        sz = self.sizeHint()
        return QSize(min(300, sz.width()), sz.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self._start or not self._end:
            return

        palette = self.palette()
        bg_no_data = palette.base().color()
        active = palette.highlight().color()

        painter.setPen(QPen(Qt.NoPen))

        day_count = (self._end - self._start).days + 1
        weeks = (day_count + 6) // 7

        for week in range(weeks):
            for dow in range(7):
                idx = week * 7 + dow
                date = self._start + _dt.timedelta(days=idx)
                if date > self._end:
                    value = 0
                else:
                    value = self._data.get(date, 0)

                x = self._margin_left + week * (self._cell + self._gap)
                y = self._margin_top + dow * (self._cell + self._gap)

                if value <= 0 or self._max_value <= 0:
                    color = bg_no_data
                else:
                    ratio = max(0.1, min(1.0, value / float(self._max_value)))
                    color = QColor(active)
                    # Lighter for low values, darker for high values
                    lighten = 150 - int(50 * ratio)  # 150 ≈ light, 100 ≈ original
                    color = color.lighter(lighten)

                painter.fillRect(
                    x,
                    y,
                    self._cell,
                    self._cell,
                    QBrush(color),
                )

        painter.setPen(palette.text().color())
        fm = painter.fontMetrics()

        # --- weekday labels on left -------------------------------------
        # Python's weekday(): Monday=0 ... Sunday=6, same as your rows.
        weekday_labels = ["M", "T", "W", "T", "F", "S", "S"]

        for dow in range(7):
            label = weekday_labels[dow]
            text_width = fm.horizontalAdvance(label)

            # Center text vertically in the cell
            y_center = (
                self._margin_top + dow * (self._cell + self._gap) + self._cell / 2
            )
            baseline_y = int(y_center + fm.ascent() / 2 - fm.descent() / 2)

            # Right-align text just to the left of the first column
            x = self._margin_left - self._gap - 2 - text_width

            painter.drawText(x, baseline_y, label)

        prev_month = None
        for week in range(weeks):
            date = self._start + _dt.timedelta(days=week * 7)
            if date > self._end:
                break

            if prev_month == date.month:
                continue
            prev_month = date.month

            label = date.strftime("%b")

            x_center = (
                self._margin_left + week * (self._cell + self._gap) + self._cell / 2
            )
            y = self._margin_top + 7 * (self._cell + self._gap) + fm.ascent()

            text_width = fm.horizontalAdvance(label)
            painter.drawText(
                int(x_center - text_width / 2),
                int(y),
                label,
            )

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        # No data = nothing to click
        if not self._start or not self._end:
            return

        # Qt6: position(), older: pos()
        pos = event.position() if hasattr(event, "position") else event.pos()
        x = pos.x()
        y = pos.y()

        # Outside grid area (left of weekday labels or above rows)
        if x < self._margin_left or y < self._margin_top:
            return

        cell_span = self._cell + self._gap
        col = int((x - self._margin_left) // cell_span)  # week index
        row = int((y - self._margin_top) // cell_span)  # dow (0..6)

        # Only 7 rows (Mon–Sun)
        if not (0 <= row < 7):
            return

        # Only as many weeks as we actually have
        day_count = (self._end - self._start).days + 1
        weeks = (day_count + 6) // 7
        if col < 0 or col >= weeks:
            return

        idx = col * 7 + row
        date = self._start + _dt.timedelta(days=idx)

        # Skip trailing empty cells beyond the last date
        if date > self._end:
            return

        self.date_clicked.emit(date)


# ---------- Statistics dialog itself ----------


class StatisticsDialog(QDialog):
    """
    Shows aggregate statistics and the date heatmap with a metric switcher.
    """

    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self._db = db

        self.setWindowTitle(strings._("statistics"))
        self.setMinimumWidth(600)
        root = QVBoxLayout(self)

        (
            pages_with_content,
            total_revisions,
            page_most_revisions,
            page_most_revisions_count,
            words_by_date,
            total_words,
            unique_tags,
            page_most_tags,
            page_most_tags_count,
            revisions_by_date,
        ) = self._gather_stats()

        # --- Numeric summary at the top ----------------------------------
        form = QFormLayout()
        root.addLayout(form)

        form.addRow(
            strings._("stats_pages_with_content"),
            QLabel(str(pages_with_content)),
        )
        form.addRow(
            strings._("stats_total_revisions"),
            QLabel(str(total_revisions)),
        )

        if page_most_revisions:
            form.addRow(
                strings._("stats_page_most_revisions"),
                QLabel(f"{page_most_revisions} ({page_most_revisions_count})"),
            )
        else:
            form.addRow(strings._("stats_page_most_revisions"), QLabel("—"))

        form.addRow(
            strings._("stats_total_words"),
            QLabel(str(total_words)),
        )

        # Unique tag names
        form.addRow(
            strings._("stats_unique_tags"),
            QLabel(str(unique_tags)),
        )

        if page_most_tags:
            form.addRow(
                strings._("stats_page_most_tags"),
                QLabel(f"{page_most_tags} ({page_most_tags_count})"),
            )
        else:
            form.addRow(strings._("stats_page_most_tags"), QLabel("—"))

        # --- Heatmap with switcher ---------------------------------------
        if words_by_date or revisions_by_date:
            group = QGroupBox(strings._("stats_activity_heatmap"))
            group_layout = QVBoxLayout(group)

            # Metric selector
            combo_row = QHBoxLayout()
            combo_row.addWidget(QLabel(strings._("stats_heatmap_metric")))
            self.metric_combo = QComboBox()
            self.metric_combo.addItem(strings._("stats_metric_words"), "words")
            self.metric_combo.addItem(strings._("stats_metric_revisions"), "revisions")
            combo_row.addWidget(self.metric_combo)
            combo_row.addStretch(1)
            group_layout.addLayout(combo_row)

            self._heatmap = DateHeatmap()
            self._words_by_date = words_by_date
            self._revisions_by_date = revisions_by_date

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(self._heatmap)
            group_layout.addWidget(scroll)

            root.addWidget(group)

            # Default to "words"
            self._apply_metric("words")
            self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        else:
            root.addWidget(QLabel(strings._("stats_no_data")))

    # ---------- internal helpers ----------

    def _apply_metric(self, metric: str) -> None:
        if metric == "revisions":
            self._heatmap.set_data(self._revisions_by_date)
        else:
            self._heatmap.set_data(self._words_by_date)

    def _on_metric_changed(self, index: int) -> None:
        metric = self.metric_combo.currentData()
        if metric:
            self._apply_metric(metric)

    def _gather_stats(self):
        return self._db.gather_stats()
