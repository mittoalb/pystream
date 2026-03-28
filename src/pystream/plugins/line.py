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

        self._gv = image_view.ui.graphicsView

        self._item:      Optional[QtWidgets.QGraphicsLineItem] = None
        self._handle_c:  Optional[QtWidgets.QGraphicsRectItem] = None  # center
        self._handle_p1: Optional[QtWidgets.QGraphicsRectItem] = None  # start
        self._handle_p2: Optional[QtWidgets.QGraphicsRectItem] = None  # end

        self._x1 = self._y1 = self._x2 = self._y2 = 0.0

        self._state    = self._IDLE
        self._enabled  = False
        self._last_image: Optional[np.ndarray] = None

        self._drag_start_sp    = None
        self._drag_start_geom  = None   # (x1,y1,x2,y2) snapshot for move
        self._drag_endpoint_idx = None  # 1 or 2

        self._vp_filter = _LineVpFilter(self)
        self._gv.viewport().installEventFilter(self._vp_filter)

    # ── public API ────────────────────────────────────────────────────────

    def set_scalebar_manager(self, scalebar_manager):
        self.scalebar_manager = scalebar_manager

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

    def cleanup(self):
        self._remove_graphics()
        try:
            self._gv.viewport().removeEventFilter(self._vp_filter)
        except Exception:
            pass

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
            self.stats_label.setText("Line: click to set end point")
            return True

        if self._state == self._PLACING:
            self._x2, self._y2 = sp.x(), sp.y()
            self._apply_geom()
            self._state = self._PLACED
            self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
            self._refresh_stats()
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
            self._x2, self._y2 = sp.x(), sp.y()
            self._apply_geom()
            self._refresh_stats()
            return True

        if self._state == self._DRAG_ENDPOINT:
            if self._drag_endpoint_idx == 1:
                self._x1, self._y1 = sp.x(), sp.y()
            else:
                self._x2, self._y2 = sp.x(), sp.y()
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

    def _on_release(self, _vp_pos) -> bool:
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

        dx_px    = ix2 - ix1
        dy_px    = iy2 - iy1
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
