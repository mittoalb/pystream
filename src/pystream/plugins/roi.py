#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROI Plugin for PyQtGraph Viewer - ImageJ Style (Simplified & Robust)
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui


class ROIManager:
    """
    ImageJ-style rectangle ROI with prominent handles and dimension display.
    Simplified version guaranteed to work with all PyQtGraph versions.
    """

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
        self.image_view = image_view
        self.stats_label = stats_label
        self.logger = logger

        self.handle_size = max(6, int(handle_size))
        self.roi_pen_width = max(1, int(roi_pen_width))
        self.show_dimensions = show_dimensions

        self.roi: Optional[pg.ROI] = None
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None
        
        # Dimension text item
        self.dimension_text: Optional[pg.TextItem] = None

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
            if self.roi is not None:
                self.roi.setVisible(True)
                self.roi.show()
            if self.dimension_text:
                self.dimension_text.setVisible(True)
            self._update_stats()
            self.stats_label.setText("ROI enabled\n(drag corners/edges to resize;\ndrag center to move)")
        else:
            if self.roi is not None:
                self.roi.setVisible(False)
            if self.dimension_text:
                self.dimension_text.setVisible(False)
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
        
        if self.dimension_text is not None:
            try:
                self.image_view.getView().removeItem(self.dimension_text)
            except Exception:
                pass
            self.dimension_text = None
            
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
        Create ImageJ-style RectROI with prominent handles.
        """
        img_item = self.image_view.getImageItem()
        
        # Yellow outline like ImageJ (2px for clean appearance)
        pen = pg.mkPen('y', width=self.roi_pen_width)
        hover_pen = pg.mkPen((255, 255, 100), width=self.roi_pen_width + 1)

        # Create ROI
        self.roi = pg.RectROI(
            [x, y], [w, h],
            pen=pen, 
            hoverPen=hover_pen,
            movable=True, 
            resizable=True, 
            removable=False
        )
        
        self.roi.setZValue(1000)

        # Parent to ImageItem for pixel-space alignment
        if img_item is not None:
            self.roi.setParentItem(img_item)
        else:
            self.image_view.getView().addItem(self.roi)

        # Add 8 handles (4 corners + 4 edges) - this is what makes it ImageJ-like
        # All handles same size for consistency
        hs = self.handle_size
        
        # CORNERS (for diagonal resizing)
        self.roi.addScaleHandle([1, 1], [0, 0])  # Bottom-Right
        self.roi.addScaleHandle([0, 0], [1, 1])  # Top-Left
        self.roi.addScaleHandle([1, 0], [0, 1])  # Top-Right
        self.roi.addScaleHandle([0, 1], [1, 0])  # Bottom-Left
        
        # EDGES (for single-axis resizing)
        self.roi.addScaleHandle([0.5, 0], [0.5, 1])  # Top-Center
        self.roi.addScaleHandle([0.5, 1], [0.5, 0])  # Bottom-Center
        self.roi.addScaleHandle([0, 0.5], [1, 0.5])  # Left-Center
        self.roi.addScaleHandle([1, 0.5], [0, 0.5])  # Right-Center

        # Style the handles to be more visible
        self._style_handles()

        # Create dimension text display
        if self.show_dimensions:
            self.dimension_text = pg.TextItem(
                anchor=(0.5, 1.1),
                color='y',
                fill=(0, 0, 0, 180),
                border='y'
            )
            self.dimension_text.setZValue(2000)
            
            if img_item is not None:
                self.dimension_text.setParentItem(img_item)
            else:
                self.image_view.getView().addItem(self.dimension_text)

        # Connect signals
        self.roi.sigRegionChanged.connect(self._on_roi_changed)

        # Make visible
        self.roi.setVisible(True)
        self.roi.show()
        
        # Force view to update
        try:
            self.image_view.getView().update()
        except Exception:
            pass
        
        # Update initial display
        self._update_dimension_display()

        if self.logger:
            self.logger.info("ImageJ-style ROI created at (%d, %d) size (%d, %d)", x, y, w, h)

    def _style_handles(self):
        if self.roi is None:
            return

        # BRIGHT RED handles with white border for maximum visibility
        handle_brush = pg.mkBrush(255, 0, 0, 255)    # Bright red
        handle_pen = pg.mkPen('w', width=3)          # White border, thick
        size = float(self.handle_size * 2)

        for handle_obj in self.roi.getHandles():
            # Handle objects ARE the item in newer pyqtgraph
            if hasattr(handle_obj, 'item'):
                handle_item = handle_obj.item
            else:
                # Fallback - handle_obj IS the item itself
                handle_item = handle_obj
                
            if handle_item is None:
                continue

            try:
                # Actually change the size
                if hasattr(handle_item, 'setSize'):
                    handle_item.setSize(size)
                elif hasattr(handle_item, 'setScale'):
                    handle_item.setScale(size / 10.0)

                if hasattr(handle_item, 'setBrush'):
                    handle_item.setBrush(handle_brush)
                if hasattr(handle_item, 'setPen'):
                    handle_item.setPen(handle_pen)

                handle_item.setZValue(self.roi.zValue() + 1)
            except Exception as e:
                if self.logger:
                    self.logger.debug("Handle styling issue: %s", e)

    def _on_roi_changed(self):
        """Called when ROI is moved or resized."""
        self._update_stats()
        self._update_dimension_display()

    def _update_dimension_display(self):
        """Update the dimension text overlay."""
        if not self.show_dimensions or self.dimension_text is None or self.roi is None:
            return
        
        try:
            pos = self.roi.pos()
            size = self.roi.size()
            
            # Position text above the ROI
            text_x = pos[0] + size[0] / 2
            text_y = pos[1]
            
            self.dimension_text.setPos(text_x, text_y)
            self.dimension_text.setText(f"{int(size[0])} × {int(size[1])}")
            self.dimension_text.setVisible(self.enabled)
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update dimension display: %s", e)

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