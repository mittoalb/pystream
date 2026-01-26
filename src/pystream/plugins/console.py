#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interactive Python Console Plugin for Real-time Stream Processing

Allows users to define custom processing functions that operate on the 
image stream in real-time, just before visualization.
"""

import logging
from typing import Optional, Callable
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt


class PythonConsole(QtWidgets.QWidget):
    """
    Embedded Python console with:
    - Code editor for writing processing functions
    - Execute button to compile and apply
    - Real-time error display
    - Access to numpy, scipy, cv2, etc.
    """
    
    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger

        self.process_func: Optional[Callable] = None
        self.enabled = False
        self.user_namespace = {}  # Store full namespace for calling user functions

        self._build_ui()
        self._set_default_template()
    
    def _build_ui(self):
        """Build the console UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Title bar with enable checkbox
        title_bar = QtWidgets.QHBoxLayout()
        title_label = QtWidgets.QLabel("<b>Python Console - Real-time Processing</b>")
        title_bar.addWidget(title_label)
        
        self.chk_enable = QtWidgets.QCheckBox("Enable")
        self.chk_enable.setChecked(False)
        self.chk_enable.stateChanged.connect(self._toggle_enabled)
        title_bar.addWidget(self.chk_enable)
        
        title_bar.addStretch()
        layout.addLayout(title_bar)
        
        # Instructions
        info_label = QtWidgets.QLabel(
            "Write a function that processes each frame before visualization.\n"
            "Function signature: def process(img: np.ndarray) -> np.ndarray"
        )
        info_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(info_label)
        
        # Code editor
        editor_label = QtWidgets.QLabel("Code Editor:")
        layout.addWidget(editor_label)
        
        self.code_editor = QtWidgets.QPlainTextEdit()
        self.code_editor.setFont(QtGui.QFont("Courier", 10))
        self.code_editor.setMinimumHeight(300)
        self.code_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.code_editor, stretch=1)
        
        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        
        btn_execute = QtWidgets.QPushButton("Execute (Compile)")
        btn_execute.clicked.connect(self._execute_code)
        btn_execute.setToolTip("Compile and activate the processing function")
        btn_layout.addWidget(btn_execute)
        
        btn_reset = QtWidgets.QPushButton("Reset to Default")
        btn_reset.clicked.connect(self._set_default_template)
        btn_layout.addWidget(btn_reset)
        
        btn_clear = QtWidgets.QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_function)
        btn_layout.addWidget(btn_clear)

        btn_load = QtWidgets.QPushButton("Load...")
        btn_load.clicked.connect(self._load_from_file)
        btn_load.setToolTip("Load Python code from file")
        btn_layout.addWidget(btn_load)

        btn_save = QtWidgets.QPushButton("Save...")
        btn_save.clicked.connect(self._save_to_file)
        btn_save.setToolTip("Save Python code to file")
        btn_layout.addWidget(btn_save)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Command input for calling functions
        cmd_layout = QtWidgets.QHBoxLayout()
        cmd_label = QtWidgets.QLabel("Command:")
        cmd_layout.addWidget(cmd_label)

        self.cmd_input = QtWidgets.QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command, e.g. c1() or diff()")
        self.cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                font-family: monospace;
            }
        """)
        self.cmd_input.returnPressed.connect(self._run_command)
        cmd_layout.addWidget(self.cmd_input)

        btn_run = QtWidgets.QPushButton("Run")
        btn_run.clicked.connect(self._run_command)
        btn_run.setMaximumWidth(60)
        cmd_layout.addWidget(btn_run)

        layout.addLayout(cmd_layout)

        # Status/error display
        status_label = QtWidgets.QLabel("Output:")
        layout.addWidget(status_label)

        self.status_display = QtWidgets.QTextEdit()
        self.status_display.setReadOnly(True)
        self.status_display.setMaximumHeight(150)
        self.status_display.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #00ff00;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 5px;
                font-family: monospace;
            }
        """)
        layout.addWidget(self.status_display)

        self._log_status("Console ready. Write your code and click 'Execute'.")
    
    def _set_default_template(self):
        """Set default processing template"""
        default_code = """# Real-time image processing function
# Available imports: numpy as np, scipy, cv2 (if installed)
# 
# Write your processing function below.
# It will be called on each frame before visualization.

def process(img):
    \"\"\"
    Process incoming image frame.
    
    Args:
        img: numpy array (2D grayscale or 3D RGB)
    
    Returns:
        processed numpy array
    \"\"\"
    # Example: Simple Gaussian blur
    # from scipy.ndimage import gaussian_filter
    # return gaussian_filter(img, sigma=2.0)
    
    # Example: Median filter
    # from scipy.ndimage import median_filter
    # return median_filter(img, size=3)
    
    # Example: Edge detection
    # from scipy.ndimage import sobel
    # sx = sobel(img, axis=0)
    # sy = sobel(img, axis=1)
    # return np.hypot(sx, sy)
    
    # Example: Simple threshold
    # return np.where(img > img.mean(), img, 0)
    
    # Pass through (no processing)
    return img
"""
        self.code_editor.setPlainText(default_code)
        self._log_status("Default template loaded.")
    
    def _toggle_enabled(self, state):
        """Enable or disable real-time processing"""
        self.enabled = (state == Qt.Checked)
        if self.enabled:
            if self.process_func is None:
                self._log_status("⚠ Processing enabled but no function compiled. Click 'Execute' first.", error=True)
            else:
                self._log_status("✓ Real-time processing ENABLED")
                if self.logger:
                    self.logger.info("Console processing enabled")
        else:
            self._log_status("Real-time processing DISABLED")
            if self.logger:
                self.logger.info("Console processing disabled")
    
    def _execute_code(self):
        """Compile and activate the user's processing function"""
        code = self.code_editor.toPlainText()

        if not code.strip():
            self._log_status("⚠ No code to execute", error=True)
            return

        try:
            namespace = {
                'np': np,
                'numpy': np,
            }

            try:
                import scipy
                import scipy.ndimage
                namespace['scipy'] = scipy
            except ImportError:
                pass

            try:
                import cv2
                namespace['cv2'] = cv2
            except ImportError:
                pass

            try:
                import skimage
                namespace['skimage'] = skimage
            except ImportError:
                pass

            exec(code, namespace)

            if 'process' not in namespace:
                self._log_status("⚠ ERROR: No 'process' function found in code", error=True)
                return

            self.process_func = namespace['process']

            try:
                test_img = np.random.rand(10, 10).astype(np.float32)
                result = self.process_func(test_img)
                if not isinstance(result, np.ndarray):
                    self._log_status("⚠ ERROR: process() must return a numpy array", error=True)
                    self.process_func = None
                    return
            except Exception as e:
                self._log_status(f"⚠ ERROR testing function: {str(e)}", error=True)
                self.process_func = None
                if self.logger:
                    self.logger.error("Console function test failed: %s", e)
                return

            # Store full namespace for running commands
            self.user_namespace = namespace

            # List available functions for user
            user_funcs = [k for k, v in namespace.items()
                         if callable(v) and not k.startswith('_') and k != 'process']

            msg = "✓ Function compiled successfully!\n"
            msg += "Enable the checkbox to activate real-time processing."
            if user_funcs:
                msg += f"\n\nAvailable commands: {', '.join(user_funcs)}"
            self._log_status(msg)
            
            if self.logger:
                self.logger.info("Console processing function compiled successfully")
        
        except Exception as e:
            self._log_status(f"⚠ COMPILATION ERROR:\n{str(e)}", error=True)
            self.process_func = None
            if self.logger:
                self.logger.error("Console code compilation failed: %s", e)
    
    def _run_command(self):
        """Execute a command in the user namespace."""
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return

        if not self.user_namespace:
            self._log_status("⚠ No code compiled yet. Click 'Execute' first.", error=True)
            return

        # Capture print output
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()

        try:
            # Execute the command in user namespace
            result = eval(cmd, self.user_namespace)
            output = captured.getvalue()

            if output:
                self._log_status(output.strip())
            if result is not None:
                self._log_status(f">>> {cmd}\n{result}")
            elif not output:
                self._log_status(f">>> {cmd}\nOK")

        except SyntaxError:
            # Try exec for statements
            try:
                exec(cmd, self.user_namespace)
                output = captured.getvalue()
                if output:
                    self._log_status(output.strip())
                else:
                    self._log_status(f">>> {cmd}\nOK")
            except Exception as e:
                self._log_status(f"⚠ ERROR: {e}", error=True)
        except Exception as e:
            self._log_status(f"⚠ ERROR: {e}", error=True)
        finally:
            sys.stdout = old_stdout

        self.cmd_input.clear()

    def _clear_function(self):
        """Clear the processing function"""
        self.process_func = None
        self.chk_enable.setChecked(False)
        self.enabled = False
        self._log_status("Function cleared.")

    def _load_from_file(self):
        """Load Python code from a file"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Python File",
            "",
            "Python Files (*.py);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()

            self.code_editor.setPlainText(code)
            self._log_status(f"✓ Loaded code from: {file_path}")

            if self.logger:
                self.logger.info(f"Loaded console code from {file_path}")

        except Exception as e:
            self._log_status(f"⚠ ERROR loading file: {str(e)}", error=True)
            if self.logger:
                self.logger.error(f"Failed to load file {file_path}: {e}")

    def _save_to_file(self):
        """Save Python code to a file"""
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Python File",
            "",
            "Python Files (*.py);;All Files (*)"
        )

        if not file_path:
            return

        if not file_path.endswith('.py'):
            file_path += '.py'

        try:
            code = self.code_editor.toPlainText()

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)

            self._log_status(f"✓ Saved code to: {file_path}")

            if self.logger:
                self.logger.info(f"Saved console code to {file_path}")

        except Exception as e:
            self._log_status(f"⚠ ERROR saving file: {str(e)}", error=True)
            if self.logger:
                self.logger.error(f"Failed to save file {file_path}: {e}")
    
    def _log_status(self, message: str, error: bool = False):
        """Log message to status display"""
        if error:
            color = "#ff4444"
        else:
            color = "#00ff00"
        
        self.status_display.setTextColor(QtGui.QColor(color))
        self.status_display.append(f"[{QtCore.QTime.currentTime().toString()}] {message}")
        
        # Auto-scroll to bottom
        cursor = self.status_display.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.status_display.setTextCursor(cursor)
    
    def process_image(self, img: np.ndarray) -> np.ndarray:
        """
        Process an image through the user's function.
        
        Args:
            img: Input image
        
        Returns:
            Processed image (or original if processing disabled/failed)
        """
        if not self.enabled or self.process_func is None:
            return img
        
        try:
            result = self.process_func(img)

            if not isinstance(result, np.ndarray):
                self._log_status("⚠ Function returned non-array. Disabling.", error=True)
                self.enabled = False
                self.chk_enable.setChecked(False)
                return img

            return result
        
        except Exception as e:
            self._log_status(f"⚠ RUNTIME ERROR: {str(e)}", error=True)
            if self.logger:
                self.logger.error("Console processing error: %s", e)
            self.enabled = False
            self.chk_enable.setChecked(False)
            return img


class ConsoleDialog(QtWidgets.QDialog):
    """Floating dialog window for the Python console"""
    
    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.setWindowTitle("Python Console - Real-time Processing")
        self.setGeometry(100, 100, 800, 600)
        
        # Make it non-modal so user can interact with main window
        self.setModal(False)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.console = PythonConsole(parent=self, logger=logger)
        layout.addWidget(self.console)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #e0e0e0;
            }
        """)
    
    def process_image(self, img: np.ndarray) -> np.ndarray:
        """Pass through to console's process_image"""
        return self.console.process_image(img)