import numpy as np
import pytest

from pyqtgraph.Qt import QtCore

from bouquin.tag_graph_dialog import TagGraphDialog, DraggableGraphItem


# ---------------------------------------------------------------------------
# Helpers for DraggableGraphItem tests
# ---------------------------------------------------------------------------


class DummyPos:
    """Simple object with x()/y() so it looks like a QPointF to the code."""

    def __init__(self, x, y):
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class FakePoint:
    """Minimal object returned from scatter.pointsAt()."""

    def __init__(self, idx):
        self._idx = idx

    def index(self):
        return self._idx


class FakeDragEvent:
    """Stub object that looks like pyqtgraph's mouse drag event."""

    def __init__(self, stage, button, start_pos, move_pos):
        # stage is one of: "start", "move", "finish"
        self._stage = stage
        self._button = button
        self._start_pos = start_pos
        self._pos = move_pos
        self.accepted = False
        self.ignored = False

    # Life-cycle ---------------------------------------------------------
    def isStart(self):
        return self._stage == "start"

    def isFinish(self):
        return self._stage == "finish"

    # Buttons / positions ------------------------------------------------
    def button(self):
        return self._button

    def buttonDownPos(self):
        return self._start_pos

    def pos(self):
        return self._pos

    # Accept / ignore ----------------------------------------------------
    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class FakeHoverEvent:
    """Stub for hoverEvent tests."""

    def __init__(self, pos=None, exit=False):
        self._pos = pos
        self._exit = exit

    def isExit(self):
        return self._exit

    def pos(self):
        return self._pos


# ---------------------------------------------------------------------------
# DraggableGraphItem
# ---------------------------------------------------------------------------


def test_draggable_graph_item_setdata_caches_kwargs(app):
    item = DraggableGraphItem()
    pos1 = np.array([[0.0, 0.0]], dtype=float)
    adj = np.zeros((0, 2), dtype=int)
    sizes = np.array([5.0], dtype=float)

    # First call sets all kwargs
    item.setData(pos=pos1, adj=adj, size=sizes)

    assert item.pos is pos1
    assert "adj" in item._data_kwargs
    assert "size" in item._data_kwargs

    # Second call only passes pos; cached kwargs should keep size/adj
    pos2 = np.array([[1.0, 1.0]], dtype=float)
    item.setData(pos=pos2)

    assert item.pos is pos2
    assert item._data_kwargs["adj"] is adj
    # size should still be present and unchanged
    assert np.all(item._data_kwargs["size"] == sizes)


def test_draggable_graph_item_drag_updates_position_and_calls_callback(app):
    moved = []

    def on_pos_changed(pos):
        # Store a copy so later mutations don't affect our assertion
        moved.append(np.array(pos, copy=True))

    item = DraggableGraphItem(on_position_changed=on_pos_changed)

    # Simple 2-node graph
    pos = np.array([[0.0, 0.0], [5.0, 5.0]], dtype=float)
    adj = np.array([[0, 1]], dtype=int)
    item.setData(pos=pos, adj=adj, size=np.array([5.0, 5.0], dtype=float))

    # Make pointsAt always return the first node
    item.scatter.pointsAt = lambda p: [FakePoint(0)]

    # Start drag on node 0 at (0, 0)
    start_ev = FakeDragEvent(
        stage="start",
        button=QtCore.Qt.MouseButton.LeftButton,
        start_pos=DummyPos(0.0, 0.0),
        move_pos=None,
    )
    item.mouseDragEvent(start_ev)
    assert item._drag_index == 0
    assert start_ev.accepted
    assert not start_ev.ignored

    # Move mouse to (2, 3) – node 0 should follow exactly
    move_ev = FakeDragEvent(
        stage="move",
        button=QtCore.Qt.MouseButton.LeftButton,
        start_pos=DummyPos(0.0, 0.0),
        move_pos=DummyPos(2.0, 3.0),
    )
    item.mouseDragEvent(move_ev)
    assert move_ev.accepted
    assert not move_ev.ignored

    assert item.pos.shape == (2, 2)
    assert item.pos[0, 0] == pytest.approx(2.0)
    assert item.pos[0, 1] == pytest.approx(3.0)

    # Callback should have been invoked with the updated positions
    assert moved, "on_position_changed should be called at least once"
    np.testing.assert_allclose(moved[-1][0], [2.0, 3.0], atol=1e-6)

    # Finish drag: internal state should reset
    finish_ev = FakeDragEvent(
        stage="finish",
        button=QtCore.Qt.MouseButton.LeftButton,
        start_pos=DummyPos(0.0, 0.0),
        move_pos=DummyPos(2.0, 3.0),
    )
    item.mouseDragEvent(finish_ev)
    assert finish_ev.accepted
    assert item._drag_index is None
    assert item._drag_offset is None


def test_draggable_graph_item_ignores_non_left_button(app):
    item = DraggableGraphItem()

    pos = np.array([[0.0, 0.0]], dtype=float)
    adj = np.zeros((0, 2), dtype=int)
    item.setData(pos=pos, adj=adj, size=np.array([5.0], dtype=float))

    # pointsAt would return something, but the button is not left,
    # so the event should be ignored.
    item.scatter.pointsAt = lambda p: [FakePoint(0)]

    ev = FakeDragEvent(
        stage="start",
        button=QtCore.Qt.MouseButton.RightButton,
        start_pos=DummyPos(0.0, 0.0),
        move_pos=None,
    )
    item.mouseDragEvent(ev)
    assert ev.ignored
    assert not ev.accepted
    assert item._drag_index is None


def test_draggable_graph_item_hover_reports_index_and_exit(app):
    hovered = []

    def on_hover(idx, ev):
        hovered.append(idx)

    item = DraggableGraphItem(on_hover=on_hover)

    # Case 1: exit event should report None
    ev_exit = FakeHoverEvent(exit=True)
    item.hoverEvent(ev_exit)
    assert hovered[-1] is None

    # Case 2: no points under mouse -> None
    item.scatter.pointsAt = lambda p: []
    ev_none = FakeHoverEvent(pos=DummyPos(0.0, 0.0))
    item.hoverEvent(ev_none)
    assert hovered[-1] is None

    # Case 3: one point under mouse -> its index
    item.scatter.pointsAt = lambda p: [FakePoint(3)]
    ev_hit = FakeHoverEvent(pos=DummyPos(1.0, 2.0))
    item.hoverEvent(ev_hit)
    assert hovered[-1] == 3


# ---------------------------------------------------------------------------
# TagGraphDialog
# ---------------------------------------------------------------------------


class EmptyTagDB:
    """DB stub that returns no tag data."""

    def get_tag_cooccurrences(self):
        return {}, [], {}


class SimpleTagDB:
    """Deterministic stub for tag co-occurrence data."""

    def __init__(self):
        self.called = False

    def get_tag_cooccurrences(self):
        self.called = True
        tags_by_id = {
            1: (1, "alpha", "#ff0000"),
            2: (2, "beta", "#00ff00"),
            3: (3, "gamma", "#0000ff"),
        }
        edges = [
            (1, 2, 3),
            (2, 3, 1),
        ]
        tag_page_counts = {1: 5, 2: 3, 3: 1}
        return tags_by_id, edges, tag_page_counts


def test_tag_graph_dialog_handles_empty_db(app, qtbot):
    dlg = TagGraphDialog(EmptyTagDB())
    qtbot.addWidget(dlg)
    dlg.show()

    # When there are no tags, nothing should be populated
    assert dlg._tag_ids == []
    assert dlg._label_items == []
    assert dlg._tag_names == {}
    assert dlg._tag_page_counts == {}


def test_tag_graph_dialog_populates_graph_from_db(app, qtbot):
    db = SimpleTagDB()
    dlg = TagGraphDialog(db)
    qtbot.addWidget(dlg)
    dlg.show()

    assert db.called

    # Basic invariants about the populated state
    assert dlg._tag_ids == [1, 2, 3]
    assert dlg._tag_names[1] == "alpha"
    assert dlg._tag_page_counts[1] == 5

    # GraphItem should have one position per node
    assert dlg.graph_item.pos.shape == (3, 2)

    # Labels and halo state should match number of tags
    assert len(dlg._label_items) == 3
    assert len(dlg._halo_sizes) == 3
    assert len(dlg._halo_brushes) == 3


def test_tag_graph_dialog_on_positions_changed_updates_labels_and_halo(
    app, qtbot, monkeypatch
):
    db = SimpleTagDB()
    dlg = TagGraphDialog(db)
    qtbot.addWidget(dlg)
    dlg.show()

    assert len(dlg._label_items) == 3

    # Set up fake halo sizes/brushes so the halo branch runs
    dlg._halo_sizes = [10.0, 20.0, 30.0]
    dlg._halo_brushes = ["a", "b", "c"]

    captured = {}

    def fake_set_data(*, x, y, size, brush, pen):
        captured["x"] = x
        captured["y"] = y
        captured["size"] = size
        captured["brush"] = brush
        captured["pen"] = pen

    monkeypatch.setattr(dlg._halo_item, "setData", fake_set_data)

    # New layout positions
    pos = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=float)
    dlg._on_positions_changed(pos)

    # Each label should be slightly below its node (y + 0.30)
    for i, label in enumerate(dlg._label_items):
        assert label.pos().x() == pytest.approx(pos[i, 0])
        assert label.pos().y() == pytest.approx(pos[i, 1] + 0.30)

    # Halo layer should receive the updated coordinates and our sizes/brushes
    assert captured["x"] == [1.0, 3.0, 5.0]
    assert captured["y"] == [2.0, 4.0, 6.0]
    assert captured["size"] == dlg._halo_sizes
    assert captured["brush"] == dlg._halo_brushes
    assert captured["pen"] is None


def test_tag_graph_dialog_hover_index_shows_and_hides_tooltip(app, qtbot, monkeypatch):
    db = SimpleTagDB()
    dlg = TagGraphDialog(db)
    qtbot.addWidget(dlg)
    dlg.show()

    shown = {}
    hidden = {"called": False}

    def fake_show_text(pos, text, widget):
        shown["pos"] = pos
        shown["text"] = text
        shown["widget"] = widget

    def fake_hide_text():
        hidden["called"] = True

    # Patch the module-level QToolTip used by TagGraphDialog
    monkeypatch.setattr("bouquin.tag_graph_dialog.QToolTip.showText", fake_show_text)
    monkeypatch.setattr("bouquin.tag_graph_dialog.QToolTip.hideText", fake_hide_text)

    # Hover over first node (index 0)
    dlg._on_hover_index(0, ev=None)
    assert "alpha" in shown["text"]
    assert "page" in shown["text"]
    assert shown["widget"] is dlg

    # Now simulate leaving the item entirely
    dlg._on_hover_index(None, ev=None)
    assert hidden["called"]
