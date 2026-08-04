#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROI Plugin - mirrors the line plugin pattern exactly.

All graphics items live in the ViewBox (image-item local coords —
i.e. image pixels). That means the ROI pans and zooms WITH the image
and stays pinned to the feature it was drawn across. Mouse events are
in viewport pixels; they're converted to image coords once, on entry,
via `_to_image`.

Interaction:
  - Toggle ON      → crosshair cursor, wait for draw.
  - Press & drag   → live rectangle preview.
  - Release        → ROI finalised; PyQtGraph handles active for reshape/move.
  - Toggle OFF     → ROI erased.
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class ROIManager:

    _IDLE    = 'idle'
    _PLACING = 'placing'
    _PLACED  = 'placed'

    def __init__(
        self,
        image_view: pg.ImageView,
        stats_label: QtWidgets.QLabel,
        logger: Optional[logging.Logger] = None,
        *,
        handle_size: int = 10,
        roi_pen_width: int = 2,
        show_dimensions: bool = True,
    ):
        self.image_view   = image_view
        self.stats_label  = stats_label
        self.logger       = logger

        self.handle_size     = max(6, int(handle_size))
        self.roi_pen_width   = max(1, int(roi_pen_width))
        self.show_dimensions = show_dimensions

        self.roi: Optional[pg.ROI] = None
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None
        self.dimension_text: Optional[pg.TextItem] = None

        # Belt-and-suspenders: keep a strong reference to every ROI /
        # dimension-text this manager has ever created. `_remove_roi`
        # sweeps this list, not just `self.roi`, so an orphan left
        # behind by a failed `view.removeItem` (which we swallow silently
        # via the try/except pattern) gets cleaned up on the next call.
        # Without this, the symptom is: multiple ROIs on screen that
        # toggle-off / reset can't clear because the reference was nulled.
        self._all_rois: list = []
        self._all_texts: list = []

        self._state       = self._IDLE
        self._press_image = None                              # QPointF (image coords)
        self._preview: Optional[QtWidgets.QGraphicsRectItem] = None

        self._gv = image_view.ui.graphicsView
        self._vp_filter = _RoiVpFilter(self)
        self._gv.viewport().installEventFilter(self._vp_filter)

    # ── helpers ───────────────────────────────────────────────────────────

    def _view(self):
        """The ViewBox — anything we add here lives in ImageItem-local
        coords (image pixels) and rides the ImageItem's transform."""
        return self.image_view.getView()

    def _img_item(self):
        return self.image_view.getImageItem()

    def _to_image(self, vp_pos) -> Optional[QtCore.QPointF]:
        """Viewport pixel → image-item local (image pixel) coords."""
        img_item = self._img_item()
        if img_item is None:
            return None
        return img_item.mapFromScene(self._gv.mapToScene(vp_pos))

    # ── public API ────────────────────────────────────────────────────────

    def toggle(self, state):
        from PyQt5.QtCore import Qt
        self.enabled = (state == Qt.Checked)
        if self.enabled:
            self._state = self._IDLE
            self._gv.viewport().setCursor(QtCore.Qt.CrossCursor)
            self.stats_label.setText("ROI: click and drag to draw")
        else:
            self._remove_all()
            self._state = self._IDLE
            self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
            self.stats_label.setText("No ROI selected")

    def reset(self):
        if self._last_image is None:
            QtWidgets.QMessageBox.information(None, "Reset ROI", "No image available.")
            return
        h, w = self._last_image.shape[:2]
        rw = max(2, w // 4)
        rh = max(2, h // 4)
        rx = (w - rw) // 2
        ry = (h - rh) // 2
        # Coords already in image-pixel space — no scene conversion needed
        # now that the ROI lives in ViewBox (= ImageItem local) coords.
        self._remove_all()
        self._build_roi(rx, ry, rw, rh)
        self.enabled = True
        self._state  = self._PLACED
        self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
        self._update_stats()

    def update_stats(self, image: np.ndarray):
        self._last_image = image
        if self.enabled and self._state == self._PLACED and self.roi is not None:
            self._update_stats()

    def get_roi_data(self, image: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        if not self.enabled or self.roi is None:
            return None
        img = image if image is not None else self._last_image
        if img is None:
            return None
        try:
            roi_slice, _ = self.roi.getArraySlice(img, self.image_view.getImageItem())
            return img[roi_slice[0], roi_slice[1]]
        except Exception as e:
            if self.logger:
                self.logger.warning("ROI data extract: %s", e)
            return None

    def get_roi_bounds(self) -> Optional[dict]:
        if self.roi is None:
            return None
        pos  = self.roi.pos()
        size = self.roi.size()
        return {"x": pos[0], "y": pos[1], "width": size[0], "height": size[1]}

    def set_roi_bounds(self, x, y, width, height):
        # x/y/width/height are image-pixel values; the ROI already lives
        # in that same frame, so no coord conversion is required.
        self._remove_all()
        self._build_roi(x, y, width, height)
        self.enabled = True
        self._state  = self._PLACED
        self._update_stats()

    def cleanup(self):
        self._remove_all()
        try:
            self._gv.viewport().removeEventFilter(self._vp_filter)
        except Exception:
            pass
        self.enabled     = False
        self._last_image = None

    # ── mouse events ─────────────────────────────────────────────────────

    def _on_press(self, vp_pos) -> bool:
        if not self.enabled or self._state != self._IDLE:
            return False
        ip = self._to_image(vp_pos)
        img_item = self._img_item()
        if ip is None or img_item is None:
            return False
        self._press_image = ip
        pen = pg.mkPen('y', width=2)
        pen.setCosmetic(True)
        # Preview lives in image-item local coords too so it tracks the
        # image while the user is dragging (in case a zoom/pan happens
        # via another input).
        self._preview = QtWidgets.QGraphicsRectItem(ip.x(), ip.y(), 0, 0)
        self._preview.setPen(pen)
        self._preview.setZValue(1000)
        self._preview.setParentItem(img_item)
        self._state = self._PLACING
        return True

    def _on_move(self, vp_pos) -> bool:
        if self._state != self._PLACING or self._preview is None:
            return False
        ip = self._to_image(vp_pos)
        if ip is None:
            return False
        x  = min(self._press_image.x(), ip.x())
        y  = min(self._press_image.y(), ip.y())
        w  = max(1.0, abs(ip.x() - self._press_image.x()))
        h  = max(1.0, abs(ip.y() - self._press_image.y()))
        self._preview.setRect(x, y, w, h)
        return True

    def _on_release(self, vp_pos) -> bool:
        if self._state != self._PLACING:
            return False
        ip = self._to_image(vp_pos)
        if ip is None:
            return False

        # remove preview
        if self._preview is not None:
            try:
                self._preview.setParentItem(None)
            except Exception:
                pass
            sc = self._gv.scene()
            if sc is not None:
                try:
                    sc.removeItem(self._preview)
                except Exception:
                    pass
        self._preview = None

        # Bounding box in image-item local coords (image pixels).
        x = min(self._press_image.x(), ip.x())
        y = min(self._press_image.y(), ip.y())
        w = max(1.0, abs(ip.x() - self._press_image.x()))
        h = max(1.0, abs(ip.y() - self._press_image.y()))

        self._remove_roi()
        self._build_roi(x, y, w, h)
        self._state = self._PLACED
        self._gv.viewport().setCursor(QtCore.Qt.ArrowCursor)
        self._update_stats()
        return True

    # ── graphics ─────────────────────────────────────────────────────────

    def _remove_roi(self):
        view = self._view()
        # Disconnect signals on the currently-tracked ROI first (only
        # this one had a connection).
        if self.roi is not None:
            try:
                self.roi.sigRegionChanged.disconnect(self._on_roi_changed)
            except Exception:
                pass
        # Sweep EVERY ROI this manager ever created — including orphans
        # from prior failed removals — plus the current one.
        seen = set()
        for r in self._all_rois:
            if r is None or id(r) in seen:
                continue
            seen.add(id(r))
            if view is not None:
                try:
                    view.removeItem(r)
                except Exception:
                    pass
        self._all_rois = []
        self.roi = None
        # Same sweep for dimension_text items.
        seen = set()
        for t in self._all_texts:
            if t is None or id(t) in seen:
                continue
            seen.add(id(t))
            if view is not None:
                try:
                    view.removeItem(t)
                except Exception:
                    pass
        self._all_texts = []
        self.dimension_text = None

    def _remove_all(self):
        if self._preview is not None:
            try:
                self._preview.setParentItem(None)
            except Exception:
                pass
            sc = self._gv.scene()
            if sc is not None:
                try:
                    sc.removeItem(self._preview)
                except Exception:
                    pass
            self._preview = None
        self._remove_roi()

    def _build_roi(self, x, y, w, h):
        """Create pg.RectROI in image-item local coords (image pixels).
        The ROI is added to the ViewBox so its pos/size are naturally
        in image-pixel units and it inherits the ImageItem's transform,
        staying pinned to the underlying feature on zoom/pan."""
        view = self._view()
        if view is None:
            return
        self._remove_roi()  # always clean up any existing ROI first

        pen       = pg.mkPen('y', width=self.roi_pen_width)
        hover_pen = pg.mkPen((255, 255, 100), width=self.roi_pen_width + 1)

        self.roi = pg.RectROI(
            [x, y], [w, h],
            pen=pen, hoverPen=hover_pen,
            movable=True, resizable=True, removable=False,
        )
        self.roi.setZValue(1000)
        view.addItem(self.roi)  # ViewBox local coords = image pixels
        self._all_rois.append(self.roi)

        # 4 corners + 4 edges
        self.roi.addScaleHandle([1, 1], [0, 0])
        self.roi.addScaleHandle([0, 0], [1, 1])
        self.roi.addScaleHandle([1, 0], [0, 1])
        self.roi.addScaleHandle([0, 1], [1, 0])
        self.roi.addScaleHandle([0.5, 0],   [0.5, 1])
        self.roi.addScaleHandle([0.5, 1],   [0.5, 0])
        self.roi.addScaleHandle([0,   0.5], [1,   0.5])
        self.roi.addScaleHandle([1,   0.5], [0,   0.5])

        self._style_handles()

        if self.show_dimensions:
            self.dimension_text = pg.TextItem(
                anchor=(0.5, 1.1), color='y',
                fill=(0, 0, 0, 180), border='y',
            )
            self.dimension_text.setZValue(2000)
            view.addItem(self.dimension_text)
            self._all_texts.append(self.dimension_text)

        self.roi.sigRegionChanged.connect(self._on_roi_changed)
        self.roi.setVisible(True)
        self._update_dimension_display()

        if self.logger:
            self.logger.info("ROI at (%.1f,%.1f) size (%.1f,%.1f)", x, y, w, h)

    def _style_handles(self):
        if self.roi is None:
            return
        brush = pg.mkBrush(255, 0, 0, 255)
        pen   = pg.mkPen('w', width=3)
        size  = float(self.handle_size * 2)
        for ho in self.roi.getHandles():
            hi = ho.item if hasattr(ho, 'item') else ho
            if hi is None:
                continue
            try:
                if hasattr(hi, 'setSize'):
                    hi.setSize(size)
                elif hasattr(hi, 'setScale'):
                    hi.setScale(size / 10.0)
                if hasattr(hi, 'setBrush'):
                    hi.setBrush(brush)
                if hasattr(hi, 'setPen'):
                    hi.setPen(pen)
                hi.setZValue(self.roi.zValue() + 1)
            except Exception as e:
                if self.logger:
                    self.logger.debug("Handle style: %s", e)

    def _on_roi_changed(self):
        if self._state == self._PLACED:
            self._update_stats()
        self._update_dimension_display()

    def _update_dimension_display(self):
        if not self.show_dimensions or self.dimension_text is None or self.roi is None:
            return
        try:
            pos  = self.roi.pos()
            size = self.roi.size()
            self.dimension_text.setPos(pos[0] + size[0] / 2, pos[1])
            self.dimension_text.setText(f"{int(size[0])} x {int(size[1])}")
            self.dimension_text.setVisible(self.enabled)
        except Exception as e:
            if self.logger:
                self.logger.warning("Dimension display: %s", e)

    # ── stats ─────────────────────────────────────────────────────────────

    def _update_stats(self):
        if not self.enabled or self.roi is None or self._last_image is None:
            return
        try:
            roi_slice, _ = self.roi.getArraySlice(
                self._last_image, self.image_view.getImageItem())
            roi_data = self._last_image[roi_slice[0], roi_slice[1]]
            if roi_data.size == 0:
                self.stats_label.setText("ROI outside image bounds")
                return
            pos  = self.roi.pos()
            size = self.roi.size()
            self.stats_label.setText(
                f"Position:\n  X: {pos[0]:.1f}\n  Y: {pos[1]:.1f}\n\n"
                f"Size:\n  W: {size[0]:.1f}\n  H: {size[1]:.1f}\n"
                f"  Pixels: {roi_data.size}\n\n"
                f"Stats:\n  Min: {float(np.min(roi_data)):.2f}\n"
                f"  Max: {float(np.max(roi_data)):.2f}\n"
                f"  Mean: {float(np.mean(roi_data)):.2f}\n"
                f"  Std: {float(np.std(roi_data)):.2f}\n"
                f"  Sum: {float(np.sum(roi_data)):.2f}"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning("ROI stats: %s", e)
            self.stats_label.setText("Error calculating ROI stats")


class _RoiVpFilter(QtCore.QObject):
    def __init__(self, mgr: ROIManager):
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
