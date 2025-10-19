#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROI Plugin for PyQtGraph Viewer
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets


class ROIManager:
    """
    Axis-aligned rectangle ROI with thick yellow outline and large pullable handles.
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        stats_label: QtWidgets.QLabel,
        logger: Optional[logging.Logger] = None,
        *,
        handle_size_corner: int = 22,
        handle_size_edge: int = 18,
        roi_pen_width: int = 5,
    ):
        self.image_view = image_view
        self.stats_label = stats_label
        self.logger = logger

        self.handle_size_corner = max(8, int(handle_size_corner))
        self.handle_size_edge = max(8, int(handle_size_edge))
        self.roi_pen_width = max(1, int(roi_pen_width))

        self.roi: Optional[pg.ROI] = None
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None

    # ---------- Public API ----------

    def toggle(self, state):
        from PyQt5.QtCore import Qt
        self.enabled = (state == Qt.Checked)

        if self.enabled:
            if self.roi is None:
                if self._last_image is not None:
                    self._create_roi_from_image(self._last_image)
                else:
                    self._create_roi_default()
            self.roi.setVisible(True)
            self.roi.show()
            self._update_stats()
            self.stats_label.setText("ROI enabled\n(drag corners/edges; drag inside to move)")
        else:
            if self.roi is not None:
                self.roi.setVisible(False)
            self.stats_label.setText("No ROI selected")

    def reset(self):
        """Reset ROI to image center with default size."""
        if self._last_image is None:
            QtWidgets.QMessageBox.information(None, "Reset ROI", "No image available.")
            return

        if self.roi is None:
            self._create_roi_from_image(self._last_image)
            self.enabled = True

        h, w = self._last_image.shape[:2]
        rw = max(2, w // 4)
        rh = max(2, h // 4)
        rx = (w - rw) // 2
        ry = (h - rh) // 2

        self.roi.setPos([rx, ry])
        self.roi.setSize([rw, rh])
        self.roi.setZValue(1000)
        self.roi.setVisible(True)
        self.roi.show()
        self._update_stats()

        if self.logger:
            self.logger.info("ROI reset to (%d, %d) size (%d, %d)", rx, ry, rw, rh)

    def update_stats(self, image: np.ndarray):
        """Provide the current image (2D numpy array)."""
        self._last_image = image
        if self.enabled and self.roi is None:
            self._create_roi_from_image(image)
        if self.enabled and self.roi is not None:
            self._update_stats()

    def get_roi_data(self, image: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """Return a cutout of the ROI from the provided or last image."""
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
                self.logger.warning("Failed to extract ROI data: %s", e)
            return None

    def get_roi_bounds(self) -> Optional[dict]:
        """Return dict(x,y,width,height) in image pixel coordinates."""
        if self.roi is None:
            return None
        pos = self.roi.pos()
        size = self.roi.size()
        return {"x": pos[0], "y": pos[1], "width": size[0], "height": size[1]}

    def set_roi_bounds(self, x: float, y: float, width: float, height: float):
        """Programmatically set ROI bounds."""
        if self.roi is None:
            if self._last_image is not None:
                self._create_roi_from_image(self._last_image)
            else:
                self._create_roi_default()
        self.roi.setPos([x, y])
        self.roi.setSize([width, height])
        self.roi.setZValue(1000)
        self.roi.setVisible(True)
        self.roi.show()
        self._update_stats()
        if self.logger:
            self.logger.info("ROI set to (%.1f, %.1f) size (%.1f, %.1f)", x, y, width, height)

    def cleanup(self):
        """Remove ROI from the view."""
        if self.roi is not None:
            try:
                self.roi.setParentItem(None)
                self.image_view.getView().removeItem(self.roi)
            except Exception:
                pass
            self.roi = None
        self.enabled = False
        self._last_image = None

    # ---------- Internals ----------

    def _create_roi_from_image(self, image: np.ndarray):
        h, w = image.shape[:2]
        rw = max(2, w // 4)
        rh = max(2, h // 4)
        rx = (w - rw) // 2
        ry = (h - rh) // 2
        self._build_roi(rx, ry, rw, rh)

    def _create_roi_default(self):
        self._build_roi(50, 50, 100, 100)

    def _build_roi(self, x, y, w, h):
        """
        Create RectROI attached to the ImageItem with:
        """
        img_item = self.image_view.getImageItem()
        pen = pg.mkPen('y', width=self.roi_pen_width)
        hover_pen = pg.mkPen((255, 255, 0, 220), width=self.roi_pen_width + 2)

        self.roi = pg.RectROI([x, y], [w, h],
                              pen=pen, hoverPen=hover_pen,
                              movable=True, resizable=True, removable=False)
        self.roi.setZValue(1000)

        # Parent to ImageItem (pixel-space alignment)
        if img_item is not None:
            self.roi.setParentItem(img_item)
        else:
            self.image_view.getView().addItem(self.roi)

        # Add 8 large handles (corners + edges)
        cs = self.handle_size_corner
        es = self.handle_size_edge
        # Corners
        self.roi.addScaleHandle([1, 1], [0, 0], size=cs)  # BR
        self.roi.addScaleHandle([0, 0], [1, 1], size=cs)  # TL
        self.roi.addScaleHandle([1, 0], [0, 1], size=cs)  # TR
        self.roi.addScaleHandle([0, 1], [1, 0], size=cs)  # BL
        # Edges
        self.roi.addScaleHandle([0.5, 0], [0.5, 1], size=es)  # Top
        self.roi.addScaleHandle([0.5, 1], [0.5, 0], size=es)  # Bottom
        self.roi.addScaleHandle([0, 0.5], [1, 0.5], size=es)  # Left
        self.roi.addScaleHandle([1, 0.5], [0, 0.5], size=es)  # Right

        # Style handles for visibility (fallbacks for older versions)
        self._style_handles()

        # Update stats on move/resize
        self.roi.sigRegionChanged.connect(self._update_stats)

        self.roi.setVisible(True)
        self.roi.show()

        # Keep in view (harmless if not needed)
        try:
            self.image_view.getView().autoRange()
        except Exception:
            pass

        if self.logger:
            self.logger.info("RectROI created at (%d, %d) size (%d, %d)", x, y, w, h)

    def _style_handles(self):
        brush = pg.mkBrush(255, 255, 0, 255)   # yellow
        pen = pg.mkPen(0, 0, 0, 255, width=1)  # black

        for h in self.roi.getHandles():
            item = h.get('item', None)
            if item is None:
                continue
            # Size is already set by addScaleHandle(size=...), but some builds expose setSize:
            if hasattr(item, "setSize"):
                try:
                    # keep requested size; no change
                    pass
                except Exception:
                    pass
            # Apply colors
            try:
                if hasattr(item, "setBrush"):
                    item.setBrush(brush)
                else:
                    item.brush = brush
            except Exception:
                pass
            try:
                if hasattr(item, "setPen"):
                    item.setPen(pen)
                else:
                    item.pen = pen
            except Exception:
                pass

    # ---------- Stats ----------

    def _update_stats(self):
        if not self.enabled or self.roi is None or self._last_image is None:
            return
        try:
            roi_slice, _ = self.roi.getArraySlice(self._last_image, self.image_view.getImageItem())
            roi_data = self._last_image[roi_slice[0], roi_slice[1]]
            if roi_data.size == 0:
                self.stats_label.setText("ROI outside image bounds")
                return

            pos = self.roi.pos()
            size = self.roi.size()

            roi_min = float(np.min(roi_data))
            roi_max = float(np.max(roi_data))
            roi_mean = float(np.mean(roi_data))
            roi_std = float(np.std(roi_data))
            roi_sum = float(np.sum(roi_data))

            self.stats_label.setText(
                f"Position:\n  X: {pos[0]:.1f}\n  Y: {pos[1]:.1f}\n\n"
                f"Size:\n  W: {size[0]:.1f}\n  H: {size[1]:.1f}\n  Pixels: {roi_data.size}\n\n"
                f"Stats:\n  Min: {roi_min:.2f}\n  Max: {roi_max:.2f}\n"
                f"  Mean: {roi_mean:.2f}\n  Std: {roi_std:.2f}\n  Sum: {roi_sum:.2f}"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update ROI stats: %s", e)
            self.stats_label.setText("Error calculating ROI stats")
