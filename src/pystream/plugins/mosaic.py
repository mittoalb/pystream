#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Camera Grid Stitching Plugin for PyQtGraph Viewer
"""

import os
import json
import time
import threading
import numpy as np
import pvaccess as pva
import epics

from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg


class CameraStitchPlugin(QtWidgets.QMainWindow):
    """Camera grid stitching plugin with live preview"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Grid Stitching")
        self.setGeometry(100, 100, 900, 700)
        
        self.config_file = "camera_stitch_config.json"
        self.config = self.load_config()
        
        # State
        self.acquiring = False
        self.stop_requested = False
        self.worker_thread = None
        self.stitched_u16 = None
        self.preview_image = None
        
        # Build UI
        self._build_ui()
        
        # Update info
        self.update_mode_info()
        
        # Auto-save on close
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QHBoxLayout(central)
        
        # Left panel: Controls
        left_panel = self._create_left_panel()
        left_panel.setMaximumWidth(450)
        main_layout.addWidget(left_panel)
        
        # Right panel: Preview
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, stretch=1)
        
        self._apply_style()
    
    def _create_left_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # Camera Parameters
        cam_group = QtWidgets.QGroupBox("Camera Parameters")
        cam_layout = QtWidgets.QFormLayout()
        
        self.pixel_size_entry = QtWidgets.QLineEdit(str(self.config.get("pixel_size", 1.0)))
        cam_layout.addRow("Pixel size (µm):", self.pixel_size_entry)
        
        cam_group.setLayout(cam_layout)
        layout.addWidget(cam_group)
        
        # Acquisition Mode
        mode_group = QtWidgets.QGroupBox("Acquisition Mode")
        mode_layout = QtWidgets.QVBoxLayout()
        
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mode:"))
        self.acq_mode_combo = QtWidgets.QComboBox()
        self.acq_mode_combo.addItems(["180", "360"])
        self.acq_mode_combo.setCurrentText(self.config.get("acq_mode", "180"))
        self.acq_mode_combo.currentTextChanged.connect(self.update_mode_info)
        mode_row.addWidget(self.acq_mode_combo)
        mode_row.addWidget(QtWidgets.QLabel("deg"))
        mode_row.addStretch()
        mode_layout.addLayout(mode_row)
        
        self.mode_info_label = QtWidgets.QLabel("Standard grid acquisition")
        self.mode_info_label.setStyleSheet("QLabel { color: #2980b9; font-size: 9pt; }")
        self.mode_info_label.setWordWrap(True)
        mode_layout.addWidget(self.mode_info_label)
        
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        # Grid Parameters
        grid_group = QtWidgets.QGroupBox("Grid Parameters")
        grid_layout = QtWidgets.QGridLayout()
        
        self.h_steps_entry = QtWidgets.QLineEdit(str(self.config.get("h_steps", 3)))
        self.v_steps_entry = QtWidgets.QLineEdit(str(self.config.get("v_steps", 3)))
        self.h_step_size_entry = QtWidgets.QLineEdit(str(self.config.get("h_step_size", 0.2)))
        self.v_step_size_entry = QtWidgets.QLineEdit(str(self.config.get("v_step_size", 0.2)))
        
        grid_layout.addWidget(QtWidgets.QLabel("Horizontal steps:"), 0, 0)
        grid_layout.addWidget(self.h_steps_entry, 0, 1)
        grid_layout.addWidget(QtWidgets.QLabel("H step size (mm):"), 0, 2)
        grid_layout.addWidget(self.h_step_size_entry, 0, 3)
        
        grid_layout.addWidget(QtWidgets.QLabel("Vertical steps:"), 1, 0)
        grid_layout.addWidget(self.v_steps_entry, 1, 1)
        grid_layout.addWidget(QtWidgets.QLabel("V step size (mm):"), 1, 2)
        grid_layout.addWidget(self.v_step_size_entry, 1, 3)
        
        self.overlap_label = QtWidgets.QLabel("Overlap: --")
        self.overlap_label.setStyleSheet("QLabel { color: #2980b9; font-weight: bold; }")
        grid_layout.addWidget(self.overlap_label, 2, 0, 1, 2)
        
        btn_calc = QtWidgets.QPushButton("Calculate Overlap")
        btn_calc.clicked.connect(self.calculate_overlap)
        grid_layout.addWidget(btn_calc, 2, 2, 1, 2)
        
        grid_group.setLayout(grid_layout)
        layout.addWidget(grid_group)
        
        # PVs
        pv_group = QtWidgets.QGroupBox("EPICS Process Variables")
        pv_layout = QtWidgets.QFormLayout()
        
        self.detector_entry = QtWidgets.QLineEdit(self.config.get("detector_pv", "32idbSP1:Pva1:Image"))
        self.size_x_entry = QtWidgets.QLineEdit(self.config.get("size_x_pv", "32idbSP1:cam1:ArraySizeX_RBV"))
        self.size_y_entry = QtWidgets.QLineEdit(self.config.get("size_y_pv", "32idbSP1:cam1:SizeY_RBV"))
        self.x_motor_entry = QtWidgets.QLineEdit(self.config.get("x_motor_pv", "32idbSP1:m1"))
        self.y_motor_entry = QtWidgets.QLineEdit(self.config.get("y_motor_pv", "32idbSP1:m2"))
        self.rotation_entry = QtWidgets.QLineEdit(self.config.get("rotation_pv", "32idbSP1:m3"))
        
        pv_layout.addRow("Detector PV:", self.detector_entry)
        pv_layout.addRow("Size X PV:", self.size_x_entry)
        pv_layout.addRow("Size Y PV:", self.size_y_entry)
        pv_layout.addRow("X Motor PV:", self.x_motor_entry)
        pv_layout.addRow("Y Motor PV:", self.y_motor_entry)
        pv_layout.addRow("Rotation PV:", self.rotation_entry)
        
        pv_group.setLayout(pv_layout)
        layout.addWidget(pv_group)
        
        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        
        self.btn_preview = QtWidgets.QPushButton("Start Preview")
        self.btn_preview.clicked.connect(self.start_preview)
        self.btn_preview.setStyleSheet("QPushButton { background-color: #f39c12; color: white; padding: 8px; }")
        btn_layout.addWidget(self.btn_preview)
        
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_acquisition)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("QPushButton { background-color: #e74c3c; color: white; padding: 8px; }")
        btn_layout.addWidget(self.btn_stop)
        
        btn_test = QtWidgets.QPushButton("Test Image")
        btn_test.clicked.connect(self.test_image)
        btn_layout.addWidget(btn_test)
        
        layout.addLayout(btn_layout)
        
        # Status
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("QLabel { background-color: #2d2d2d; padding: 6px; border: 1px solid #404040; }")
        layout.addWidget(self.status_label)
        
        # Progress
        self.progress_bar = QtWidgets.QProgressBar()
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        
        return panel
    
    def _create_right_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        
        # Image view
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        self.image_view.view.setMouseMode(pg.ViewBox.RectMode)
        layout.addWidget(self.image_view)
        
        # Contrast controls
        contrast_layout = QtWidgets.QHBoxLayout()
        
        self.chk_auto_contrast = QtWidgets.QCheckBox("Auto Contrast")
        self.chk_auto_contrast.setChecked(True)
        contrast_layout.addWidget(self.chk_auto_contrast)
        
        contrast_layout.addWidget(QtWidgets.QLabel("Low %:"))
        self.sld_low_pct = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_low_pct.setRange(0, 50)
        self.sld_low_pct.setValue(1)
        self.sld_low_pct.setMaximumWidth(150)
        contrast_layout.addWidget(self.sld_low_pct)
        
        contrast_layout.addWidget(QtWidgets.QLabel("High %:"))
        self.sld_high_pct = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_high_pct.setRange(50, 100)
        self.sld_high_pct.setValue(99)
        self.sld_high_pct.setMaximumWidth(150)
        contrast_layout.addWidget(self.sld_high_pct)
        
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_preview)
        contrast_layout.addWidget(btn_refresh)
        
        btn_save = QtWidgets.QPushButton("Save Image...")
        btn_save.clicked.connect(self.save_stitched_image)
        contrast_layout.addWidget(btn_save)
        
        contrast_layout.addStretch()
        
        layout.addLayout(contrast_layout)
        
        return panel
    
    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a1a;
                color: #e0e0e0;
            }
            QGroupBox {
                color: #e0e0e0;
                border: 1px solid #404040;
                border-radius: 5px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 4px;
                border: 1px solid #404040;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 6px 12px;
                border: 1px solid #404040;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                color: #666;
            }
            QComboBox {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 4px;
                border: 1px solid #404040;
                border-radius: 3px;
            }
        """)
    
    def update_mode_info(self):
        mode = self.acq_mode_combo.currentText()
        if mode == "180":
            self.mode_info_label.setText("Standard grid acquisition at current rotation")
        else:
            self.mode_info_label.setText("Double field of view: Grid doubled, half at 0°, half at 180°")
    
    def get_image_size(self):
        try:
            size_x = epics.caget(self.size_x_entry.text())
            size_y = epics.caget(self.size_y_entry.text())
            return int(size_y), int(size_x)
        except Exception:
            return 2426, 3232
    
    def calculate_overlap(self):
        try:
            pixel_size = float(self.pixel_size_entry.text())
            h_step_mm = float(self.h_step_size_entry.text())
            v_step_mm = float(self.v_step_size_entry.text())
            
            img_h, img_w = self.get_image_size()
            
            h_step_um = h_step_mm * 1000
            v_step_um = v_step_mm * 1000
            
            img_w_um = img_w * pixel_size
            img_h_um = img_h * pixel_size
            
            h_overlap = max(0, (img_w_um - h_step_um) / img_w_um)
            v_overlap = max(0, (img_h_um - v_step_um) / img_h_um)
            
            self.overlap_label.setText(f"Overlap: H: {h_overlap:.1%}, V: {v_overlap:.1%}")
            self.calculated_overlap = (h_overlap, v_overlap)
        except Exception:
            self.overlap_label.setText("Overlap: Error")
            self.calculated_overlap = (0.15, 0.15)
    
    def get_image(self):
        detector_pv = self.detector_entry.text()
        pv = pva.Channel(detector_pv)
        img_h, img_w = self.get_image_size()
        arr = pv.get()['value'][0]['ushortValue']
        return np.asarray(arr, dtype=np.uint16).reshape(img_h, img_w)
    
    def move_motors(self, x_pos, y_pos):
        x_motor = self.x_motor_entry.text()
        y_motor = self.y_motor_entry.text()
        epics.caput(x_motor, x_pos, wait=True)
        epics.caput(y_motor, y_pos, wait=True)
        time.sleep(0.1)
    
    def move_rotation(self, angle):
        rotation_pv = self.rotation_entry.text()
        epics.caput(rotation_pv, angle, wait=True)
        time.sleep(0.2)
    
    def test_image(self):
        try:
            self.status_label.setText("Acquiring test image...")
            QtWidgets.QApplication.processEvents()
            
            img = self.get_image()
            self.image_view.setImage(img, autoRange=True, autoLevels=True)
            
            self.status_label.setText("Test image displayed")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to acquire test image:\n{str(e)}")
            self.status_label.setText("Error")
    
    def start_preview(self):
        if self.acquiring:
            return
        
        try:
            h_steps = int(self.h_steps_entry.text())
            v_steps = int(self.v_steps_entry.text())
            h_step_size = float(self.h_step_size_entry.text())
            v_step_size = float(self.v_step_size_entry.text())
            
            if h_steps < 1 or v_steps < 1:
                raise ValueError("Steps must be >= 1")
        except ValueError as e:
            QtWidgets.QMessageBox.critical(self, "Input Error", str(e))
            return
        
        self.stop_requested = False
        self.btn_preview.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.worker_thread = threading.Thread(target=self.acquire_grid, daemon=True)
        self.worker_thread.start()
        
        # Start UI updater
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.refresh_preview)
        self.update_timer.start(100)
    
    def stop_acquisition(self):
        self.stop_requested = True
        self.status_label.setText("Stop requested...")
        self.btn_stop.setEnabled(False)
    
    def acquire_grid(self):
        try:
            self.acquiring = True
            
            h_steps = int(self.h_steps_entry.text())
            v_steps = int(self.v_steps_entry.text())
            h_step_size = float(self.h_step_size_entry.text())
            v_step_size = float(self.v_step_size_entry.text())
            acq_mode = self.acq_mode_combo.currentText()
            
            self.calculate_overlap()
            h_overlap, v_overlap = getattr(self, 'calculated_overlap', (0.15, 0.15))
            
            if acq_mode == "360":
                actual_h_steps = h_steps * 2
                actual_v_steps = v_steps
            else:
                actual_h_steps = h_steps
                actual_v_steps = v_steps
            
            total_images = h_steps * v_steps * (2 if acq_mode == "360" else 1)
            self.progress_bar.setMaximum(total_images)
            
            test_img = self.get_image()
            img_h, img_w = test_img.shape
            
            eff_h = int(img_h * (1 - v_overlap))
            eff_w = int(img_w * (1 - h_overlap))
            out_h = eff_h * actual_v_steps + int(img_h * v_overlap)
            out_w = eff_w * actual_h_steps + int(img_w * h_overlap)
            
            self.stitched_u16 = np.zeros((out_h, out_w), dtype=np.uint16)
            
            count = 0
            border_thick = 5
            
            if acq_mode == "360":
                for rot_idx, rotation in enumerate([0, 180]):
                    if self.stop_requested:
                        break
                    
                    self.status_label.setText(f"Moving to {rotation}° rotation...")
                    self.move_rotation(rotation)
                    
                    for i in range(v_steps):
                        for j in range(h_steps):
                            if self.stop_requested:
                                break
                            
                            count += 1
                            x_pos = j * h_step_size
                            y_pos = i * v_step_size
                            
                            self.status_label.setText(f"Image {count}/{total_images}: ({j+1},{i+1}) at {rotation}°")
                            
                            self.move_motors(x_pos, y_pos)
                            img = self.get_image()
                            
                            if rotation == 0:
                                big_i = i
                                big_j = j + h_steps
                            else:
                                big_i = i
                                big_j = (h_steps - 1 - j)
                            
                            start_y = big_i * eff_h
                            start_x = big_j * eff_w
                            end_y = min(start_y + img_h, out_h)
                            end_x = min(start_x + img_w, out_w)
                            
                            sub = img[:end_y-start_y, :end_x-start_x]
                            self.stitched_u16[start_y:end_y, start_x:end_x] = sub
                            
                            # Optional borders
                            try:
                                for t in range(border_thick):
                                    if start_y + t < end_y:
                                        self.stitched_u16[start_y + t, start_x:end_x] = np.max(sub)
                                    if end_y - 1 - t >= start_y:
                                        self.stitched_u16[end_y - 1 - t, start_x:end_x] = np.max(sub)
                                    if start_x + t < end_x:
                                        self.stitched_u16[start_y:end_y, start_x + t] = np.max(sub)
                                    if end_x - 1 - t >= start_x:
                                        self.stitched_u16[start_y:end_y, end_x - 1 - t] = np.max(sub)
                            except Exception:
                                pass
                            
                            self.progress_bar.setValue(count)
                        if self.stop_requested:
                            break
            else:
                for i in range(v_steps):
                    for j in range(h_steps):
                        if self.stop_requested:
                            break
                        
                        count += 1
                        x_pos = j * h_step_size
                        y_pos = i * v_step_size
                        
                        self.status_label.setText(f"Image {count}/{total_images}: ({j+1},{i+1})")
                        
                        self.move_motors(x_pos, y_pos)
                        img = self.get_image()
                        
                        start_y = i * eff_h
                        start_x = j * eff_w
                        end_y = min(start_y + img_h, out_h)
                        end_x = min(start_x + img_w, out_w)
                        
                        sub = img[:end_y-start_y, :end_x-start_x]
                        self.stitched_u16[start_y:end_y, start_x:end_x] = sub
                        
                        # Borders
                        try:
                            for t in range(border_thick):
                                if start_y + t < end_y:
                                    self.stitched_u16[start_y + t, start_x:end_x] = np.max(sub)
                                if end_y - 1 - t >= start_y:
                                    self.stitched_u16[end_y - 1 - t, start_x:end_x] = np.max(sub)
                                if start_x + t < end_x:
                                    self.stitched_u16[start_y:end_y, start_x + t] = np.max(sub)
                                if end_x - 1 - t >= start_x:
                                    self.stitched_u16[start_y:end_y, end_x - 1 - t] = np.max(sub)
                        except Exception:
                            pass
                        
                        self.progress_bar.setValue(count)
                    if self.stop_requested:
                        break
            
            self.status_label.setText(f"Complete! ({out_w}x{out_h}) - {acq_mode}° mode")
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Acquisition Error", str(e))
            self.status_label.setText("Error")
        finally:
            self.acquiring = False
            self.stop_requested = False
            self.btn_preview.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.progress_bar.setValue(0)
            if hasattr(self, 'update_timer'):
                self.update_timer.stop()
    
    def refresh_preview(self):
        if self.stitched_u16 is None:
            return
        
        try:
            img = self.stitched_u16
            auto_contrast = self.chk_auto_contrast.isChecked()
            
            if auto_contrast:
                vmin, vmax = np.percentile(img[img > 0], [1, 99]) if np.any(img > 0) else (0, 65535)
            else:
                low_pct = self.sld_low_pct.value()
                high_pct = self.sld_high_pct.value()
                vmin = np.percentile(img[img > 0], low_pct) if np.any(img > 0) else 0
                vmax = np.percentile(img[img > 0], high_pct) if np.any(img > 0) else 65535
            
            self.image_view.setImage(img, autoRange=False, autoLevels=False, levels=(vmin, vmax))
        except Exception:
            pass
    
    def save_stitched_image(self):
        if self.stitched_u16 is None:
            QtWidgets.QMessageBox.warning(self, "No Image", "No stitched image to save")
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Stitched Image", "", 
            "NumPy Array (*.npy);;Text File (*.txt);;All Files (*)"
        )
        
        if not path:
            return
        
        try:
            if path.endswith('.npy'):
                np.save(path, self.stitched_u16)
            else:
                np.savetxt(path, self.stitched_u16, fmt='%d', delimiter='\t')
            
            QtWidgets.QMessageBox.information(self, "Saved", f"Saved to:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Error", f"Failed to save:\n{str(e)}")
    
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def save_config(self):
        config = {
            "detector_pv": self.detector_entry.text(),
            "size_x_pv": self.size_x_entry.text(),
            "size_y_pv": self.size_y_entry.text(),
            "x_motor_pv": self.x_motor_entry.text(),
            "y_motor_pv": self.y_motor_entry.text(),
            "rotation_pv": self.rotation_entry.text(),
            "pixel_size": float(self.pixel_size_entry.text() or 1.0),
            "acq_mode": self.acq_mode_combo.currentText(),
            "h_steps": int(self.h_steps_entry.text() or 3),
            "v_steps": int(self.v_steps_entry.text() or 3),
            "h_step_size": float(self.h_step_size_entry.text() or 0.2),
            "v_step_size": float(self.v_step_size_entry.text() or 0.2)
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception:
            pass
    
    def closeEvent(self, event):
        self.save_config()
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        event.accept()


# Standalone test
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = CameraStitchPlugin()
    window.show()
    sys.exit(app.exec_())