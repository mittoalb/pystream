#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HDF5 Image Divider Plugin for PyQtGraph
----------------------------------------
Opens HDF5 files virtually and displays the division of two image datasets.
Allows real-time shifting of the second image using keyboard arrows.
Includes slider to select which image index to view.

Structure expected:
- /exchange/data (array of projections - first image)
- /exchange/data_white (array of images - second image)

Shows: data / data_white with real-time shift adjustment
"""

import h5py
import numpy as np
from typing import Optional
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
pg.setConfigOptions(imageAxisOrder='row-major')


class HDF5ImageDividerDialog(QtWidgets.QDialog):
    """Dialog for viewing HDF5 image division with real-time shifting"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hdf5_file = None
        self.data_dataset = None
        self.data_white_dataset = None
        
        # Current state
        self.current_index = 0
        self.shift_x = 0
        self.shift_y = 0
        self.normalization_enabled = True
        
        # Cached images
        self.current_data = None
        self.current_white = None
        self.result_image = None
        
        self.setWindowTitle("HDF5 Image Divider")
        self.setModal(False)
        self.resize(1400, 900)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface"""
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Left panel - Controls
        left_panel = QtWidgets.QWidget()
        left_panel.setMaximumWidth(350)
        layout = QtWidgets.QVBoxLayout(left_panel)
        layout.setSpacing(10)
        
        # Title
        title = QtWidgets.QLabel("IMG Data Viewer")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # File selection group
        file_group = QtWidgets.QGroupBox("File Selection")
        file_layout = QtWidgets.QVBoxLayout()
        
        self.file_path_label = QtWidgets.QLabel("No file loaded")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setStyleSheet("color: #999;")
        file_layout.addWidget(self.file_path_label)
        
        load_btn = QtWidgets.QPushButton("Load HDF5 File")
        load_btn.clicked.connect(self._load_file)
        file_layout.addWidget(load_btn)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Dataset info group
        info_group = QtWidgets.QGroupBox("Dataset Information")
        info_layout = QtWidgets.QFormLayout()
        
        self.data_shape_label = QtWidgets.QLabel("N/A")
        self.white_shape_label = QtWidgets.QLabel("N/A")
        self.num_images_label = QtWidgets.QLabel("N/A")
        
        info_layout.addRow("Data shape:", self.data_shape_label)
        info_layout.addRow("White shape:", self.white_shape_label)
        info_layout.addRow("Number of images:", self.num_images_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Image selection group
        selection_group = QtWidgets.QGroupBox("Image Selection")
        selection_layout = QtWidgets.QVBoxLayout()
        
        # Slider for image index
        slider_layout = QtWidgets.QHBoxLayout()
        slider_layout.addWidget(QtWidgets.QLabel("Image Index:"))
        
        self.index_label = QtWidgets.QLabel("0")
        self.index_label.setMinimumWidth(50)
        self.index_label.setStyleSheet("font-weight: bold;")
        slider_layout.addWidget(self.index_label)
        
        selection_layout.addLayout(slider_layout)
        
        self.image_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.image_slider.setMinimum(0)
        self.image_slider.setMaximum(0)
        self.image_slider.setValue(0)
        self.image_slider.setEnabled(False)
        self.image_slider.valueChanged.connect(self._on_slider_changed)
        selection_layout.addWidget(self.image_slider)
        
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)
        
        # Normalization control group
        norm_group = QtWidgets.QGroupBox("Normalization")
        norm_layout = QtWidgets.QVBoxLayout()
        
        self.normalization_checkbox = QtWidgets.QCheckBox("Enable Normalization (data / data_white)")
        self.normalization_checkbox.setChecked(True)
        self.normalization_checkbox.stateChanged.connect(self._on_normalization_changed)
        norm_layout.addWidget(self.normalization_checkbox)
        
        self.mode_label = QtWidgets.QLabel("Mode: <b>Division</b>")
        self.mode_label.setStyleSheet("padding: 5px; background-color: #2a2a2a; border-radius: 3px;")
        norm_layout.addWidget(self.mode_label)
        
        norm_group.setLayout(norm_layout)
        layout.addWidget(norm_group)
        
        # Shift control group
        shift_group = QtWidgets.QGroupBox("Shift Control")
        shift_layout = QtWidgets.QFormLayout()
        
        self.shift_x_label = QtWidgets.QLabel("0")
        self.shift_x_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("X Shift (pixels):", self.shift_x_label)
        
        self.shift_y_label = QtWidgets.QLabel("0")
        self.shift_y_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("Y Shift (pixels):", self.shift_y_label)
        
        # Reset button
        reset_btn = QtWidgets.QPushButton("Reset Shift")
        reset_btn.clicked.connect(self._reset_shift)
        shift_layout.addRow("", reset_btn)
        
        # Instructions
        self.shift_instructions = QtWidgets.QLabel(
            "<b>Keyboard Controls:</b><br>"
            "← → ↑ ↓: Shift image by 1 pixel<br>"
            "Shift + arrows: Shift by 10 pixels<br>"
            "Ctrl + arrows: Shift by 50 pixels"
        )
        self.shift_instructions.setWordWrap(True)
        self.shift_instructions.setStyleSheet("padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
        shift_layout.addRow(self.shift_instructions)
        
        shift_group.setLayout(shift_layout)
        layout.addWidget(shift_group)
        
        # Image statistics group
        stats_group = QtWidgets.QGroupBox("Image Statistics")
        stats_layout = QtWidgets.QFormLayout()
        
        self.min_val_label = QtWidgets.QLabel("N/A")
        self.max_val_label = QtWidgets.QLabel("N/A")
        self.mean_val_label = QtWidgets.QLabel("N/A")
        
        stats_layout.addRow("Min value:", self.min_val_label)
        stats_layout.addRow("Max value:", self.max_val_label)
        stats_layout.addRow("Mean value:", self.mean_val_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Stretch to push everything to the top
        layout.addStretch()
        
        # Close button
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        main_layout.addWidget(left_panel)
        
        # Right panel - Image display
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setSpacing(5)
        
        # Image viewer
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        right_layout.addWidget(self.image_view)
        
        # Status bar
        self.status_label = QtWidgets.QLabel("Load an HDF5 file to begin")
        self.status_label.setStyleSheet(
            "padding: 5px; background-color: #2a2a2a; border-radius: 3px;"
        )
        right_layout.addWidget(self.status_label)
        
        main_layout.addWidget(right_panel, stretch=1)
        
        # Set focus policy to receive keyboard events
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
    
    def _load_file(self):
        """Open file dialog and load HDF5 file"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select HDF5 File",
            "",
            "HDF5 Files (*.h5 *.hdf5);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Close previous file if open
            if self.hdf5_file is not None:
                self.hdf5_file.close()
            
            # Open file in read-only mode (virtual access)
            self.hdf5_file = h5py.File(file_path, 'r')
            
            # Access datasets (virtual - no data loaded yet)
            if '/exchange/data' not in self.hdf5_file:
                raise ValueError("Dataset '/exchange/data' not found in file")
            if '/exchange/data_white' not in self.hdf5_file:
                raise ValueError("Dataset '/exchange/data_white' not found in file")
            
            self.data_dataset = self.hdf5_file['/exchange/data']
            self.data_white_dataset = self.hdf5_file['/exchange/data_white']
            
            # Validate shapes
            if len(self.data_dataset.shape) < 3:
                raise ValueError("Data dataset must have at least 3 dimensions")
            if len(self.data_white_dataset.shape) < 3:
                raise ValueError("Data_white dataset must have at least 3 dimensions")
            
            # Update UI
            self.file_path_label.setText(file_path.split('/')[-1])
            self.file_path_label.setStyleSheet("color: white;")
            
            self.data_shape_label.setText(str(self.data_dataset.shape))
            self.white_shape_label.setText(str(self.data_white_dataset.shape))
            
            num_images = max(self.data_dataset.shape[0], self.data_white_dataset.shape[0])
            self.num_images_label.setText(str(num_images))
            
            # Setup slider
            self.image_slider.setMaximum(num_images - 1)
            self.image_slider.setEnabled(True)
            self.image_slider.setValue(0)
            
            # Reset shift
            self.shift_x = 0
            self.shift_y = 0
            self._update_shift_labels()
            
            # Load first image
            self._load_and_display_image(0)
            
            self.status_label.setText(f"Loaded: {num_images} images. Use slider to navigate, arrows to shift.")
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error Loading File",
                f"Failed to load HDF5 file:\n{str(e)}"
            )
            self.status_label.setText(f"Error: {str(e)}")
    
    def _load_and_display_image(self, index):
        """Load a single image from both datasets and display the division"""
        if self.data_dataset is None or self.data_white_dataset is None:
            return
        
        try:
            # Load only the specific slice (virtual loading)
            self.current_data = self.data_dataset[index, :, :].astype(np.float32)
            self.current_white = self.data_white_dataset[0, :, :].astype(np.float32)
            
            self.current_index = index
            self.index_label.setText(str(index))
            
            # Update display with current shift
            self._update_display()
            
        except Exception as e:
            self.status_label.setText(f"Error loading image {index}: {str(e)}")
    
    def _update_display(self):
        """Update the display with current shift applied"""
        if self.current_data is None or self.current_white is None:
            return
        
        try:
            if self.normalization_enabled:
                # Apply shift to white image
                shifted_white = self._apply_shift(self.current_white, self.shift_x, self.shift_y)
                
                # Perform division (avoid division by zero)
                with np.errstate(divide='ignore', invalid='ignore'):
                    result = np.divide(self.current_data, shifted_white)
                    result[~np.isfinite(result)] = 0  # Replace inf/nan with 0
                
                self.result_image = result
            else:
                # Just show the raw data image (no normalization)
                result = self.current_data
                self.result_image = result
            
            # Update display
            self.image_view.setImage(result, autoRange=False, autoLevels=False, autoHistogramRange=True)
            
            # Update statistics
            self.min_val_label.setText(f"{np.min(result):.4f}")
            self.max_val_label.setText(f"{np.max(result):.4f}")
            self.mean_val_label.setText(f"{np.mean(result):.4f}")
            
            if self.normalization_enabled:
                self.status_label.setText(
                    f"Image {self.current_index} | Shift: ({self.shift_x}, {self.shift_y}) | Mode: Division"
                )
            else:
                self.status_label.setText(
                    f"Image {self.current_index} | Mode: Raw Data (no normalization)"
                )
            
        except Exception as e:
            self.status_label.setText(f"Error updating display: {str(e)}")
    
    def _apply_shift(self, image, shift_x, shift_y):
        """Apply x and y shift to an image"""
        if shift_x == 0 and shift_y == 0:
            return image
        
        # Create shifted image
        shifted = np.zeros_like(image)
        
        # Calculate source and destination regions
        src_x_start = max(0, -shift_x)
        src_x_end = image.shape[1] - max(0, shift_x)
        src_y_start = max(0, -shift_y)
        src_y_end = image.shape[0] - max(0, shift_y)
        
        dst_x_start = max(0, shift_x)
        dst_x_end = image.shape[1] - max(0, -shift_x)
        dst_y_start = max(0, shift_y)
        dst_y_end = image.shape[0] - max(0, -shift_y)
        
        # Copy shifted data
        shifted[dst_y_start:dst_y_end, dst_x_start:dst_x_end] = \
            image[src_y_start:src_y_end, src_x_start:src_x_end]
        
        return shifted
    
    def _on_slider_changed(self, value):
        """Handle slider value change"""
        self._load_and_display_image(value)
    
    def _on_normalization_changed(self, state):
        """Handle normalization checkbox change"""
        self.normalization_enabled = (state == QtCore.Qt.Checked)
        
        # Update mode label
        if self.normalization_enabled:
            self.mode_label.setText("Mode: <b>Division (data / data_white)</b>")
        else:
            self.mode_label.setText("Mode: <b>Raw Data Only</b>")
        
        # Update display
        self._update_display()
    
    def _reset_shift(self):
        """Reset shift to zero"""
        self.shift_x = 0
        self.shift_y = 0
        self._update_shift_labels()
        self._update_display()
    
    def _update_shift_labels(self):
        """Update shift labels"""
        self.shift_x_label.setText(str(self.shift_x))
        self.shift_y_label.setText(str(self.shift_y))
    
    def keyPressEvent(self, event):
        """Handle keyboard events for shifting"""
        if self.current_data is None:
            return
        
        # Only allow shifting when normalization is enabled
        if not self.normalization_enabled:
            super().keyPressEvent(event)
            return
        
        # Determine step size based on modifiers
        step = 1
        if event.modifiers() & QtCore.Qt.ShiftModifier:
            step = 10
        elif event.modifiers() & QtCore.Qt.ControlModifier:
            step = 50
        
        # Handle arrow keys
        if event.key() == QtCore.Qt.Key_Left:
            self.shift_x -= step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Right:
            self.shift_x += step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Up:
            self.shift_y -= step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Down:
            self.shift_y += step
            self._update_shift_labels()
            self._update_display()
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Clean up when closing"""
        if self.hdf5_file is not None:
            self.hdf5_file.close()
        super().closeEvent(event)


# ==================== Standalone Mode ====================
def main():
    """Run the HDF5 image divider as a standalone application"""
    import sys
    
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("HDF5 Image Divider")
    
    # Apply dark theme (similar to reference)
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor(127, 127, 127))
    
    app.setPalette(palette)
    
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            font-weight: bold;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #2a2a2a;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 3px;
            min-height: 20px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
            border: 1px solid #2a82da;
        }
        QPushButton {
            background-color: #454545;
            border: 1px solid #666;
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #505050;
            border: 1px solid #888;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:disabled {
            background-color: #353535;
            color: #666;
        }
        QSlider::groove:horizontal {
            border: 1px solid #555;
            height: 8px;
            background: #2a2a2a;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #2a82da;
            border: 1px solid #3a95d8;
            width: 18px;
            margin: -5px 0;
            border-radius: 9px;
        }
        QSlider::handle:horizontal:hover {
            background: #3a95d8;
        }
    """)
    
    dialog = HDF5ImageDividerDialog()
    dialog.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()