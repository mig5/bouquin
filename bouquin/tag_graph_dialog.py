import networkx as nx
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PySide6.QtWidgets import QDialog, QVBoxLayout, QToolTip
from PySide6.QtGui import QFont, QCursor, QColor

from .db import DBManager
from . import strings


class DraggableGraphItem(pg.GraphItem):
    """GraphItem where individual nodes can be dragged with the left mouse button,
    and hover events can be reported back to the owning dialog.
    """

    def __init__(self, on_position_changed=None, on_hover=None, **kwds):
        # Our own fields MUST be set before super().__init__ because
        # GraphItem.__init__ will call self.setData(...)
        self._drag_index = None
        self._drag_offset = None
        self._on_position_changed = on_position_changed
        self._on_hover = on_hover
        self.pos = None
        self._data_kwargs = {}  # cache of last setData kwargs

        super().__init__(**kwds)
        self.setAcceptHoverEvents(True)

    def setData(self, **kwds):
        """Cache kwargs so we don't lose size/adj/brush on drag."""
        if "pos" in kwds:
            self.pos = kwds["pos"]
        self._data_kwargs.update(kwds)
        super().setData(**self._data_kwargs)

    def mouseDragEvent(self, ev):
        # --- start of drag ---
        if ev.isStart():
            if ev.button() != QtCore.Qt.MouseButton.LeftButton:
                ev.ignore()
                return

            pos = ev.buttonDownPos()
            pts = self.scatter.pointsAt(pos)

            # pointsAt may return an empty list/array
            if pts is None or len(pts) == 0:
                ev.ignore()
                return

            spot = pts[0]
            self._drag_index = spot.index()

            node_pos = np.array(self.pos[self._drag_index], dtype=float)

            if hasattr(pos, "x"):
                mouse = np.array([pos.x(), pos.y()], dtype=float)
            else:
                mouse = np.array(pos, dtype=float)

            self._drag_offset = node_pos - mouse
            ev.accept()
            return

        # --- end of drag ---
        if ev.isFinish():
            self._drag_index = None
            self._drag_offset = None
            ev.accept()
            return

        # --- drag in progress ---
        if self._drag_index is None:
            ev.ignore()
            return

        pos = ev.pos()
        if hasattr(pos, "x"):
            mouse = np.array([pos.x(), pos.y()], dtype=float)
        else:
            mouse = np.array(pos, dtype=float)

        new_pos = mouse + self._drag_offset
        self.pos[self._drag_index] = new_pos  # mutate in-place

        # Repaint graph, preserving all the other kwargs (size, adj, colours, ...)
        self.setData(pos=self.pos)

        if self._on_position_changed is not None:
            self._on_position_changed(self.pos)

        ev.accept()

    def hoverEvent(self, ev):
        """Report which node (if any) is under the mouse while hovering."""
        # Leaving the item entirely
        if ev.isExit():
            if self._on_hover is not None:
                self._on_hover(None, ev)
            return

        pos = ev.pos()
        pts = self.scatter.pointsAt(pos)

        if pts is None or len(pts) == 0:
            if self._on_hover is not None:
                self._on_hover(None, ev)
            return

        idx = pts[0].index()
        if self._on_hover is not None:
            self._on_hover(idx, ev)


class TagGraphDialog(QDialog):
    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(strings._("tag_graph"))

        layout = QVBoxLayout(self)
        self.view = pg.GraphicsLayoutWidget()
        layout.addWidget(self.view)

        self.plot = self.view.addPlot()
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")

        # Dark-ish background, Grafana / neon style
        self.view.setBackground("#050816")
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.getViewBox().setDefaultPadding(0.15)

        # State for tags / edges / labels / halo
        self._label_items = []
        self._tag_ids = []
        self._tag_names = {}
        self._tag_page_counts = {}

        self._halo_sizes = []
        self._halo_brushes = []

        self.graph_item = DraggableGraphItem(
            on_position_changed=self._on_positions_changed,
            on_hover=self._on_hover_index,
        )
        self.plot.addItem(self.graph_item)

        # Separate scatter for "halo" glow behind nodes
        self._halo_item = pg.ScatterPlotItem(pxMode=True)
        self._halo_item.setZValue(-1)  # draw behind nodes/labels
        self.plot.addItem(self._halo_item)

        self._populate_graph(db)

    def _populate_graph(self, db: DBManager):
        tags_by_id, edges, tag_page_counts = db.get_tag_cooccurrences()

        if not tags_by_id:
            return

        # Map tag_id -> index
        tag_ids = list(tags_by_id.keys())
        self._tag_ids = tag_ids
        self._tag_page_counts = dict(tag_page_counts)
        self._tag_names = {tid: tags_by_id[tid][1] for tid in tag_ids}

        idx_of = {tid: i for i, tid in enumerate(tag_ids)}
        N = len(tag_ids)

        # ---- Layout: prefer a weighted spring layout via networkx (topic islands)
        if edges:
            G = nx.Graph()
            for tid in tag_ids:
                G.add_node(tid)
            for t1, t2, w in edges:
                G.add_edge(t1, t2, weight=w)

            pos_dict = nx.spring_layout(G, weight="weight", k=1.2, iterations=80)
            pos = np.array([pos_dict[tid] for tid in tag_ids], dtype=float)
        else:
            # Fallback: random-ish blob
            pos = np.random.normal(size=(N, 2))

        # Adjacency (edges)
        adj = np.array([[idx_of[t1], idx_of[t2]] for t1, t2, _ in edges], dtype=int)

        # Node sizes: proportional to how often tag is used
        max_pages = max(tag_page_counts.values() or [1])
        sizes = np.array(
            [10 + 20 * (tag_page_counts.get(tid, 0) / max_pages) for tid in tag_ids],
            dtype=float,
        )

        # ---- Neon-style nodes ----
        # Inner fill: dark; outline: tag hex colour
        node_brushes = []
        node_pens = []

        dark_fill = (5, 8, 22, 230)  # almost background, slightly lighter

        # For halo
        halo_sizes = []
        halo_brushes = []

        for i, tid in enumerate(tag_ids):
            _id, name, color = tags_by_id[tid]

            # node interior (dark) + bright outline
            node_brushes.append(pg.mkBrush(dark_fill))
            node_pens.append(pg.mkPen(color, width=2.5))

            # halo: semi-transparent version of DB colour, larger than node
            qcol = QColor(color)
            qcol.setAlpha(90)
            halo_brushes.append(pg.mkBrush(qcol))
            halo_sizes.append(sizes[i] * 1.8)

        self._halo_sizes = halo_sizes
        self._halo_brushes = halo_brushes

        # ---- Edges: softer neon-ish lines with opacity / width based on co-occurrence ----
        if edges:
            weights = np.array([w for _, _, w in edges], dtype=float)
            max_w = weights.max() if weights.size else 1.0
            weight_factors = (weights / max_w).clip(0.0, 1.0)

            # bright cyan-ish neon
            base_color = (56, 189, 248)  # tailwind-ish cyan-400
            edge_pens = []

            for wf in weight_factors:
                alpha = int(40 + 160 * wf)  # 40–200
                width = 0.7 + 2.3 * wf  # 0.7–3.0
                edge_pens.append(pg.mkPen((*base_color, alpha), width=width))
        else:
            edge_pens = None

        # Assign data to GraphItem (this will set self.graph_item.pos)
        self.graph_item.setData(
            pos=pos,
            adj=adj,
            size=sizes,
            symbolBrush=node_brushes,
            symbolPen=node_pens,
            edgePen=edge_pens,
            pxMode=True,
        )

        # ---- Neon halo layer (behind nodes) ----
        xs = [p[0] for p in pos]
        ys = [p[1] for p in pos]
        self._halo_item.setData(
            x=xs,
            y=ys,
            size=self._halo_sizes,
            brush=self._halo_brushes,
            pen=None,
        )

        # ---- Add text labels for each tag ----
        self._label_items = []  # reset
        font = QFont()
        font.setPointSize(8)

        for i, tid in enumerate(tag_ids):
            _id, name, color = tags_by_id[tid]
            label = pg.TextItem(text=name, color=color, anchor=(0.5, 0.5))
            label.setFont(font)
            self.plot.addItem(label)
            self._label_items.append(label)

        # Initial placement of labels
        self._on_positions_changed(pos)

    def _on_positions_changed(self, pos):
        """Called by DraggableGraphItem whenever node positions change."""
        if not self._label_items:
            return

        # Update labels
        for i, label in enumerate(self._label_items):
            label.setPos(float(pos[i, 0]), float(pos[i, 1]) + 0.30)

        # Update halo positions to match nodes
        if self._halo_sizes and self._halo_brushes:
            xs = [p[0] for p in pos]
            ys = [p[1] for p in pos]
            self._halo_item.setData(
                x=xs,
                y=ys,
                size=self._halo_sizes,
                brush=self._halo_brushes,
                pen=None,
            )

    def _on_hover_index(self, index, ev):
        """Show '<tag>: N pages' when hovering a node."""
        if index is None or not self._tag_ids:
            QToolTip.hideText()
            return

        tag_id = self._tag_ids[index]
        name = self._tag_names.get(tag_id, "")
        count = self._tag_page_counts.get(tag_id, 0)
        text = f"{name}: {count} page{'s' if count != 1 else ''}"

        QToolTip.showText(QCursor.pos(), text, self)
