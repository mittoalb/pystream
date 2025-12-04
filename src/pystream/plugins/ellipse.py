#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ellipse ROI Plugin for PyQtGraph Viewer
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets


class EllipseROIManager:
    """
    ImageJ-style ellipse/circle ROI with:
    - 8 prominent RED handles (4 corners + 4 edges) - HIGHLY VISIBLE!
    - Smooth dragging and resizing from any handle
    - Real-time dimension display
    - Black outline (professional appearance)
    - Accurate ellipse masking (only pixels inside ellipse)
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        stats_label: QtWidgets.QLabel,
        logger: Optional[logging.Logger] = None,
        *,
        handle_size: int = 12,  # Larger default for visibility
        roi_pen_width: int = 3,  # Thicker outline
        show_dimensions: bool = True,
    ):
        self.image_view = image_view
        self.stats_label = stats_label
        self.logger = logger

        self.handle_size = max(6, int(handle_size))
        self.roi_pen_width = max(1, int(roi_pen_width))
        self.show_dimensions = show_dimensions

        self.roi: Optional[pg.EllipseROI] = None
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
            self.stats_label.setText("Ellipse ROI enabled\n(drag corners/edges to resize;\ndrag center to move;\n8 handles for full control)")
        else:
            if self.roi is not None:
                self.roi.setVisible(False)
            if self.dimension_text:
                self.dimension_text.setVisible(False)
            self.stats_label.setText("No ellipse ROI selected")

    def reset(self):
        """Reset ROI to image center with default size."""
        if self._last_image is None:
            QtWidgets.QMessageBox.information(None, "Reset Ellipse ROI", "No image available.")
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
            self.logger.info("Ellipse ROI reset to (%d, %d) size (%d, %d)", rx, ry, rw, rh)

    def update_stats(self, image: np.ndarray):
        """Provide the current image (2D numpy array)."""
        self._last_image = image
        if self.enabled and self.roi is None:
            self._create_roi_from_image(image)
        if self.enabled and self.roi is not None:
            self._update_stats()

    def get_roi_data(self, image: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """Return pixels within the ellipse from the provided or last image."""
        if not self.enabled or self.roi is None:
            return None
        img = image if image is not None else self._last_image
        if img is None:
            return None
        try:
            # Get the array region (bounding box)
            roi_slice, _ = self.roi.getArraySlice(img, self.image_view.getImageItem())
            roi_data = img[roi_slice[0], roi_slice[1]]
            
            # Create ellipse mask
            pos = self.roi.pos()
            size = self.roi.size()
            
            # Get coordinates relative to bounding box
            h, w = roi_data.shape[:2]
            y_coords, x_coords = np.ogrid[0:h, 0:w]
            
            # Center of ellipse in bounding box coordinates
            center_x = w / 2
            center_y = h / 2
            
            # Semi-axes
            a = size[0] / 2  # semi-major axis (x)
            b = size[1] / 2  # semi-minor axis (y)
            
            # Ellipse equation: (x/a)^2 + (y/b)^2 <= 1
            mask = ((x_coords - center_x) / a) ** 2 + ((y_coords - center_y) / b) ** 2 <= 1
            
            # Return only pixels inside ellipse
            return roi_data[mask]
            
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to extract ellipse ROI data: %s", e)
            return None

    def get_roi_bounds(self) -> Optional[dict]:
        """Return dict(x,y,width,height) of bounding box in image pixel coordinates."""
        if self.roi is None:
            return None
        pos = self.roi.pos()
        size = self.roi.size()
        return {"x": pos[0], "y": pos[1], "width": size[0], "height": size[1]}

    def set_roi_bounds(self, x: float, y: float, width: float, height: float):
        """Programmatically set ellipse ROI bounds."""
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
            self.logger.info("Ellipse ROI set to (%.1f, %.1f) size (%.1f, %.1f)", x, y, width, height)

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
        Create ellipse ROI with 8 handles for full control.
        - 4 axis handles (0°, 90°, 180°, 270°): stretch individual axes
        - 4 diagonal handles (45°, 135°, 225°, 315°): scale radius uniformly
        """
        img_item = self.image_view.getImageItem()

        # Outline pens - YELLOW
        pen = pg.mkPen((255, 255, 0), width=self.roi_pen_width + 1)  # Yellow outline, thicker
        hover_pen = pg.mkPen((255, 200, 0), width=self.roi_pen_width + 2)  # Orange on hover, even thicker

        # HANDLE pens - YELLOW filled squares
        handle_pen = pg.mkPen(255, 255, 0, width=2)          # bright YELLOW outline
        handle_hover_pen = pg.mkPen(255, 200, 0, width=3)    # orange on hover

        # Create EllipseROI with explicit handlePen / handleHoverPen
        self.roi = pg.EllipseROI(
            [x, y], [w, h],
            pen=pen,
            hoverPen=hover_pen,
            movable=True,
            resizable=True,
            removable=False,
            handlePen=handle_pen,
            handleHoverPen=handle_hover_pen,
        )

        # For older pyqtgraph versions, also set attributes directly
        self.roi.handlePen = handle_pen
        self.roi.handleHoverPen = handle_hover_pen

        self.roi.setZValue(1000)

        if img_item is not None:
            self.roi.setParentItem(img_item)
        else:
            self.image_view.getView().addItem(self.roi)

        # Remove default handles
        for handle in self.roi.getHandles():
            self.roi.removeHandle(handle)

        # AXIS HANDLES (0°, 90°, 180°, 270°) - stretch along one axis only
        # These keep the opposite axis fixed and only stretch in one direction
        self.roi.addScaleHandle([0.5, 0], [0.5, 1])  # Top (270°) - stretch vertical
        self.roi.addScaleHandle([1, 0.5], [0, 0.5])  # Right (0°) - stretch horizontal
        self.roi.addScaleHandle([0.5, 1], [0.5, 0])  # Bottom (90°) - stretch vertical
        self.roi.addScaleHandle([0, 0.5], [1, 0.5])  # Left (180°) - stretch horizontal

        # DIAGONAL HANDLES (45°, 135°, 225°, 315°) - scale uniformly (radius)
        # These lie on the ellipse circumference at diagonal positions
        # Position on ellipse: [0.5 + 0.5*cos(θ), 0.5 + 0.5*sin(θ)]
        # cos(45°) = sin(45°) = 0.707
        d = 0.5 + 0.5 * 0.707  # ≈ 0.8535
        d_inv = 0.5 - 0.5 * 0.707  # ≈ 0.1465
        
        self.roi.addScaleHandle([d, d], [0.5, 0.5])      # Bottom-Right (45°) on circumference
        self.roi.addScaleHandle([d, d_inv], [0.5, 0.5])  # Top-Right (315°) on circumference
        self.roi.addScaleHandle([d_inv, d_inv], [0.5, 0.5])  # Top-Left (225°) on circumference
        self.roi.addScaleHandle([d_inv, d], [0.5, 0.5])  # Bottom-Left (135°) on circumference

        # Enlarge them
        self._style_handles()

        # Dimension text...
        if self.show_dimensions:
            self.dimension_text = pg.TextItem(
                anchor=(0.5, 1.1),
                color='k',
                fill=(255, 255, 255, 220),
                border='k',
            )
            self.dimension_text.setZValue(2000)
            if img_item is not None:
                self.dimension_text.setParentItem(img_item)
            else:
                self.image_view.getView().addItem(self.dimension_text)

        self.roi.sigRegionChanged.connect(self._on_roi_changed)

        self.roi.setVisible(True)
        self.roi.show()

        try:
            self.image_view.getView().update()
        except Exception:
            pass

        self._update_dimension_display()

        if self.logger:
            self.logger.info("Ellipse ROI created at (%d, %d) size (%d, %d)", x, y, w, h)


    def _style_handles(self):
        """Make handles VERY visible with YELLOW filled squares"""
        if self.roi is None:
            return

        # BRIGHT YELLOW filled handles
        handle_brush = pg.mkBrush(255, 255, 0, 255)    # Bright yellow fill
        handle_pen = pg.mkPen('k', width=2)             # Black border
        size = float(self.handle_size * 2)

        for handle_obj in self.roi.getHandles():
            # Handle objects have an 'item' attribute that is the actual graphics item
            if hasattr(handle_obj, 'item'):
                handle_item = handle_obj.item
            else:
                # Fallback - handle_obj might be the item itself
                handle_item = handle_obj
                
            if handle_item is None:
                continue

            try:
                # Actually change the size (Handle has setSize, not setRadius)
                if hasattr(handle_item, 'setSize'):
                    handle_item.setSize(size)
                elif hasattr(handle_item, 'setScale'):
                    # Fallback for older pyqtgraph versions
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
            
            # Show dimensions and indicate it's an ellipse
            if abs(size[0] - size[1]) < 2:
                # Nearly circular
                self.dimension_text.setText(f"⭕ {int(size[0])} × {int(size[1])}")
            else:
                # Elliptical
                self.dimension_text.setText(f"⬭ {int(size[0])} × {int(size[1])}")
            
            self.dimension_text.setVisible(self.enabled)
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update dimension display: %s", e)

    # ---------- Stats ----------

    def _update_stats(self):
        if not self.enabled or self.roi is None or self._last_image is None:
            return
        try:
            # Get bounding box
            roi_slice, _ = self.roi.getArraySlice(self._last_image, self.image_view.getImageItem())
            roi_data_box = self._last_image[roi_slice[0], roi_slice[1]]
            
            if roi_data_box.size == 0:
                self.stats_label.setText("Ellipse ROI outside image bounds")
                return

            pos = self.roi.pos()
            size = self.roi.size()

            # Create ellipse mask
            h, w = roi_data_box.shape[:2]
            y_coords, x_coords = np.ogrid[0:h, 0:w]
            
            center_x = w / 2
            center_y = h / 2
            a = size[0] / 2  # semi-major axis
            b = size[1] / 2  # semi-minor axis
            
            # Ellipse equation
            mask = ((x_coords - center_x) / a) ** 2 + ((y_coords - center_y) / b) ** 2 <= 1
            
            # Get data inside ellipse only
            roi_data = roi_data_box[mask]
            
            if roi_data.size == 0:
                self.stats_label.setText("Ellipse ROI contains no pixels")
                return

            roi_min = float(np.min(roi_data))
            roi_max = float(np.max(roi_data))
            roi_mean = float(np.mean(roi_data))
            roi_std = float(np.std(roi_data))
            roi_sum = float(np.sum(roi_data))
            
            # Calculate ellipse properties
            area = np.pi * a * b
            perimeter = np.pi * (3 * (a + b) - np.sqrt((3 * a + b) * (a + 3 * b)))
            
            shape_info = "Circle" if abs(size[0] - size[1]) < 2 else "Ellipse"

            self.stats_label.setText(
                f"Shape: {shape_info}\n\n"
                f"Position:\n  X: {pos[0]:.1f}\n  Y: {pos[1]:.1f}\n\n"
                f"Size:\n  W: {size[0]:.1f}\n  H: {size[1]:.1f}\n"
                f"  Area: {area:.1f} px²\n  Perim: {perimeter:.1f} px\n"
                f"  Pixels: {roi_data.size}\n\n"
                f"Stats:\n  Min: {roi_min:.2f}\n  Max: {roi_max:.2f}\n"
                f"  Mean: {roi_mean:.2f}\n  Std: {roi_std:.2f}\n  Sum: {roi_sum:.2f}"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update ellipse ROI stats: %s", e)
            self.stats_label.setText("Error calculating ellipse ROI stats")