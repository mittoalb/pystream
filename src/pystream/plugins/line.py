#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Line Profile Plugin for PyQtGraph Viewer
"""

import logging
from typing import Optional, Tuple
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui


class LineProfileManager:
    """
    Line drawing tool with Shift-constrain for vertical/horizontal lines (ImageJ-style).
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        stats_label: QtWidgets.QLabel,
        logger: Optional[logging.Logger] = None,
        *,
        handle_size: int = 20,
        line_pen_width: int = 3,
    ):
        self.image_view = image_view
        self.stats_label = stats_label
        self.logger = logger

        self.handle_size = max(8, int(handle_size))
        self.line_pen_width = max(1, int(line_pen_width))

        self.line: Optional[pg.LineSegmentROI] = None
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None
        
        # For Shift-key constraint
        self._shift_pressed = False
        self._original_pos = None
        self._dragging_handle = None

    # ---------- Public API ----------

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
            self.stats_label.setText("Line enabled\n(drag endpoints; hold Ctrl for H/V constraint)")
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
        # Create diagonal line in center
        x1, y1 = w // 3, h // 2
        x2, y2 = 2 * w // 3, h // 2
        
        self.line.setPos([x1, y1])
        self.line.setEndpoints([0, 0], [x2 - x1, y2 - y1])
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

    def get_line_profile(self, image: Optional[np.ndarray] = None) -> Optional[Tuple[np.ndarray, np.ndarray]]:
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
            # Get line endpoints
            pos = self.line.pos()
            handles = self.line.getHandles()
            if len(handles) < 2:
                return None
            
            p1 = self.line.mapToItem(self.image_view.getImageItem(), handles[0].pos())
            p2 = self.line.mapToItem(self.image_view.getImageItem(), handles[1].pos())
            
            x1, y1 = int(p1.x()), int(p1.y())
            x2, y2 = int(p2.x()), int(p2.y())
            
            # Generate points along the line
            length = int(np.sqrt((x2 - x1)**2 + (y2 - y1)**2))
            if length < 1:
                return None
            
            x = np.linspace(x1, x2, length)
            y = np.linspace(y1, y2, length)
            
            # Sample image at line coordinates
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
            handles = self.line.getHandles()
            if len(handles) < 2:
                return None
            
            p1 = self.line.mapToItem(self.image_view.getImageItem(), handles[0].pos())
            p2 = self.line.mapToItem(self.image_view.getImageItem(), handles[1].pos())
            
            return {
                "x1": p1.x(), "y1": p1.y(),
                "x2": p2.x(), "y2": p2.y()
            }
        except Exception:
            return None

    def set_line_coords(self, x1: float, y1: float, x2: float, y2: float):
        """Programmatically set line coordinates."""
        if self.line is None:
            if self._last_image is not None:
                self._create_line_from_image(self._last_image)
            else:
                self._create_line_default()
        
        self.line.setPos([x1, y1])
        self.line.setEndpoints([0, 0], [x2 - x1, y2 - y1])
        self.line.setZValue(1000)
        self.line.setVisible(True)
        self.line.show()
        self._update_stats()
        
        if self.logger:
            self.logger.info("Line set to (%.1f, %.1f) - (%.1f, %.1f)", x1, y1, x2, y2)

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

    def _create_line_from_image(self, image: np.ndarray):
        h, w = image.shape[:2]
        x1, y1 = w // 3, h // 2
        x2, y2 = 2 * w // 3, h // 2
        self._build_line(x1, y1, x2, y2)

    def _create_line_default(self):
        self._build_line(50, 50, 200, 50)

    def _build_line(self, x1, y1, x2, y2):
        """Create LineSegmentROI with Ctrl-constraint capability."""
        img_item = self.image_view.getImageItem()
        pen = pg.mkPen('c', width=self.line_pen_width)  # Cyan line
        hover_pen = pg.mkPen((0, 255, 255, 220), width=self.line_pen_width + 2)

        # Create line from (x1,y1) to (x2,y2)
        positions = [[x1, y1], [x2, y2]]
        self.line = pg.LineSegmentROI(positions, pen=pen, hoverPen=hover_pen, movable=True)
        self.line.setZValue(1000)

        # Parent to ImageItem
        if img_item is not None:
            self.line.setParentItem(img_item)
        else:
            self.image_view.getView().addItem(self.line)

        # Style handles
        self._style_handles()

        # Connect signals for ctrl-constraint with immediate feedback
        self.line.sigRegionChanged.connect(self._on_region_changed)
        self.line.sigRegionChangeStarted.connect(self._on_drag_start)
        self.line.sigRegionChangeFinished.connect(self._on_drag_finish)

        # Install event filter for ctrl key on the main window
        self._install_key_handler()

        self.line.setVisible(True)
        self.line.show()

        if self.logger:
            self.logger.info("Line created at (%d, %d) - (%d, %d)", x1, y1, x2, y2)

    def _style_handles(self):
        """Style the line endpoint handles."""
        brush = pg.mkBrush(0, 255, 255, 255)  # cyan
        pen = pg.mkPen(0, 0, 0, 255, width=1)  # black outline

        for h in self.line.getHandles():
            # Handle is an object with 'item' attribute, not a dict
            item = h['item'] if isinstance(h, dict) else getattr(h, 'item', None)
            if item is None:
                continue
            
            # Set size
            if hasattr(item, "setSize"):
                try:
                    item.setSize(self.handle_size)
                except Exception:
                    pass
            
            # Set colors
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

    def _install_key_handler(self):
        """Install event filter to detect Ctrl key on application level."""
        # Install on the QApplication to catch all keyboard events
        QtWidgets.QApplication.instance().installEventFilter(CtrlKeyFilter(self))
        
        # Also install on the view for redundancy
        view = self.image_view.getView()
        if view and view.scene():
            view.scene().installEventFilter(CtrlKeyFilter(self))

    def _on_region_changed(self):
        """Called whenever the line region changes (during drag)."""
        # Apply constraint if Ctrl is pressed
        if self._shift_pressed:
            self.constrain_to_axis()
        else:
            self._update_stats()

    def _on_drag_start(self):
        """Called when user starts dragging."""
        if self.line is None:
            return
        
        # Store original position
        handles = self.line.getHandles()
        if len(handles) >= 2:
            try:
                p1 = self.line.mapToItem(self.image_view.getImageItem(), handles[0].pos())
                p2 = self.line.mapToItem(self.image_view.getImageItem(), handles[1].pos())
                self._original_pos = (p1.x(), p1.y(), p2.x(), p2.y())
            except Exception:
                pass

    def _on_drag_finish(self):
        """Called when user finishes dragging."""
        self._original_pos = None
        self._dragging_handle = None

    def constrain_to_axis(self):
        """Constrain line to horizontal or vertical when Shift is pressed."""
        if self.line is None or self._original_pos is None:
            return
        
        try:
            handles = self.line.getHandles()
            if len(handles) < 2:
                return
            
            # Get current positions
            p1 = self.line.mapToItem(self.image_view.getImageItem(), handles[0].pos())
            p2 = self.line.mapToItem(self.image_view.getImageItem(), handles[1].pos())
            
            x1_orig, y1_orig, x2_orig, y2_orig = self._original_pos
            
            # Determine which handle is being dragged
            dist1 = (p1.x() - x1_orig)**2 + (p1.y() - y1_orig)**2
            dist2 = (p2.x() - x2_orig)**2 + (p2.y() - y2_orig)**2
            
            if dist1 > dist2:
                # Handle 1 is moving, constrain it
                dx = abs(p1.x() - x2_orig)
                dy = abs(p1.y() - y2_orig)
                
                if dx > dy:
                    # Horizontal constraint
                    new_y = y2_orig
                    self.line.setEndpoints([x2_orig, y2_orig], [p1.x(), new_y])
                else:
                    # Vertical constraint
                    new_x = x2_orig
                    self.line.setEndpoints([x2_orig, y2_orig], [new_x, p1.y()])
            else:
                # Handle 2 is moving, constrain it
                dx = abs(p2.x() - x1_orig)
                dy = abs(p2.y() - y1_orig)
                
                if dx > dy:
                    # Horizontal constraint
                    new_y = y1_orig
                    self.line.setEndpoints([x1_orig, y1_orig], [p2.x(), new_y])
                else:
                    # Vertical constraint
                    new_x = x1_orig
                    self.line.setEndpoints([x1_orig, y1_orig], [new_x, p2.y()])
                    
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to constrain line: %s", e)

    # ---------- Stats ----------

    def _update_stats(self):
        """Update statistics label with line info and profile stats."""
        if not self.enabled or self.line is None or self._last_image is None:
            return
        
        try:
            coords = self.get_line_coords()
            if coords is None:
                return
            
            x1, y1 = coords['x1'], coords['y1']
            x2, y2 = coords['x2'], coords['y2']
            
            # Calculate length
            length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
            # Get angle (0-360 degrees, 0=right, 90=down)
            angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
            if angle < 0:
                angle += 360
            
            # Get profile data
            profile = self.get_line_profile()
            if profile:
                positions, values = profile
                profile_min = float(np.min(values))
                profile_max = float(np.max(values))
                profile_mean = float(np.mean(values))
                profile_std = float(np.std(values))
                
                self.stats_label.setText(
                    f"Line:\n"
                    f"  Start: ({x1:.1f}, {y1:.1f})\n"
                    f"  End: ({x2:.1f}, {y2:.1f})\n"
                    f"  Length: {length:.1f} px\n"
                    f"  Angle: {angle:.1f}°\n\n"
                    f"Profile:\n"
                    f"  Points: {len(values)}\n"
                    f"  Min: {profile_min:.2f}\n"
                    f"  Max: {profile_max:.2f}\n"
                    f"  Mean: {profile_mean:.2f}\n"
                    f"  Std: {profile_std:.2f}"
                )
            else:
                self.stats_label.setText(
                    f"Line:\n"
                    f"  Start: ({x1:.1f}, {y1:.1f})\n"
                    f"  End: ({x2:.1f}, {y2:.1f})\n"
                    f"  Length: {length:.1f} px\n"
                    f"  Angle: {angle:.1f}°"
                )
                
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to update line stats: %s", e)
            self.stats_label.setText("Error calculating line stats")


class CtrlKeyFilter(QtCore.QObject):
    """Event filter to detect Left Ctrl key press/release."""
    
    def __init__(self, line_manager: LineProfileManager):
        super().__init__()
        self.line_manager = line_manager
    
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            # Check for Left Control key specifically
            if event.key() == QtCore.Qt.Key_Control:
                self.line_manager._shift_pressed = True
                if self.line_manager.line and self.line_manager._original_pos:
                    self.line_manager.constrain_to_axis()
        elif event.type() == QtCore.QEvent.KeyRelease:
            if event.key() == QtCore.Qt.Key_Control:
                self.line_manager._shift_pressed = False
        
        return False  # Don't consume the event