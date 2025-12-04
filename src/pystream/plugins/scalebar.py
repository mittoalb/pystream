#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scale Bar Plugin for PyQtGraph Viewer - Dual Scale Bar Support
"""

import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtGui


class SingleScaleBar:
    """
    Single scale bar instance with its own settings and graphics items.
    """
    
    def __init__(
        self,
        image_view: pg.ImageView,
        logger: Optional[logging.Logger] = None,
        *,
        pixel_size: float = 1.0,
        unit: str = "nm",
        bar_width_fraction: float = 0.25,
        position: str = "bottom-right",
        bar_height: int = 8,
        font_size: int = 12,
        color: str = "white",
        margin: int = 20,
        vertical_offset: int = 0,  # Additional vertical offset for stacking
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
        self.vertical_offset = vertical_offset
        
        # State
        self.enabled = False
        
        # Graphics items
        self.bar_rect: Optional[QtWidgets.QGraphicsRectItem] = None
        self.bar_text: Optional[pg.TextItem] = None
    
    def show(self):
        """Show scale bar and text."""
        if self.bar_rect is not None:
            self.bar_rect.show()
        if self.bar_text is not None:
            self.bar_text.show()
    
    def hide(self):
        """Hide scale bar and text."""
        if self.bar_rect is not None:
            self.bar_rect.hide()
        if self.bar_text is not None:
            self.bar_text.hide()
    
    def cleanup(self):
        """Remove scale bar graphics items."""
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
    
    def update(self, image: np.ndarray):
        """Update scale bar based on image dimensions."""
        if not self.enabled:
            return
        
        h, w = image.shape[:2]
        
        # Calculate bar length in pixels
        desired_bar_width_px = w * self.bar_width_fraction
        desired_bar_width_real = desired_bar_width_px * self.pixel_size
        
        # Round to nice number
        bar_width_real = self._get_nice_scale(desired_bar_width_real)
        bar_width_px = bar_width_real / self.pixel_size
        
        # Calculate position
        x, y = self._calculate_position(w, h, bar_width_px)
        
        # Create or update rectangle
        if self.bar_rect is None:
            self.bar_rect = QtWidgets.QGraphicsRectItem(x, y, bar_width_px, self.bar_height)
            color_obj = pg.mkColor(self.color)
            self.bar_rect.setBrush(pg.mkBrush(color_obj))
            self.bar_rect.setPen(pg.mkPen(None))
            self.bar_rect.setZValue(2000)
            
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
        """Round to a nice scale bar value (1, 2, 5, 10, 20, 50, 100, etc.)."""
        if value <= 0:
            return 1.0
        
        magnitude = 10 ** np.floor(np.log10(value))
        normalized = value / magnitude
        
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
        if value >= 1000:
            if self.unit == "nm":
                return f"{value/1000:.1f} µm"
            elif self.unit == "µm":
                return f"{value/1000:.1f} mm"
            elif self.unit == "mm":
                return f"{value/1000:.1f} m"
        
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
            y = img_h - self.bar_height - margin - self.vertical_offset
        elif self.position == "bottom-left":
            x = margin
            y = img_h - self.bar_height - margin - self.vertical_offset
        elif self.position == "top-right":
            x = img_w - bar_w - margin
            y = margin + self.vertical_offset
        elif self.position == "top-left":
            x = margin
            y = margin + self.vertical_offset
        else:
            x = img_w - bar_w - margin
            y = img_h - self.bar_height - margin - self.vertical_offset
        
        return x, y
    
    def _calculate_text_position(self, bar_x: float, bar_y: float, bar_w: float) -> tuple:
        """Calculate text position (centered above bar)."""
        text_x = bar_x + bar_w / 2
        text_y = bar_y - 5
        return text_x, text_y


class ScaleBarManager:
    """
    Manages multiple scale bars that can be toggled independently.
    Supports two scale bars with different pixel sizes.
    
    Backward compatible interface - single toggle controls both bars,
    but settings dialog allows independent configuration.
    """

    def __init__(
        self,
        image_view: pg.ImageView,
        logger: Optional[logging.Logger] = None,
        *,
        pixel_size: float = 1.0,
        unit: str = "nm",
        bar_width_fraction: float = 0.25,
        position: str = "bottom-right",
        bar_height: int = 8,
        font_size: int = 12,
        color: str = "white",
        margin: int = 20,
    ):
        self.image_view = image_view
        self.logger = logger
        
        # State
        self._last_image: Optional[np.ndarray] = None
        self._global_enabled = False  # Master toggle state
        
        # Create two independent scale bars
        self.scale_bar_1 = SingleScaleBar(
            image_view=image_view,
            logger=logger,
            pixel_size=pixel_size,
            unit=unit,
            position=position,
            color=color,
            bar_width_fraction=bar_width_fraction,
            bar_height=bar_height,
            font_size=font_size,
            margin=margin,
            vertical_offset=0,
        )
        
        # Second scale bar with different defaults
        self.scale_bar_2 = SingleScaleBar(
            image_view=image_view,
            logger=logger,
            pixel_size=pixel_size * 10,  # 10x the first scale
            unit=unit,
            position=position,
            color="yellow",
            bar_width_fraction=bar_width_fraction,
            bar_height=bar_height,
            font_size=font_size,
            margin=margin,
            vertical_offset=40,  # Stack 40 pixels above the first bar
        )
        
        # Individual enable states (for settings dialog)
        self.bar_1_individually_enabled = True
        self.bar_2_individually_enabled = True

    # ---------- Public API (Backward Compatible) ----------

    def toggle(self, state):
        """
        Toggle scale bars visibility (master control).
        This maintains backward compatibility with single checkbox.
        """
        from PyQt5.QtCore import Qt
        self._global_enabled = (state == Qt.Checked)

        if self._global_enabled:
            # Show bars that are individually enabled
            if self.bar_1_individually_enabled:
                self.scale_bar_1.enabled = True
                if self._last_image is not None:
                    self.scale_bar_1.update(self._last_image)
                self.scale_bar_1.show()
            
            if self.bar_2_individually_enabled:
                self.scale_bar_2.enabled = True
                if self._last_image is not None:
                    self.scale_bar_2.update(self._last_image)
                self.scale_bar_2.show()
        else:
            # Hide both bars
            self.scale_bar_1.enabled = False
            self.scale_bar_1.hide()
            self.scale_bar_2.enabled = False
            self.scale_bar_2.hide()

    def toggle_bar_1(self, state):
        """Toggle scale bar 1 visibility (for advanced control)."""
        from PyQt5.QtCore import Qt
        self.bar_1_individually_enabled = (state == Qt.Checked)
        
        if self._global_enabled:
            self.scale_bar_1.enabled = self.bar_1_individually_enabled
            if self.scale_bar_1.enabled:
                if self._last_image is not None:
                    self.scale_bar_1.update(self._last_image)
                self.scale_bar_1.show()
            else:
                self.scale_bar_1.hide()

    def toggle_bar_2(self, state):
        """Toggle scale bar 2 visibility (for advanced control)."""
        from PyQt5.QtCore import Qt
        self.bar_2_individually_enabled = (state == Qt.Checked)
        
        if self._global_enabled:
            self.scale_bar_2.enabled = self.bar_2_individually_enabled
            if self.scale_bar_2.enabled:
                if self._last_image is not None:
                    self.scale_bar_2.update(self._last_image)
                self.scale_bar_2.show()
            else:
                self.scale_bar_2.hide()

    def set_pixel_size(self, pixel_size: float, unit: str = None):
        """
        Set pixel size for scale bar 1 (backward compatibility).
        Scale bar 2 automatically scales by 10x.
        """
        self.scale_bar_1.pixel_size = pixel_size
        if unit is not None:
            self.scale_bar_1.unit = unit
        
        # Auto-scale bar 2 to 10x
        self.scale_bar_2.pixel_size = pixel_size * 10
        if unit is not None:
            self.scale_bar_2.unit = unit
        
        if self._global_enabled and self._last_image is not None:
            if self.bar_1_individually_enabled:
                self.scale_bar_1.update(self._last_image)
            if self.bar_2_individually_enabled:
                self.scale_bar_2.update(self._last_image)
        
        if self.logger:
            self.logger.info("Scale bar 1 pixel size set to %.3f %s/px", pixel_size, self.scale_bar_1.unit)
            self.logger.info("Scale bar 2 pixel size set to %.3f %s/px", pixel_size * 10, self.scale_bar_2.unit)

    def update_image(self, image: np.ndarray):
        """Update with new image dimensions."""
        self._last_image = image
        if self._global_enabled:
            if self.bar_1_individually_enabled:
                self.scale_bar_1.update(image)
            if self.bar_2_individually_enabled:
                self.scale_bar_2.update(image)

    def cleanup(self):
        """Remove both scale bars from view."""
        self.scale_bar_1.cleanup()
        self.scale_bar_2.cleanup()
        self._last_image = None
        self._global_enabled = False

    def get_scale_bar(self, bar_num: int) -> SingleScaleBar:
        """Get a specific scale bar instance (1 or 2)."""
        if bar_num == 1:
            return self.scale_bar_1
        elif bar_num == 2:
            return self.scale_bar_2
        else:
            raise ValueError(f"Invalid bar number: {bar_num}. Must be 1 or 2.")
    
    # Backward compatibility properties
    @property
    def enabled(self):
        return self._global_enabled
    
    @property
    def pixel_size(self):
        return self.scale_bar_1.pixel_size
    
    @property
    def unit(self):
        return self.scale_bar_1.unit


class ScaleBarDialog(QtWidgets.QDialog):
    """Dialog for configuring dual scale bar settings."""
    
    def __init__(self, scale_bar_manager: ScaleBarManager, parent=None):
        super().__init__(parent)
        self.scale_bar = scale_bar_manager
        
        self.setWindowTitle("Scale Bar Settings")
        self.setModal(False)
        self.resize(450, 550)
        
        self._build_ui()
        self._load_current_settings()
    
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Master enable info
        info_label = QtWidgets.QLabel(
            "💡 Tip: Use the main checkbox to show/hide both scale bars.\n"
            "Use the checkboxes below to enable/disable individual bars."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px;")
        layout.addWidget(info_label)
        
        # Tab widget for two scale bars
        self.tab_widget = QtWidgets.QTabWidget()
        
        # Scale Bar 1 Tab
        tab1 = QtWidgets.QWidget()
        self.tab_widget.addTab(tab1, "Scale Bar 1")
        self._build_bar_settings(tab1, bar_num=1)
        
        # Scale Bar 2 Tab
        tab2 = QtWidgets.QWidget()
        self.tab_widget.addTab(tab2, "Scale Bar 2")
        self._build_bar_settings(tab2, bar_num=2)
        
        layout.addWidget(self.tab_widget)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        btn_apply = QtWidgets.QPushButton("Apply All")
        btn_apply.clicked.connect(self._apply_all_settings)
        button_layout.addWidget(btn_apply)
        
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(self.close)
        button_layout.addWidget(btn_close)
        
        layout.addLayout(button_layout)
    
    def _build_bar_settings(self, parent_widget, bar_num: int):
        """Build settings UI for a specific scale bar."""
        layout = QtWidgets.QVBoxLayout(parent_widget)
        
        # Enable/disable checkbox at top
        enable_checkbox = QtWidgets.QCheckBox(f"Enable Scale Bar {bar_num}")
        enable_checkbox.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(enable_checkbox)
        
        layout.addWidget(QtWidgets.QLabel(""))  # Spacer
        
        # Pixel size group
        pixel_group = QtWidgets.QGroupBox("Pixel Size")
        pixel_layout = QtWidgets.QFormLayout()
        
        pixel_size_input = QtWidgets.QDoubleSpinBox()
        pixel_size_input.setDecimals(4)
        pixel_size_input.setRange(0.0001, 1000000)
        pixel_size_input.setValue(1.0)
        pixel_layout.addRow("Size:", pixel_size_input)
        
        unit_input = QtWidgets.QComboBox()
        unit_input.addItems(["nm", "µm", "mm", "m", "Å", "px"])
        pixel_layout.addRow("Unit:", unit_input)
        
        pixel_group.setLayout(pixel_layout)
        layout.addWidget(pixel_group)
        
        # Appearance group
        appearance_group = QtWidgets.QGroupBox("Appearance")
        appearance_layout = QtWidgets.QFormLayout()
        
        position_input = QtWidgets.QComboBox()
        position_input.addItems(["bottom-right", "bottom-left", "top-right", "top-left"])
        appearance_layout.addRow("Position:", position_input)
        
        color_input = QtWidgets.QComboBox()
        color_input.addItems(["white", "black", "yellow", "red", "green", "blue", "cyan", "magenta"])
        appearance_layout.addRow("Color:", color_input)
        
        bar_width_input = QtWidgets.QSpinBox()
        bar_width_input.setRange(10, 50)
        bar_width_input.setValue(25)
        bar_width_input.setSuffix(" %")
        appearance_layout.addRow("Bar Width:", bar_width_input)
        
        vertical_offset_input = QtWidgets.QSpinBox()
        vertical_offset_input.setRange(0, 200)
        vertical_offset_input.setValue(0)
        vertical_offset_input.setSuffix(" px")
        appearance_layout.addRow("Vertical Offset:", vertical_offset_input)
        
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)
        
        layout.addStretch()
        
        # Apply button for this bar only
        btn_apply_bar = QtWidgets.QPushButton(f"Apply Scale Bar {bar_num}")
        btn_apply_bar.clicked.connect(lambda: self._apply_bar_settings(bar_num))
        layout.addWidget(btn_apply_bar)
        
        # Store widgets for later access
        if bar_num == 1:
            self.bar1_enabled = enable_checkbox
            self.bar1_pixel_size = pixel_size_input
            self.bar1_unit = unit_input
            self.bar1_position = position_input
            self.bar1_color = color_input
            self.bar1_width = bar_width_input
            self.bar1_offset = vertical_offset_input
        else:
            self.bar2_enabled = enable_checkbox
            self.bar2_pixel_size = pixel_size_input
            self.bar2_unit = unit_input
            self.bar2_position = position_input
            self.bar2_color = color_input
            self.bar2_width = bar_width_input
            self.bar2_offset = vertical_offset_input
    
    def _load_current_settings(self):
        """Load current scale bar settings into UI."""
        # Scale Bar 1
        bar1 = self.scale_bar.scale_bar_1
        self.bar1_enabled.setChecked(self.scale_bar.bar_1_individually_enabled)
        self.bar1_pixel_size.setValue(bar1.pixel_size)
        self.bar1_unit.setCurrentText(bar1.unit)
        self.bar1_position.setCurrentText(bar1.position)
        self.bar1_color.setCurrentText(bar1.color)
        self.bar1_width.setValue(int(bar1.bar_width_fraction * 100))
        self.bar1_offset.setValue(bar1.vertical_offset)
        
        # Scale Bar 2
        bar2 = self.scale_bar.scale_bar_2
        self.bar2_enabled.setChecked(self.scale_bar.bar_2_individually_enabled)
        self.bar2_pixel_size.setValue(bar2.pixel_size)
        self.bar2_unit.setCurrentText(bar2.unit)
        self.bar2_position.setCurrentText(bar2.position)
        self.bar2_color.setCurrentText(bar2.color)
        self.bar2_width.setValue(int(bar2.bar_width_fraction * 100))
        self.bar2_offset.setValue(bar2.vertical_offset)
    
    def _apply_bar_settings(self, bar_num: int):
        """Apply settings for a specific scale bar."""
        bar = self.scale_bar.get_scale_bar(bar_num)
        
        if bar_num == 1:
            enabled = self.bar1_enabled.isChecked()
            pixel_size = self.bar1_pixel_size.value()
            unit = self.bar1_unit.currentText()
            position = self.bar1_position.currentText()
            color = self.bar1_color.currentText()
            bar_width = self.bar1_width.value() / 100.0
            vertical_offset = self.bar1_offset.value()
            self.scale_bar.bar_1_individually_enabled = enabled
        else:
            enabled = self.bar2_enabled.isChecked()
            pixel_size = self.bar2_pixel_size.value()
            unit = self.bar2_unit.currentText()
            position = self.bar2_position.currentText()
            color = self.bar2_color.currentText()
            bar_width = self.bar2_width.value() / 100.0
            vertical_offset = self.bar2_offset.value()
            self.scale_bar.bar_2_individually_enabled = enabled
        
        # Apply settings
        bar.pixel_size = pixel_size
        bar.unit = unit
        bar.position = position
        bar.color = color
        bar.bar_width_fraction = bar_width
        bar.vertical_offset = vertical_offset
        
        # Update display if globally enabled and this bar is individually enabled
        if self.scale_bar._global_enabled and enabled:
            bar.enabled = True
            if self.scale_bar._last_image is not None:
                bar.update(self.scale_bar._last_image)
            bar.show()
        else:
            bar.enabled = False
            bar.hide()
        
        status = "enabled" if enabled else "disabled"
        QtWidgets.QMessageBox.information(self, "Settings Applied", 
                                         f"Scale bar {bar_num} {status} and settings updated!")
        
        if self.scale_bar.logger:
            self.scale_bar.logger.info(f"Scale bar {bar_num} updated: {pixel_size} {unit}/px, {status}")
    
    def _apply_all_settings(self):
        """Apply settings for both scale bars."""
        self._apply_bar_settings(1)
        self._apply_bar_settings(2)
        QtWidgets.QMessageBox.information(self, "Settings Applied", 
                                         "All scale bar settings updated!")