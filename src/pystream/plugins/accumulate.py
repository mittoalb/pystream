#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frame Accumulator Plugin for PyQtGraph Viewer
----------------------------------------------
Accumulates/sums frames from the main viewer in real-time.
- Start/Stop/Reset controls
- Shows accumulated sum and frame count
- Real-time display updates
"""

import logging
import numpy as np
from typing import Optional
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg


class FrameAccumulatorDialog(QtWidgets.QDialog):
    """Dialog for accumulating frames in real-time"""
    
    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        
        # State
        self.accumulating = False
        self.accumulated_image = None
        self.frame_count = 0
        
        # Thread lock for accumulated image
        self.accum_lock = QtCore.QMutex()
        
        self.setWindowTitle("Frame Accumulator")
        self.setModal(False)
        self.resize(900, 700)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface"""
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Left panel - Controls
        left_panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left_panel)
        layout.setSpacing(10)
        
        # Title
        title = QtWidgets.QLabel("Frame Accumulator")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Control buttons
        control_group = QtWidgets.QGroupBox("Control")
        control_layout = QtWidgets.QVBoxLayout()
        
        btn_layout = QtWidgets.QHBoxLayout()
        
        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.clicked.connect(self._start_accumulation)
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_accumulation)
        btn_layout.addWidget(self.stop_btn)
        
        control_layout.addLayout(btn_layout)
        
        self.reset_btn = QtWidgets.QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset_accumulation)
        control_layout.addWidget(self.reset_btn)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # Statistics
        stats_group = QtWidgets.QGroupBox("Statistics")
        stats_layout = QtWidgets.QFormLayout()
        
        self.frame_count_label = QtWidgets.QLabel("0")
        self.frame_count_label.setStyleSheet("font-weight: bold; font-size: 20px;")
        stats_layout.addRow("Frames:", self.frame_count_label)
        
        self.status_label = QtWidgets.QLabel("Idle")
        stats_layout.addRow("Status:", self.status_label)
        
        self.sum_range_label = QtWidgets.QLabel("—")
        stats_layout.addRow("Sum Range:", self.sum_range_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Save options
        save_group = QtWidgets.QGroupBox("Save Accumulated Image")
        save_layout = QtWidgets.QVBoxLayout()
        
        self.save_btn = QtWidgets.QPushButton("Save as NumPy (.npy)")
        self.save_btn.clicked.connect(self._save_accumulated)
        save_layout.addWidget(self.save_btn)
        
        save_group.setLayout(save_layout)
        layout.addWidget(save_group)
        
        # Log output
        log_group = QtWidgets.QGroupBox("Log")
        log_layout = QtWidgets.QVBoxLayout()
        
        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        log_layout.addWidget(self.log_output)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
        
        # Right panel - Image display
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        
        display_title = QtWidgets.QLabel("Accumulated Image")
        display_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        right_layout.addWidget(display_title)
        
        self.graphics_view = pg.GraphicsLayoutWidget()
        self.plot_item = self.graphics_view.addPlot()
        self.image_item = pg.ImageItem()
        self.plot_item.addItem(self.image_item)
        self.plot_item.setAspectLocked(True)
        
        # Add colorbar
        self.colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=pg.colormap.get('viridis')
        )
        self.colorbar.setImageItem(self.image_item)
        
        right_layout.addWidget(self.graphics_view)
        
        # Add panels to main layout
        left_panel.setMaximumWidth(350)
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        main_layout.setStretch(1, 1)
    
    def _log(self, message: str):
        """Add message to log"""
        import time
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        if self.logger:
            self.logger.info(f"[FrameAccumulator] {message}")
    
    def _start_accumulation(self):
        """Start accumulating frames"""
        self.accumulating = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Accumulating...")
        self.status_label.setStyleSheet("color: #0a0; font-weight: bold;")
        self._log("Started accumulation")
    
    def _stop_accumulation(self):
        """Stop accumulating frames"""
        self.accumulating = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet("color: #fa0; font-weight: bold;")
        self._log(f"Stopped accumulation at {self.frame_count} frames")
    
    def _reset_accumulation(self):
        """Reset accumulated data"""
        self.accum_lock.lock()
        try:
            self.accumulated_image = None
            self.frame_count = 0
            self.frame_count_label.setText("0")
            self.sum_range_label.setText("—")
            self.image_item.clear()
            self.status_label.setText("Reset - Ready")
            self.status_label.setStyleSheet("color: #888;")
            self._log("Reset accumulation")
        finally:
            self.accum_lock.unlock()
    
    def add_frame(self, img: np.ndarray):
        """
        Called by parent to add a new frame to accumulation.
        This is the public interface for the main viewer.
        """
        if not self.accumulating:
            return
        
        if img is None:
            return
        
        self.accum_lock.lock()
        try:
            # Initialize accumulated image on first frame
            if self.accumulated_image is None:
                self.accumulated_image = img.astype(np.float64)
                self.frame_count = 1
            else:
                # Add new frame to accumulation
                self.accumulated_image += img.astype(np.float64)
                self.frame_count += 1
            
            # Update display
            display_img = self.accumulated_image.copy()
            
            # Update UI
            self.frame_count_label.setText(str(self.frame_count))
            self.sum_range_label.setText(f"{display_img.min():.0f} — {display_img.max():.0f}")
            
            # Update image with auto-levels on first frame, then manual
            if self.frame_count == 1:
                self.image_item.setImage(display_img.T, autoLevels=True)
            else:
                self.image_item.setImage(display_img.T, autoLevels=False)
            
            if self.frame_count % 10 == 0:
                self._log(f"Accumulated {self.frame_count} frames")
        
        finally:
            self.accum_lock.unlock()
    
    def _save_accumulated(self):
        """Save the accumulated image"""
        if self.accumulated_image is None:
            QtWidgets.QMessageBox.information(
                self, "Save Accumulated", 
                "No accumulated image to save yet."
            )
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Accumulated Image", 
            f"accumulated_{self.frame_count}_frames.npy",
            "NumPy Array (*.npy);;All Files (*)"
        )
        
        if not path:
            return
        
        try:
            self.accum_lock.lock()
            try:
                np.save(path, self.accumulated_image)
            finally:
                self.accum_lock.unlock()
            
            self._log(f"Saved {self.frame_count} frame accumulation to {path}")
            QtWidgets.QMessageBox.information(
                self, "Save Accumulated", 
                f"Successfully saved accumulated image\n"
                f"({self.frame_count} frames) to:\n\n{path}"
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save accumulated image: {e}")
            QtWidgets.QMessageBox.critical(
                self, "Save Accumulated", 
                f"Failed to save:\n{e}"
            )
    
    def closeEvent(self, event):
        """Clean up when dialog is closed"""
        if self.accumulating:
            reply = QtWidgets.QMessageBox.question(
                self, "Accumulation Active",
                f"Accumulation is active with {self.frame_count} frames.\n"
                f"Stop accumulation before closing?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel
            )
            
            if reply == QtWidgets.QMessageBox.Cancel:
                event.ignore()
                return
            else:
                self._stop_accumulation()
        
        event.accept()


# For standalone testing
if __name__ == '__main__':
    import sys
    from PyQt5 import QtGui
    
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Frame Accumulator")
    
    # Apply dark theme to match pystream
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    app.setPalette(palette)
    
    dialog = FrameAccumulatorDialog()
    dialog.show()
    
    # Simulate some frames for testing
    timer = QtCore.QTimer()
    frame_num = [0]
    def add_test_frame():
        frame_num[0] += 1
        test_img = np.random.randint(0, 100, (512, 512), dtype=np.uint16)
        dialog.add_frame(test_img)
    
    timer.timeout.connect(add_test_frame)
    timer.start(100)  # Add frame every 100ms
    
    sys.exit(app.exec_())