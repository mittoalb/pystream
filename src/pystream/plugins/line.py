#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Line Profile Plugin for PyQtGraph Viewer - ImageJ-style
"""

import logging
from typing import Optional, Tuple
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class LineProfileManager:
    """
    Simple line drawing tool similar to ImageJ.
    - Click and drag to draw a line
    - Large, visible handles for precise positioning
    - Hold Shift for horizontal/vertical constraint
    - Drag anywhere on the line to move it
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        stats_label: QtWidgets.QLabel,
        logger: Optional[logging.Logger] = None,
        *,
        handle_size: int = 12,
        line_pen_width: int = 2,
        pixel_size_um: float = 1.0,
    ):
        self.image_view = image_view
        self.stats_label = stats_label
        self.logger = logger

        self.handle_size = max(8, int(handle_size))
        self.line_pen_width = max(1, int(line_pen_width))
        self.pixel_size_um = pixel_size_um

        self.line: Optional[pg.LineSegmentROI] = None
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None

        self._shift_pressed = False
        self._dragging_handle = None  # Track which handle is being dragged

    def set_pixel_size(self, pixel_size_um: float):
        self.pixel_size_um = pixel_size_um
        if self.enabled:
            self._update_stats()

    def toggle(self, state):
        from PyQt5.QtCore import Qt
        self.enabled = (state == Qt.Checked)

        if self.enabled:
            if self.line is None:
                if self._last_image is not None:
                    self._create_line_from_image(self._last_image)
                else:
                    self._create_line_default()
            self.line.setVisible(True)
            self.line.show()
            self._update_stats()
            self.stats_label.setText(
                "Line enabled\n"
                "(Hold Shift for H/V constraint)"
            )
        else:
            if self.line is not None:
                self.line.setVisible(False)
            self.stats_label.setText("No line selected")

    def reset(self):
        """Reset line to image center."""
        if self._last_image is None:
            QtWidgets.QMessageBox.information(None, "Reset Line", "No image available.")
            return

        if self.line is None:
            self._create_line_from_image(self._last_image)
            self.enabled = True

        h, w = self._last_image.shape[:2]
        x1, y1 = w // 3, h // 2
        x2, y2 = 2 * w // 3, h // 2

        self.line.setPos(x1, y1)
        handles = self.line.getHandles()
        if len(handles) >= 2:
            h0 = self._handle_item(handles[0])
            h1 = self._handle_item(handles[1])
            h0.setPos(0, 0)
            h1.setPos(x2 - x1, y2 - y1)

        self.line.setZValue(1000)
        self.line.setVisible(True)
        self.line.show()
        self._update_stats()

        if self.logger:
            self.logger.info("Line reset to (%d, %d) - (%d, %d)", x1, y1, x2, y2)

    def update_stats(self, image: np.ndarray):
        """Provide the current image (2D numpy array)."""
        self._last_image = image
        if self.enabled and self.line is None:
            self._create_line_from_image(image)
        if self.enabled and self.line is not None:
            self._update_stats()

    def get_line_profile(
        self, image: Optional[np.ndarray] = None
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Return line profile data as (positions, values).
        positions: distance along line in pixels
        values: intensity values along the line
        """
        if not self.enabled or self.line is None:
            return None

        img = image if image is not None else self._last_image
        if img is None:
            return None

        try:
            img_item = self.image_view.getImageItem()
            if img_item is None:
                return None

            handles = self.line.getHandles()
            if len(handles) < 2:
                return None

            p1_local = self._handle_pos(handles[0])
            p2_local = self._handle_pos(handles[1])

            p1 = self.line.mapToItem(img_item, p1_local)
            p2 = self.line.mapToItem(img_item, p2_local)

            x1, y1 = float(p1.x()), float(p1.y())
            x2, y2 = float(p2.x()), float(p2.y())

            length = int(np.hypot(x2 - x1, y2 - y1))
            if length < 1:
                return None

            x = np.linspace(x1, x2, length)
            y = np.linspace(y1, y2, length)

            h, w = img.shape[:2]
            x_int = np.clip(x.astype(int), 0, w - 1)
            y_int = np.clip(y.astype(int), 0, h - 1)

            values = img[y_int, x_int]
            positions = np.arange(length)

            return positions, values

        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to extract line profile: %s", e)
            return None

    def get_line_coords(self) -> Optional[dict]:
        """Return dict(x1, y1, x2, y2) in image pixel coordinates."""
        if self.line is None:
            return None

        try:
            img_item = self.image_view.getImageItem()
            if img_item is None:
                return None

            handles = self.line.getHandles()
            if len(handles) < 2:
                return None

            p1_local = self._handle_pos(handles[0])
            p2_local = self._handle_pos(handles[1])

            p1 = self.line.mapToItem(img_item, p1_local)
            p2 = self.line.mapToItem(img_item, p2_local)

            return {
                "x1": float(p1.x()), "y1": float(p1.y()),
                "x2": float(p2.x()), "y2": float(p2.y()),
            }
        except Exception:
            return None

    def set_line_coords(self, x1: float, y1: float, x2: float, y2: float):
        """Programmatically set line coordinates (in image pixel coordinates)."""
        if self.line is None:
            if self._last_image is not None:
                self._create_line_from_image(self._last_image)
            else:
                self._create_line_default()

        self.line.setPos(x1, y1)
        handles = self.line.getHandles()
        if len(handles) >= 2:
            h0 = self._handle_item(handles[0])
            h1 = self._handle_item(handles[1])
            h0.setPos(0, 0)
            h1.setPos(x2 - x1, y2 - y1)

        self.line.setZValue(1000)
        self.line.setVisible(True)
        self.line.show()
        self._update_stats()

        if self.logger:
            self.logger.info(
                "Line set to (%.1f, %.1f) - (%.1f, %.1f)", x1, y1, x2, y2
            )

    def cleanup(self):
        """Remove line from the view."""
        if self.line is not None:
            try:
                self.line.setParentItem(None)
                self.image_view.getView().removeItem(self.line)
            except Exception:
                pass
            self.line = None
        self.enabled = False
        self._last_image = None

    # ---------- Internals ----------

    @staticmethod
    def _handle_pos(h):
        if isinstance(h, dict):
            return h["pos"]
        return h.pos()

    @staticmethod
    def _handle_item(h):
        if hasattr(h, 'item'):
            return h.item
        return h

    def _create_line_from_image(self, image: np.ndarray):
        h, w = image.shape[:2]
        x1, y1 = w // 3, h // 2
        x2, y2 = 2 * w // 3, h // 2
        self._build_line(x1, y1, x2, y2)

    def _create_line_default(self):
        self._build_line(50, 50, 200, 50)

    def _build_line(self, x1, y1, x2, y2):
        img_item = self.image_view.getImageItem()

        # Bright yellow line for visibility
        pen = pg.mkPen((255, 255, 0), width=self.line_pen_width)
        hover_pen = pg.mkPen((255, 255, 100), width=self.line_pen_width + 1)

        positions = [[x1, y1], [x2, y2]]
        self.line = pg.LineSegmentROI(
            positions, pen=pen, hoverPen=hover_pen, movable=True
        )
        self.line.setZValue(1000)

        if img_item is not None:
            self.line.setParentItem(img_item)
        else:
            self.image_view.getView().addItem(self.line)

        # Style handles for high visibility
        self._style_handles()

        # Connect signals for shift-constraint
        self.line.sigRegionChangeStarted.connect(self._on_drag_start)
        self.line.sigRegionChanged.connect(self._on_region_changed)
        self.line.sigRegionChangeFinished.connect(self._on_drag_finish)

        # Install shift key handler
        self._install_key_handler()

        self.line.setVisible(True)
        self.line.show()

        if self.logger:
            self.logger.info("Line created at (%d, %d) - (%d, %d)", x1, y1, x2, y2)

    def _style_handles(self):
        """Style handles for high visibility - large, bright, easy to grab."""
        if self.line is None:
            return

        # Large, bright handles - easy to see and grab
        handle_brush = pg.mkBrush((255, 0, 0, 200))  # Bright red, slightly transparent
        handle_pen = pg.mkPen((255, 255, 255), width=2)  # White outline

        for h in self.line.getHandles():
            item = self._handle_item(h)
            if item is None:
                continue

            try:
                # Make handles large and visible
                item.setSize(self.handle_size)
                item.setBrush(handle_brush)
                item.setPen(handle_pen)

                # Ensure handles are on top
                item.setZValue(self.line.zValue() + 10)

            except Exception as e:
                if self.logger:
                    self.logger.debug("Handle styling issue: %s", e)

    def _install_key_handler(self):
        """Install event filter to detect Shift key."""
        key_filter = ShiftKeyFilter(self)

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(key_filter)

        view = self.image_view.getView()
        if view:
            view.installEventFilter(key_filter)

    def _on_drag_start(self):
        """Called when user starts dragging a handle."""
        self._dragging_handle = None

        if not self._shift_pressed:
            return

        # Determine which handle is being dragged
        handles = self.line.getHandles() if self.line is not None else []
        if len(handles) < 2:
            return

        # Store initial positions
        self._initial_pos_0 = QtCore.QPointF(self._handle_pos(handles[0]))
        self._initial_pos_1 = QtCore.QPointF(self._handle_pos(handles[1]))

    def _on_drag_finish(self):
        """Called when user finishes dragging."""
        self._dragging_handle = None

    def _on_region_changed(self):
        """Called when line is moved or resized - apply Shift constraint if needed."""
        if not self.enabled or self.line is None:
            return

        handles = self.line.getHandles()
        if len(handles) < 2:
            return

        # Apply shift constraint for horizontal/vertical lines
        if self._shift_pressed and hasattr(self, '_initial_pos_0'):
            p0 = self._handle_pos(handles[0])
            p1 = self._handle_pos(handles[1])

            # Detect which handle moved more
            dist0 = (p0 - self._initial_pos_0).manhattanLength()
            dist1 = (p1 - self._initial_pos_1).manhattanLength()

            if dist0 > dist1:
                # Handle 0 is moving, handle 1 is anchor
                moving_idx, anchor_idx = 0, 1
                moving_pos = p0
                anchor_pos = p1
            else:
                # Handle 1 is moving, handle 0 is anchor
                moving_idx, anchor_idx = 1, 0
                moving_pos = p1
                anchor_pos = p0

            # Calculate constrained position
            dx = moving_pos.x() - anchor_pos.x()
            dy = moving_pos.y() - anchor_pos.y()

            # Snap to horizontal or vertical
            if abs(dx) > abs(dy):
                # Horizontal line
                constrained_x = moving_pos.x()
                constrained_y = anchor_pos.y()
            else:
                # Vertical line
                constrained_x = anchor_pos.x()
                constrained_y = moving_pos.y()

            # Apply constraint
            self.line.blockSignals(True)
            moving_item = self._handle_item(handles[moving_idx])
            moving_item.setPos(constrained_x, constrained_y)
            self.line.blockSignals(False)

        self._update_stats()

    def _update_stats(self):
        """Update statistics display with line measurements."""
        if not self.enabled or self.line is None or self._last_image is None:
            return

        try:
            coords = self.get_line_coords()
            if coords is None:
                return

            x1, y1 = coords["x1"], coords["y1"]
            x2, y2 = coords["x2"], coords["y2"]

            length_px = float(np.hypot(x2 - x1, y2 - y1))
            length_um = length_px * self.pixel_size_um
            length_mm = length_um / 1000.0

            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if angle < 0:
                angle += 360.0

            dx_px = abs(x2 - x1)
            dy_px = abs(y2 - y1)
            dx_um = dx_px * self.pixel_size_um
            dy_um = dy_px * self.pixel_size_um

            profile = self.get_line_profile()
            if profile:
                positions, values = profile
                profile_min = float(np.min(values))
                profile_max = float(np.max(values))
                profile_mean = float(np.mean(values))
                profile_std = float(np.std(values))

                self.stats_label.setText(
                    f"Distance Measurement:\n"
                    f"  Length: {length_px:.1f} px = {length_um:.2f} µm = {length_mm:.4f} mm\n"
                    f"  ΔX: {dx_px:.1f} px = {dx_um:.2f} µm\n"
                    f"  ΔY: {dy_px:.1f} px = {dy_um:.2f} µm\n"
                    f"  Angle: {angle:.1f}°\n"
                    f"  Start: ({x1:.1f}, {y1:.1f})\n"
                    f"  End: ({x2:.1f}, {y2:.1f})\n\n"
                    f"Profile:\n"
                    f"  Points: {len(values)}\n"
                    f"  Min: {profile_min:.1f}\n"
                    f"  Max: {profile_max:.1f}\n"
                    f"  Mean: {profile_mean:.1f}\n"
                    f"  Std: {profile_std:.1f}"
                )
            else:
                self.stats_label.setText(
                    f"Distance Measurement:\n"
                    f"  Length: {length_px:.1f} px = {length_um:.2f} µm = {length_mm:.4f} mm\n"
                    f"  ΔX: {dx_px:.1f} px = {dx_um:.2f} µm\n"
                    f"  ΔY: {dy_px:.1f} px = {dy_um:.2f} µm\n"
                    f"  Angle: {angle:.1f}°\n"
                    f"  Start: ({x1:.1f}, {y1:.1f})\n"
                    f"  End: ({x2:.1f}, {y2:.1f})"
                )

        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update line stats: %s", e)
            self.stats_label.setText("Error calculating line stats")


class ShiftKeyFilter(QtCore.QObject):
    """Event filter to detect Shift key press/release."""

    def __init__(self, line_manager: LineProfileManager):
        super().__init__()
        self.line_manager = line_manager

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Shift:
                self.line_manager._shift_pressed = True

        elif event.type() == QtCore.QEvent.KeyRelease:
            if event.key() == QtCore.Qt.Key_Shift:
                self.line_manager._shift_pressed = False

        return False
