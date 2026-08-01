#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Line measurement tool.

Interaction:
  - Toggle ON      → click once to place the start point.
  - Move mouse     → live preview of the line (start → cursor).
  - Click again    → finalize the end point; line is drawn.
  - Drag center    → move the whole line.
  - Drag endpoint  → reposition that endpoint (live update).
  - Toggle OFF     → line is erased.

Physical length is computed using the pixel sizes stored in the two
scale bars (scale_bar_1 for X, scale_bar_2 for Y).
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui


_HANDLE_HIT_PX  = 12
_HANDLE_SIZE_PX = 10


def _line_pen():
    p = pg.mkPen('y', width=2)
    p.setCosmetic(True)
    return p

def _handle_pen():
    p = pg.mkPen('c', width=1)
    p.setCosmetic(True)
    return p

def _handle_brush():
    return QtGui.QBrush(QtGui.QColor(0, 200, 255, 200))


class LineProfileDialog(QtWidgets.QDialog):
    """ImageJ-style line intensity profile — a plot that live-updates
    with the current line and the current frame.

    Held by LineProfileManager; the manager pushes new samples via
    `set_profile(distances_um, intensities, length_um)` every time the
    line or the frame changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Line Profile")
        self.resize(720, 360)
        # Non-modal, and doesn't take focus off the main viewer.
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)

        lay = QtWidgets.QVBoxLayout(self)

        self.header = QtWidgets.QLabel("no line placed")
        self.header.setStyleSheet(
            "font-family: monospace; padding: 4px 8px; color: #cfc;")
        lay.addWidget(self.header)

        self.plot = pg.PlotWidget()
        self.plot.setBackground('k')
        self.plot.setLabel('bottom', 'Distance', units='µm')
        self.plot.setLabel('left',  'Intensity')
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self.plot.plot([], [], pen=pg.mkPen('y', width=2))
        lay.addWidget(self.plot, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        self.freeze_chk = QtWidgets.QCheckBox("Freeze (pause live updates)")
        self.freeze_chk.setToolTip(
            "When ticked the plot stops following new frames and line edits.")
        btn_row.addWidget(self.freeze_chk)
        btn_row.addStretch()
        self.copy_btn = QtWidgets.QPushButton("Copy to clipboard")
        self.copy_btn.setToolTip("Copy the current profile as tab-separated "
                                 "'distance_um\\tintensity' lines.")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(self.copy_btn)
        lay.addLayout(btn_row)

        self._last_x: Optional[np.ndarray] = None
        self._last_y: Optional[np.ndarray] = None

    def set_profile(self, distances_um: np.ndarray,
                    intensities: np.ndarray, length_um: float) -> None:
        if self.freeze_chk.isChecked():
            return
        self._last_x = distances_um
        self._last_y = intensities
        self._curve.setData(distances_um, intensities)
        if intensities.size > 0:
            self.header.setText(
                f"length: {length_um:.2f} µm   |   "
                f"samples: {intensities.size}   |   "
                f"min: {float(intensities.min()):.1f}   "
                f"max: {float(intensities.max()):.1f}   "
                f"mean: {float(intensities.mean()):.1f}"
            )
        else:
            self.header.setText("no line placed")

    def clear(self) -> None:
        self._curve.setData([], [])
        self._last_x = self._last_y = None
        self.header.setText("no line placed")

    def _copy_to_clipboard(self) -> None:
        if self._last_x is None or self._last_y is None:
            return
        lines = ["distance_um\tintensity"]
        for x, y in zip(self._last_x, self._last_y):
            lines.append(f"{x:.6g}\t{y:.6g}")
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))


class LineProfileManager:

    _IDLE          = 'idle'          # waiting for first click
    _PLACING       = 'placing'       # start set, tracking mouse for end
    _PLACED        = 'placed'        # line finalised
    _MOVING        = 'moving'        # dragging center handle
    _DRAG_ENDPOINT = 'drag_endpoint' # dragging one of the two endpoint handles

    def __init__(self, image_view: pg.ImageView,
                 stats_label: QtWidgets.QLabel,
                 logger: Optional[logging.Logger] = None):
        self.image_view       = image_view
        self.stats_label      = stats_label
        self.logger           = logger
        self.scalebar_manager = None
        self._profile_dialog: Optional[LineProfileDialog] = None

        self._gv = image_view.ui.graphicsView

        self._item:      Optional[QtWidgets.QGraphicsLineItem] = None
        self._handle_c:  Optional[QtWidgets.QGraphicsRectItem] = None  # center
        self._handle_p1: Optional[QtWidgets.QGraphicsRectItem] = None  # start
        self._handle_p2: Optional[QtWidgets.QGraphicsRectItem] = None  # end

        self._x1 = self._y1 = self._x2 = self._y2 = 0.0

        self._state    = self._IDLE
        self._enabled  = False
        self._last_image: Optional[np.ndarray] = None
        # Effective viewer decimation. Set by pystream every frame; a
        # displayed pixel spans `display_bin` sensor pixels, so lengths
        # must scale by this factor.
        self.display_bin: int = 1

        self._drag_start_sp    = None
        self._drag_start_geom  = None   # (x1,y1,x2,y2) snapshot for move
        self._drag_endpoint_idx = None  # 1 or 2

        self._shift = False

        self._vp_filter  = _LineVpFilter(self)
        self._key_filter = _LineKeyFilter(self)
        self._gv.viewport().installEventFilter(self._vp_filter)
        app = QtWidgets.QApplication.instance()
        if app:
            app.installEventFilter(self._key_filter)

    # ── public API ────────────────────────────────────────────────────────

    def set_scalebar_manager(self, scalebar_manager):
        self.scalebar_manager = scalebar_manager

    def show_profile_dialog(self):
        """Open (or raise) the intensity-profile popup. Non-modal."""
        if self._profile_dialog is None:
            # Parent = None keeps it as a top-level window that can be
            # moved independently of the main viewer.
            self._profile_dialog = LineProfileDialog(parent=None)
        self._profile_dialog.show()
        self._profile_dialog.raise_()
        self._profile_dialog.activateWindow()
        # Push a fresh sample immediately so the plot isn't empty when
        # the user opens the dialog after already drawing a line.
        if self._state == self._PLACED:
            self._refresh_stats()

    def toggle(self, state):
        from PyQt5.QtCore import Qt
        if state == Qt.Checked:
            self._enabled = True
            self._state   = self._IDLE
            self._gv.viewport().setCursor(QtCore.Qt.CrossCursor)
            self.stats_label.setText("Line: click to set start point")
        else:
            self._enabled = False
            self._remove_graphics()
            self._state = self._IDLE
            self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
            self.stats_label.setText("No line")
            if self._profile_dialog is not None:
                self._profile_dialog.clear()

    def update_stats(self, image: np.ndarray):
        self._last_image = image
        if self._state == self._PLACED:
            self._refresh_stats()

    def reset(self):
        self._remove_graphics()
        if self._enabled:
            self._state = self._IDLE
            self._gv.viewport().setCursor(QtCore.Qt.CrossCursor)
            self.stats_label.setText("Line: click to set start point")
        if self._profile_dialog is not None:
            self._profile_dialog.clear()

    def cleanup(self):
        self._remove_graphics()
        try:
            self._gv.viewport().removeEventFilter(self._vp_filter)
        except Exception:
            pass
        try:
            app = QtWidgets.QApplication.instance()
            if app:
                app.removeEventFilter(self._key_filter)
        except Exception:
            pass
        if self._profile_dialog is not None:
            try:
                self._profile_dialog.close()
            except Exception:
                pass
            self._profile_dialog = None

    # ── helpers ───────────────────────────────────────────────────────────

    def _sc(self):
        return self._gv.scene()

    def _to_scene(self, vp_pos) -> QtCore.QPointF:
        return self._gv.mapToScene(vp_pos)

    def _pixel_sizes(self):
        if self.scalebar_manager is None:
            return 1.0, 1.0
        return (self.scalebar_manager.scale_bar_1.pixel_size,
                self.scalebar_manager.scale_bar_2.pixel_size)

    # ── graphics ──────────────────────────────────────────────────────────

    def _remove_graphics(self):
        sc = self._sc()
        for attr in ('_item', '_handle_c', '_handle_p1', '_handle_p2'):
            item = getattr(self, attr)
            if item is not None:
                if sc:
                    sc.removeItem(item)
                setattr(self, attr, None)

    def _make_handle(self) -> QtWidgets.QGraphicsRectItem:
        s = _HANDLE_SIZE_PX / 2.0
        h = QtWidgets.QGraphicsRectItem(-s, -s, 2*s, 2*s)
        h.setPen(_handle_pen())
        h.setBrush(_handle_brush())
        h.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        h.setZValue(1001)
        return h

    def _create_graphics(self):
        self._remove_graphics()
        sc = self._sc()
        if sc is None:
            return

        self._item = QtWidgets.QGraphicsLineItem(
            self._x1, self._y1, self._x2, self._y2)
        self._item.setPen(_line_pen())
        self._item.setZValue(1000)
        sc.addItem(self._item)

        self._handle_c  = self._make_handle()
        self._handle_p1 = self._make_handle()
        self._handle_p2 = self._make_handle()
        sc.addItem(self._handle_c)
        sc.addItem(self._handle_p1)
        sc.addItem(self._handle_p2)

        self._place_handles()

    def _place_handles(self):
        if self._handle_c is not None:
            self._handle_c.setPos((self._x1 + self._x2) / 2.0,
                                  (self._y1 + self._y2) / 2.0)
        if self._handle_p1 is not None:
            self._handle_p1.setPos(self._x1, self._y1)
        if self._handle_p2 is not None:
            self._handle_p2.setPos(self._x2, self._y2)

    def _apply_geom(self):
        if self._item is not None:
            self._item.setLine(self._x1, self._y1, self._x2, self._y2)
        self._place_handles()

    def _hit(self, handle, vp_pos) -> bool:
        if handle is None:
            return False
        h_vp = self._gv.mapFromScene(handle.pos())
        return (np.hypot(vp_pos.x() - h_vp.x(),
                         vp_pos.y() - h_vp.y()) <= _HANDLE_HIT_PX)

    # ── constraint ────────────────────────────────────────────────────────

    def _constrain(self, ax, ay, fx, fy):
        if not self._shift:
            return fx, fy
        if abs(fx - ax) >= abs(fy - ay):
            return fx, ay   # horizontal
        return ax, fy       # vertical

    # ── mouse events ──────────────────────────────────────────────────────

    def _on_press(self, vp_pos) -> bool:
        if not self._enabled:
            return False

        sp = self._to_scene(vp_pos)

        if self._state == self._IDLE:
            self._x1 = self._x2 = sp.x()
            self._y1 = self._y2 = sp.y()
            self._create_graphics()
            self._state = self._PLACING
            self.stats_label.setText("Line: drag to end, release to place")
            return True

        if self._state == self._PLACED:
            if self._hit(self._handle_p1, vp_pos):
                self._state = self._DRAG_ENDPOINT
                self._drag_endpoint_idx = 1
                self._gv.viewport().setCursor(QtCore.Qt.CrossCursor)
                return True
            if self._hit(self._handle_p2, vp_pos):
                self._state = self._DRAG_ENDPOINT
                self._drag_endpoint_idx = 2
                self._gv.viewport().setCursor(QtCore.Qt.CrossCursor)
                return True
            if self._hit(self._handle_c, vp_pos):
                self._state = self._MOVING
                self._drag_start_sp   = sp
                self._drag_start_geom = (self._x1, self._y1,
                                         self._x2, self._y2)
                self._gv.viewport().setCursor(QtCore.Qt.SizeAllCursor)
                return True

        return False

    def _on_move(self, vp_pos) -> bool:
        sp = self._to_scene(vp_pos)

        if self._state == self._PLACING:
            x, y = self._constrain(self._x1, self._y1, sp.x(), sp.y())
            self._x2, self._y2 = x, y
            self._apply_geom()
            self._refresh_stats()
            return True

        if self._state == self._DRAG_ENDPOINT:
            if self._drag_endpoint_idx == 1:
                x, y = self._constrain(self._x2, self._y2, sp.x(), sp.y())
                self._x1, self._y1 = x, y
            else:
                x, y = self._constrain(self._x1, self._y1, sp.x(), sp.y())
                self._x2, self._y2 = x, y
            self._apply_geom()
            self._refresh_stats()
            return True

        if self._state == self._MOVING:
            dx = sp.x() - self._drag_start_sp.x()
            dy = sp.y() - self._drag_start_sp.y()
            x1, y1, x2, y2 = self._drag_start_geom
            self._x1, self._y1 = x1 + dx, y1 + dy
            self._x2, self._y2 = x2 + dx, y2 + dy
            self._apply_geom()
            return True

        return False

    def _on_release(self, vp_pos) -> bool:
        if self._state == self._PLACING:
            sp = self._to_scene(vp_pos)
            x, y = self._constrain(self._x1, self._y1, sp.x(), sp.y())
            self._x2, self._y2 = x, y
            self._apply_geom()
            self._state = self._PLACED
            self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
            self._refresh_stats()
            return True
        if self._state in (self._MOVING, self._DRAG_ENDPOINT):
            self._state = self._PLACED
            self._drag_endpoint_idx = None
            self._refresh_stats()
            self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
            return True
        return False

    # ── stats ─────────────────────────────────────────────────────────────

    def _refresh_stats(self):
        img_item = self.image_view.getImageItem()
        if img_item is None:
            return

        p1 = img_item.mapFromScene(QtCore.QPointF(self._x1, self._y1))
        p2 = img_item.mapFromScene(QtCore.QPointF(self._x2, self._y2))
        ix1, iy1 = p1.x(), p1.y()
        ix2, iy2 = p2.x(), p2.y()

        # dx/dy are in *displayed* pixels — the image was decimated by
        # display_bin before it reached the viewer. Scale up so lengths
        # report in sensor pixels (and multiply pixel_size µm/sensor-px
        # by the same factor).
        b = max(1, int(self.display_bin))
        dx_px = (ix2 - ix1) * b
        dy_px = (iy2 - iy1) * b
        length_px = float(np.hypot(dx_px, dy_px))

        px_x, px_y = self._pixel_sizes()
        length_um  = float(np.hypot(dx_px * px_x, dy_px * px_y))
        length_mm  = length_um / 1000.0
        angle      = float(np.degrees(np.arctan2(dy_px, dx_px)))

        if self._state in (self._PLACING, self._DRAG_ENDPOINT):
            self.stats_label.setText(
                f"Line: {length_px:.0f} px  |  {length_um:.2f} µm")
            return

        self.stats_label.setText(
            f"Line\n"
            f"Length: {length_px:.1f} px\n"
            f"        {length_um:.2f} µm  ({length_mm:.4f} mm)\n"
            f"ΔX: {abs(dx_px):.1f} px = {abs(dx_px)*px_x:.2f} µm\n"
            f"ΔY: {abs(dy_px):.1f} px = {abs(dy_px)*px_y:.2f} µm\n"
            f"Angle: {angle:.1f}°\n"
            f"Start: ({ix1:.1f}, {iy1:.1f})\n"
            f"End:   ({ix2:.1f}, {iy2:.1f})")

        # Push a fresh intensity profile to the popup, if the user
        # opened it. Sampling is bilinear on the displayed frame.
        if self._profile_dialog is not None and self._profile_dialog.isVisible():
            self._update_profile(ix1, iy1, ix2, iy2, length_um)

    def _update_profile(self, ix1, iy1, ix2, iy2, length_um):
        img = self._last_image
        if img is None or img.ndim < 2:
            return
        H, W = img.shape[:2]
        # One sample per displayed pixel — ImageJ default. Bump min to
        # 2 so a zero-length line doesn't crash setData.
        n = max(2, int(np.ceil(float(np.hypot(ix2 - ix1, iy2 - iy1)))))
        xs = np.linspace(ix1, ix2, n)
        ys = np.linspace(iy1, iy2, n)
        # Reject samples that fall outside the image; keep in-bounds
        # ones (the endpoints can drift off during a drag).
        in_bounds = (xs >= 0) & (xs <= W - 1) & (ys >= 0) & (ys <= H - 1)
        if not np.any(in_bounds):
            self._profile_dialog.clear()
            return
        xs, ys = xs[in_bounds], ys[in_bounds]
        # Bilinear sample.
        x0 = np.floor(xs).astype(np.int64)
        y0 = np.floor(ys).astype(np.int64)
        x1 = np.clip(x0 + 1, 0, W - 1)
        y1 = np.clip(y0 + 1, 0, H - 1)
        fx = xs - x0
        fy = ys - y0
        f = img.astype(np.float32, copy=False)
        prof = (f[y0, x0] * (1 - fx) * (1 - fy) +
                f[y0, x1] * fx       * (1 - fy) +
                f[y1, x0] * (1 - fx) * fy       +
                f[y1, x1] * fx       * fy)
        distances_um = np.linspace(0.0, length_um, prof.size)
        self._profile_dialog.set_profile(distances_um, prof, length_um)


class _LineKeyFilter(QtCore.QObject):
    def __init__(self, mgr):
        super().__init__()
        self.mgr = mgr

    def eventFilter(self, _obj, event):
        t = event.type()
        if t == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Shift:
            self.mgr._shift = True
        elif t == QtCore.QEvent.KeyRelease and event.key() == QtCore.Qt.Key_Shift:
            self.mgr._shift = False
        return False


class _LineVpFilter(QtCore.QObject):
    def __init__(self, mgr: LineProfileManager):
        super().__init__()
        self.mgr = mgr

    def eventFilter(self, _obj, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton:
                return self.mgr._on_press(event.pos())
        elif t == QtCore.QEvent.MouseMove:
            return self.mgr._on_move(event.pos())
        elif t == QtCore.QEvent.MouseButtonRelease:
            if event.button() == QtCore.Qt.LeftButton:
                return self.mgr._on_release(event.pos())
        return False
