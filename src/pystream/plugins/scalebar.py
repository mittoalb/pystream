#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scale Bar Plugin for PyQtGraph Viewer
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui


class ScaleBarManager:
    """
    Scale bar overlay that can be toggled on/off.
    User can configure pixel size (nm/px, µm/px, etc.)
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        logger: Optional[logging.Logger] = None,
        *,
        pixel_size: float = 1.0,  # Default: 1.0 nm/px
        unit: str = "nm",
        bar_width_fraction: float = 0.25,  # Bar width as fraction of image width
        position: str = "bottom-right",  # "bottom-right", "bottom-left", "top-right", "top-left"
        bar_height: int = 8,  # Height of the scale bar in pixels
        font_size: int = 12,
        color: str = "white",
        margin: int = 20,  # Margin from edges
    ):
        self.image_view = image_view
        self.logger = logger

        # Scale bar settings
        self.pixel_size = pixel_size
        self.unit = unit
        self.bar_width_fraction = bar_width_fraction
        self.position = position
        self.bar_height = bar_height
        self.font_size = font_size
        self.color = color
        self.margin = margin

        # State
        self.enabled = False
        self._last_image: Optional[np.ndarray] = None

        # Graphics items
        self.bar_rect: Optional[pg.QtWidgets.QGraphicsRectItem] = None
        self.bar_text: Optional[pg.TextItem] = None

    # ---------- Public API ----------

    def toggle(self, state):
        """Toggle scale bar visibility."""
        from PyQt5.QtCore import Qt
        self.enabled = (state == Qt.Checked)

        if self.enabled:
            if self._last_image is not None:
                self._update_scale_bar()
            self._show_scale_bar()
        else:
            self._hide_scale_bar()

    def set_pixel_size(self, pixel_size: float, unit: str = None):
        """Set pixel size and optionally unit."""
        self.pixel_size = pixel_size
        if unit is not None:
            self.unit = unit
        
        if self.enabled and self._last_image is not None:
            self._update_scale_bar()
        
        if self.logger:
            self.logger.info("Scale bar pixel size set to %.3f %s/px", pixel_size, self.unit)

    def set_position(self, position: str):
        """Set scale bar position: bottom-right, bottom-left, top-right, top-left."""
        valid_positions = ["bottom-right", "bottom-left", "top-right", "top-left"]
        if position not in valid_positions:
            if self.logger:
                self.logger.warning("Invalid position '%s'. Using 'bottom-right'", position)
            position = "bottom-right"
        
        self.position = position
        if self.enabled and self._last_image is not None:
            self._update_scale_bar()

    def set_color(self, color: str):
        """Set scale bar color (e.g., 'white', 'black', 'yellow')."""
        self.color = color
        if self.enabled and self._last_image is not None:
            self._update_scale_bar()

    def update_image(self, image: np.ndarray):
        """Update with new image dimensions."""
        self._last_image = image
        if self.enabled:
            self._update_scale_bar()

    def cleanup(self):
        """Remove scale bar from view."""
        self._hide_scale_bar()
        if self.bar_rect is not None:
            try:
                self.image_view.getView().removeItem(self.bar_rect)
            except Exception:
                pass
            self.bar_rect = None
        
        if self.bar_text is not None:
            try:
                self.image_view.getView().removeItem(self.bar_text)
            except Exception:
                pass
            self.bar_text = None
        
        self.enabled = False
        self._last_image = None

    # ---------- Internals ----------

    def _show_scale_bar(self):
        """Show scale bar and text."""
        if self.bar_rect is not None:
            self.bar_rect.show()
        if self.bar_text is not None:
            self.bar_text.show()

    def _hide_scale_bar(self):
        """Hide scale bar and text."""
        if self.bar_rect is not None:
            self.bar_rect.hide()
        if self.bar_text is not None:
            self.bar_text.hide()

    def _update_scale_bar(self):
        """Create or update the scale bar based on current image and settings."""
        if self._last_image is None:
            return

        h, w = self._last_image.shape[:2]

        # Calculate bar length in pixels
        # We want a "nice" round number for the scale bar
        desired_bar_width_px = w * self.bar_width_fraction
        desired_bar_width_real = desired_bar_width_px * self.pixel_size

        # Round to nice number
        bar_width_real = self._get_nice_scale(desired_bar_width_real)
        bar_width_px = bar_width_real / self.pixel_size

        # Calculate position
        x, y = self._calculate_position(w, h, bar_width_px)

        # Create or update rectangle
        if self.bar_rect is None:
            self.bar_rect = pg.QtWidgets.QGraphicsRectItem(x, y, bar_width_px, self.bar_height)
            color_obj = pg.mkColor(self.color)
            self.bar_rect.setBrush(pg.mkBrush(color_obj))
            self.bar_rect.setPen(pg.mkPen(None))
            self.bar_rect.setZValue(2000)
            
            # Add to view
            img_item = self.image_view.getImageItem()
            if img_item is not None:
                self.bar_rect.setParentItem(img_item)
            else:
                self.image_view.getView().addItem(self.bar_rect)
        else:
            self.bar_rect.setRect(x, y, bar_width_px, self.bar_height)
            color_obj = pg.mkColor(self.color)
            self.bar_rect.setBrush(pg.mkBrush(color_obj))

        # Create or update text
        text = self._format_scale_text(bar_width_real)
        text_x, text_y = self._calculate_text_position(x, y, bar_width_px)

        if self.bar_text is None:
            self.bar_text = pg.TextItem(text, anchor=(0.5, 1), color=self.color)
            self.bar_text.setFont(QtGui.QFont("Arial", self.font_size, QtGui.QFont.Bold))
            self.bar_text.setZValue(2001)
            
            # Add to view
            img_item = self.image_view.getImageItem()
            if img_item is not None:
                self.bar_text.setParentItem(img_item)
            else:
                self.image_view.getView().addItem(self.bar_text)
        else:
            self.bar_text.setText(text)
            self.bar_text.setColor(self.color)

        self.bar_text.setPos(text_x, text_y)

        if self.logger:
            self.logger.debug("Scale bar updated: %.1f px = %.2f %s", bar_width_px, bar_width_real, self.unit)

    def _get_nice_scale(self, value: float) -> float:
        """
        Round to a nice scale bar value (1, 2, 5, 10, 20, 50, 100, etc.).
        """
        if value <= 0:
            return 1.0

        # Get order of magnitude
        magnitude = 10 ** np.floor(np.log10(value))
        
        # Normalize to 1-10 range
        normalized = value / magnitude
        
        # Round to nice number
        if normalized < 1.5:
            nice = 1.0
        elif normalized < 3.5:
            nice = 2.0
        elif normalized < 7.5:
            nice = 5.0
        else:
            nice = 10.0
        
        return nice * magnitude

    def _format_scale_text(self, value: float) -> str:
        """Format scale bar text with appropriate precision."""
        # Determine precision based on magnitude
        if value >= 1000:
            # Show in next unit up if available
            if self.unit == "nm":
                return f"{value/1000:.1f} µm"
            elif self.unit == "µm":
                return f"{value/1000:.1f} mm"
            elif self.unit == "mm":
                return f"{value/1000:.1f} m"
        
        # Standard formatting
        if value >= 100:
            return f"{int(value)} {self.unit}"
        elif value >= 10:
            return f"{value:.1f} {self.unit}"
        else:
            return f"{value:.2f} {self.unit}"

    def _calculate_position(self, img_w: int, img_h: int, bar_w: float) -> tuple:
        """Calculate x, y position for scale bar based on position setting."""
        margin = self.margin
        
        if self.position == "bottom-right":
            x = img_w - bar_w - margin
            y = img_h - self.bar_height - margin
        elif self.position == "bottom-left":
            x = margin
            y = img_h - self.bar_height - margin
        elif self.position == "top-right":
            x = img_w - bar_w - margin
            y = margin
        elif self.position == "top-left":
            x = margin
            y = margin
        else:
            # Default to bottom-right
            x = img_w - bar_w - margin
            y = img_h - self.bar_height - margin
        
        return x, y

    def _calculate_text_position(self, bar_x: float, bar_y: float, bar_w: float) -> tuple:
        """Calculate text position (centered above bar)."""
        text_x = bar_x + bar_w / 2
        text_y = bar_y - 5  # 5 pixels above the bar
        return text_x, text_y


class ScaleBarDialog(QtWidgets.QDialog):
    """Dialog for configuring scale bar settings."""
    
    def __init__(self, scale_bar_manager: ScaleBarManager, parent=None):
        super().__init__(parent)
        self.scale_bar = scale_bar_manager
        
        self.setWindowTitle("Scale Bar Settings")
        self.setModal(False)
        self.resize(350, 300)
        
        self._build_ui()
        self._load_current_settings()
    
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Pixel size group
        pixel_group = QtWidgets.QGroupBox("Pixel Size")
        pixel_layout = QtWidgets.QFormLayout()
        
        self.pixel_size_input = QtWidgets.QDoubleSpinBox()
        self.pixel_size_input.setDecimals(4)
        self.pixel_size_input.setRange(0.0001, 1000000)
        self.pixel_size_input.setValue(1.0)
        pixel_layout.addRow("Size:", self.pixel_size_input)
        
        self.unit_input = QtWidgets.QComboBox()
        self.unit_input.addItems(["nm", "µm", "mm", "m", "Å", "px"])
        pixel_layout.addRow("Unit:", self.unit_input)
        
        pixel_group.setLayout(pixel_layout)
        layout.addWidget(pixel_group)
        
        # Appearance group
        appearance_group = QtWidgets.QGroupBox("Appearance")
        appearance_layout = QtWidgets.QFormLayout()
        
        self.position_input = QtWidgets.QComboBox()
        self.position_input.addItems(["bottom-right", "bottom-left", "top-right", "top-left"])
        appearance_layout.addRow("Position:", self.position_input)
        
        self.color_input = QtWidgets.QComboBox()
        self.color_input.addItems(["white", "black", "yellow", "red", "green", "blue", "cyan", "magenta"])
        appearance_layout.addRow("Color:", self.color_input)
        
        self.bar_width_input = QtWidgets.QSpinBox()
        self.bar_width_input.setRange(10, 50)
        self.bar_width_input.setValue(25)
        self.bar_width_input.setSuffix(" %")
        appearance_layout.addRow("Bar Width:", self.bar_width_input)
        
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        btn_apply = QtWidgets.QPushButton("Apply")
        btn_apply.clicked.connect(self._apply_settings)
        button_layout.addWidget(btn_apply)
        
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(self.close)
        button_layout.addWidget(btn_close)
        
        layout.addLayout(button_layout)
    
    def _load_current_settings(self):
        """Load current scale bar settings into UI."""
        self.pixel_size_input.setValue(self.scale_bar.pixel_size)
        
        # Set unit
        unit_idx = self.unit_input.findText(self.scale_bar.unit)
        if unit_idx >= 0:
            self.unit_input.setCurrentIndex(unit_idx)
        
        # Set position
        pos_idx = self.position_input.findText(self.scale_bar.position)
        if pos_idx >= 0:
            self.position_input.setCurrentIndex(pos_idx)
        
        # Set color
        color_idx = self.color_input.findText(self.scale_bar.color)
        if color_idx >= 0:
            self.color_input.setCurrentIndex(color_idx)
        
        # Set bar width
        self.bar_width_input.setValue(int(self.scale_bar.bar_width_fraction * 100))
    
    def _apply_settings(self):
        """Apply settings to scale bar manager."""
        pixel_size = self.pixel_size_input.value()
        unit = self.unit_input.currentText()
        position = self.position_input.currentText()
        color = self.color_input.currentText()
        bar_width = self.bar_width_input.value() / 100.0
        
        self.scale_bar.set_pixel_size(pixel_size, unit)
        self.scale_bar.set_position(position)
        self.scale_bar.set_color(color)
        self.scale_bar.bar_width_fraction = bar_width
        
        if self.scale_bar.enabled and self.scale_bar._last_image is not None:
            self.scale_bar._update_scale_bar()
        
        QtWidgets.QMessageBox.information(self, "Settings Applied", "Scale bar settings updated successfully!")