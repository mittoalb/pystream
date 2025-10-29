#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NTNDArray Real-time Viewer (PyQt5/PyQtGraph)
---------------------------------------------------------------------

Usage:
  python pyqtgraph_viewer.py --pv <PVNAME>
     [--max-fps 0] [--hist-fps 4] [--display-bin 0]
     [--auto-every 10]
     [--proc-config processors.json] [--no-plugins]
     [--log-file path] [--log-level INFO]
"""

import argparse
import math
import time
import queue
import threading
import os
import json
import tempfile
import logging
from typing import Optional, Tuple, Dict

import numpy as np
import pvaccess as pva

# PyQt5
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.Qsci import QsciScintilla, QsciLexerPython, QsciLexerJSON


# PyQtGraph
import pyqtgraph as pg
pg.setConfigOptions(imageAxisOrder='row-major')

# Logger
from .logger import setup_custom_logger, log_exception

# Plugins
from .plugins.roi import ROIManager
from .plugins.mosalign import MotorScanDialog
from .plugins.line import LineProfileManager

LOGGER: Optional[logging.Logger] = None

try:
    from AdImageUtility import AdImageUtility as _ADU
    _HAS_ADU = True
except Exception:
    _HAS_ADU = False


# ----------------------- Config I/O -----------------------
def _app_dir() -> str:
    config_dir = os.path.join(os.path.expanduser("~"), ".pystream")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def _cfg_path(name: str = "viewer_config.json") -> str:
    return os.path.join(_app_dir(), name)

def _load_config(defaults: Optional[Dict] = None, filename: str = "viewer_config.json") -> Dict:
    if defaults is None:
        defaults = {}
    path = _cfg_path(filename)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        if LOGGER:
            LOGGER.warning("Config load failed (%s). Using defaults.", e)
        return dict(defaults)

def _save_config(data: dict, filename: str = "viewer_config.json") -> None:
    path = _cfg_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cfg.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
        if LOGGER:
            LOGGER.info("Config saved to %s", path)
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        if LOGGER:
            LOGGER.error("Failed to save config to %s", path)
            log_exception(LOGGER, e)
        raise


# ----------------------- Plugin pipeline -----------------------
PIPE = None
def _init_pipeline(proc_config_path: Optional[str]):
    global PIPE
    if not proc_config_path:
        if LOGGER: LOGGER.info("[Plugins] No proc_config path provided; pipeline disabled.")
        return
    try:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        procplug_path = os.path.join(here, "procplug.py")
        if not os.path.exists(procplug_path):
            if LOGGER: LOGGER.warning("[Plugins] procplug.py not found")
            PIPE = None
            return

        spec = importlib.util.spec_from_file_location("procplug", procplug_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        #cfg_path = proc_config_path if os.path.isabs(proc_config_path) else os.path.join(here, proc_config_path)
        
        cfg_path = (
                proc_config_path if os.path.isabs(proc_config_path) else os.path.join(here, "pipelines", os.path.basename(proc_config_path))
        )

        if LOGGER: LOGGER.info("[Plugins] Loading pipeline config: %s", cfg_path)
        PIPE = mod.ProcessorPipeline.from_config(cfg_path)
        if LOGGER: LOGGER.info("[Plugins] Pipeline initialized with %d processor(s)", len(getattr(PIPE, "processors", [])))
    except Exception as e:
        if LOGGER:
            LOGGER.error("[Plugins] Failed to initialize pipeline")
            log_exception(LOGGER, e)
        PIPE = None


# ----------------------- NTNDArray reshape -----------------------
def reshape_ntnda(ntnda) -> Tuple[int, np.ndarray, int, int, Optional[int], int, str]:
    """Returns: (imageId, image, nx, ny, nz, colorMode, fieldKey)"""
    if _HAS_ADU:
        from AdImageUtility import AdImageUtility
        return AdImageUtility.reshapeNtNdArray(ntnda)

    image_id = ntnda['uniqueId']
    dims = ntnda['dimension']
    nDims = len(dims)

    color_mode = 0
    if 'attribute' in ntnda:
        for a in ntnda['attribute']:
            if a.get('name') == 'ColorMode':
                try:
                    color_mode = a['value'][0]['value']
                except Exception:
                    pass
                break

    try:
        field_key = ntnda.getSelectedUnionFieldName()
        raw = ntnda['value'][0][field_key]
    except Exception:
        field_key = next(iter(ntnda['value'][0].keys()))
        raw = ntnda['value'][0][field_key]

    if nDims == 0:
        return (image_id, None, None, None, None, color_mode, field_key)

    if nDims == 2 and color_mode == 0:
        nx = dims[0]['size']; ny = dims[1]['size']
        img = np.asarray(raw).reshape(ny, nx)
        return (image_id, img, nx, ny, None, color_mode, field_key)

    if nDims == 3:
        d0, d1, d2 = dims[0]['size'], dims[1]['size'], dims[2]['size']
        arr = np.asarray(raw)
        if color_mode == 2:
            nz, nx, ny = d0, d1, d2
            img = arr.reshape(nz, nx, ny).transpose(2, 1, 0)
        elif color_mode == 3:
            nx, nz, ny = d0, d1, d2
            img = arr.reshape(nx, nz, ny).transpose(2, 0, 1)
        elif color_mode == 4:
            nx, ny, nz = d0, d1, d2
            img = arr.reshape(nx, ny, nz).transpose(1, 0, 2)
        else:
            if 1 in (d0, d1, d2):
                ny, nx = sorted([d0, d1, d2], reverse=True)[:2]
                img = arr.reshape(ny, nx); color_mode = 0
            else:
                raise pva.InvalidArgument(f'Unsupported dims/colorMode: {dims}, cm={color_mode}')
        return (image_id, img, img.shape[1], img.shape[0], img.shape[2] if img.ndim == 3 else None,
                color_mode, field_key)

    raise pva.InvalidArgument(f'Invalid NTNDArray dims: {dims}')


# ----------------------- PVA subscriber -----------------------
class NtndaSubscriber:
    def __init__(self, pv_name: str, out_queue: queue.Queue):
        self.pv_name = pv_name
        self.out_q = out_queue
        self.chan = pva.Channel(pv_name)
        self.subscribed = False
        self._lock = threading.Lock()
        
        #accumulate
        self.accumulating = False
        self.accumulated_sum = None
        self.accum_frame_count = 0

    def _callback(self, pv: pva.PvObject):
        try:
            uid, img, nx, ny, nz, cm, key = reshape_ntnda(pv)
            if img is None:
                return
            # Convert RGB to grayscale
            if img.ndim == 3 and img.shape[2] in (3, 4):
                img = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]).astype(np.float32, copy=False)

            # Latest-only queue
            try:
                while True:
                    self.out_q.get_nowait()
            except Exception:
                pass
            self.out_q.put_nowait((time.time(), uid, img))
        except Exception as exc:
            if LOGGER:
                LOGGER.error("[NtndaSubscriber] callback error")
                log_exception(LOGGER, exc)

    def start(self):
        with self._lock:
            if self.subscribed:
                return
            if LOGGER: LOGGER.info("Subscribing to PV %s", self.pv_name)
            self.chan.subscribe("viewer", self._callback)
            self.chan.startMonitor()
            self.subscribed = True

    def stop(self):
        with self._lock:
            if not self.subscribed:
                return
            if LOGGER: LOGGER.info("Stopping monitor for PV %s", self.pv_name)
            try:
                self.chan.stopMonitor()
            except Exception as e:
                if LOGGER:
                    LOGGER.warning("stopMonitor raised:")
                    log_exception(LOGGER, e)
            try:
                self.chan.unsubscribe("viewer")
            except Exception as e:
                if LOGGER:
                    LOGGER.warning("unsubscribe raised:")
                    log_exception(LOGGER, e)
            self.subscribed = False


# ----------------------- PyQtGraph Viewer App -----------------------
class PvViewerApp(QtWidgets.QMainWindow):
    image_ready = QtCore.pyqtSignal(int, np.ndarray, float)
    
    def __init__(self, pv_name: Optional[str], max_fps: int = 0,
                display_bin: int = 0, hist_fps: float = 4.0,
                auto_every: int = 10):
        super().__init__()
        
        self.setWindowTitle("NTNDArray PyQtGraph Viewer")
        self.setGeometry(100, 100, 1400, 900)
        
        # ===== INITIALIZE ALL ATTRIBUTES FIRST =====
        self.cfg = _load_config(defaults={"pv_name": pv_name or ""})
        
        self.max_fps = int(max_fps)
        self.frame_interval = (1.0 / self.max_fps) if self.max_fps > 0 else 0.0
        self.hist_interval = 1.0 / max(0.1, float(hist_fps))
        
        self.display_bin = int(display_bin)
        
        self.queue = queue.Queue(maxsize=1)
        self.sub = None
        self.last_draw = 0.0
        self.paused = False
        
        # View/contrast state
        self.vmin = 0.0
        self.vmax = 1.0
        self.autoscale_enabled = True
        self.flip_h = False
        self.flip_v = False
        self.transpose_img = False
        self.current_uid = -1
        self.fps_ema = None
        self._last_ts = time.time()
        
        # Autoscale cadence
        self._auto_every = max(1, int(auto_every))
        self._auto_cnt = 0
        
        # Flat-field
        self.flat = None
        self.apply_flat_enabled = False
        self._last_display_img = None
        self._work_f32 = None
        
        # Plugins
        self._use_plugins = PIPE is not None
        
        # Histogram throttling
        self._last_hist_t = 0.0
        
        # Crosshair
        self.crosshair_enabled = False
        self.crosshair_x = None
        self.crosshair_y = None
        
        # Recording
        self.recording = False
        self.recorded_frame_count = 0
        self.record_path = ""
        self.record_dir = ""
        
        # Initialize manager placeholders
        self.motor_scan_dialog = None
        self.roi_manager = None
        self.line_manager = None
        
        # Editor state (for code editor tab)
        self.current_editor_file = None
        
        # ===== NOW BUILD UI WITH TABS =====
        # Create central widget with tabs
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # === TAB 1: VIEWER ===
        viewer_widget = self._create_viewer_tab()
        self.tabs.addTab(viewer_widget, "📹 Viewer")
        
        # === TAB 2: CODE EDITOR ===
        editor_widget = self._create_editor_tab()
        self.tabs.addTab(editor_widget, "📝 Editor")
        
        # ===== POST-UI INITIALIZATION =====
        # Initialize ROI manager
        self.roi_manager = ROIManager(self.image_view, self.lbl_roi_info, logger=LOGGER)
        self.chk_roi.stateChanged.connect(self.roi_manager.toggle)
        self.btn_reset_roi.clicked.connect(self.roi_manager.reset)
        
        self.line_manager = LineProfileManager(self.image_view, self.lbl_line_info, logger=LOGGER)
        self.chk_line.stateChanged.connect(self.line_manager.toggle)
        self.btn_reset_line.clicked.connect(self.line_manager.reset)
        
        # Connect signal
        self.image_ready.connect(self._update_image_slot)
        
        # Start queue pump timer
        self.pump_timer = QtCore.QTimer()
        self.pump_timer.timeout.connect(self._pump_queue)
        self.pump_timer.start(5)
        
        # Auto-connect if PV present
        if self.pv_entry.text().strip():
            self._connect_pv()
    
    def _build_ui(self):
        """Build the main viewer UI and return as widget"""
        # Create container widget instead of setting as central widget
        viewer_container = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(viewer_container)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Top control bar
        top_bar = self._create_top_bar()
        main_layout.addWidget(top_bar)
        
        # Splitter
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        
        # Left panel
        left_panel = self._create_left_panel()
        left_panel.setMinimumWidth(320)
        left_panel.setMaximumWidth(400)
        splitter.addWidget(left_panel)
        
        # PyQtGraph ImageView
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        self.image_view.view.setMouseMode(pg.ViewBox.RectMode)
        
        # Enable mouse wheel zoom
        self.image_view.view.setMouseEnabled(x=True, y=True)
        
        # Disable panning but keep zoom
        self.image_view.view.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)
        
        # Add crosshair lines
        self.crosshair_vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('y', width=2))
        self.crosshair_hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('y', width=2))
        self.crosshair_vline.setVisible(False)
        self.crosshair_hline.setVisible(False)
        self.image_view.addItem(self.crosshair_vline)
        self.image_view.addItem(self.crosshair_hline)
        
        # Connect mouse events for crosshair
        self.image_view.scene.sigMouseMoved.connect(self._on_mouse_move)
        self.image_view.scene.sigMouseClicked.connect(self._on_mouse_click)
        
        splitter.addWidget(self.image_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([350, 1050])
        
        main_layout.addWidget(splitter, stretch=1)
        
        self._apply_dark_theme()
        
        # Return the container widget instead of setting as central
        return viewer_container
    

    def _create_viewer_tab(self):
        """Create the main viewer interface"""
        return self._build_ui()

    def _create_editor_tab(self):
        """Create code editor interface"""
        editor_container = QtWidgets.QWidget()
        editor_layout = QtWidgets.QVBoxLayout(editor_container)
        
        # Editor toolbar
        editor_toolbar = QtWidgets.QHBoxLayout()
        
        self.cmb_file_type = QtWidgets.QComboBox()
        self.cmb_file_type.addItems([
            "Pipeline Config (JSON)",
            "Python Processor",
            "Custom Script"
        ])
        self.cmb_file_type.currentIndexChanged.connect(self._on_editor_type_changed)
        editor_toolbar.addWidget(QtWidgets.QLabel("Edit:"))
        editor_toolbar.addWidget(self.cmb_file_type)
        
        btn_open = QtWidgets.QPushButton("Open...")
        btn_open.clicked.connect(self._editor_open_file)
        editor_toolbar.addWidget(btn_open)
        
        btn_save = QtWidgets.QPushButton("Save")
        btn_save.clicked.connect(self._editor_save_file)
        editor_toolbar.addWidget(btn_save)
        
        btn_save_as = QtWidgets.QPushButton("Save As...")
        btn_save_as.clicked.connect(self._editor_save_file_as)
        editor_toolbar.addWidget(btn_save_as)
        
        btn_run = QtWidgets.QPushButton("▶ Run/Reload")
        btn_run.clicked.connect(self._editor_run_code)
        btn_run.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        editor_toolbar.addWidget(btn_run)
        
        editor_toolbar.addStretch()
        
        self.lbl_editor_file = QtWidgets.QLabel("No file loaded")
        self.lbl_editor_file.setStyleSheet("color: #666;")
        editor_toolbar.addWidget(self.lbl_editor_file)
        
        editor_layout.addLayout(editor_toolbar)
        
        # === QScintilla Code Editor with Syntax Highlighting ===
        self.code_editor = QsciScintilla()
        
        # Set font
        font = QtGui.QFont("Courier New", 10)
        self.code_editor.setFont(font)
        
        # Line numbers margin
        self.code_editor.setMarginType(0, QsciScintilla.NumberMargin)
        self.code_editor.setMarginWidth(0, "00000")  # Width for up to 5 digits
        self.code_editor.setMarginsForegroundColor(QtGui.QColor("#888888"))
        self.code_editor.setMarginsBackgroundColor(QtGui.QColor("#2b2b2b"))
        
        # Current line highlighting
        self.code_editor.setCaretLineVisible(True)
        self.code_editor.setCaretLineBackgroundColor(QtGui.QColor("#2d2d2d"))
        
        # Indentation
        self.code_editor.setIndentationsUseTabs(False)
        self.code_editor.setTabWidth(4)
        self.code_editor.setAutoIndent(True)
        
        # Brace matching
        self.code_editor.setBraceMatching(QsciScintilla.SloppyBraceMatch)
        self.code_editor.setMatchedBraceBackgroundColor(QtGui.QColor("#4d4d4d"))
        
        # Auto-completion
        self.code_editor.setAutoCompletionSource(QsciScintilla.AcsAll)
        self.code_editor.setAutoCompletionThreshold(2)
        self.code_editor.setAutoCompletionCaseSensitivity(False)
        
        # Edge mode (80 character line)
        self.code_editor.setEdgeMode(QsciScintilla.EdgeLine)
        self.code_editor.setEdgeColumn(80)
        self.code_editor.setEdgeColor(QtGui.QColor("#444444"))
        
        # Python lexer (syntax highlighting)
        self.python_lexer = QsciLexerPython()
        self.python_lexer.setDefaultFont(font)
        
        # Set Python lexer colors (dark theme)
        self.python_lexer.setDefaultPaper(QtGui.QColor("#1e1e1e"))
        self.python_lexer.setDefaultColor(QtGui.QColor("#d4d4d4"))
        self.python_lexer.setColor(QtGui.QColor("#569cd6"), QsciLexerPython.Keyword)  # Keywords (blue)
        self.python_lexer.setColor(QtGui.QColor("#4ec9b0"), QsciLexerPython.ClassName)  # Classes (teal)
        self.python_lexer.setColor(QtGui.QColor("#dcdcaa"), QsciLexerPython.FunctionMethodName)  # Functions (yellow)
        self.python_lexer.setColor(QtGui.QColor("#ce9178"), QsciLexerPython.DoubleQuotedString)  # Strings (orange)
        self.python_lexer.setColor(QtGui.QColor("#ce9178"), QsciLexerPython.SingleQuotedString)
        self.python_lexer.setColor(QtGui.QColor("#6a9955"), QsciLexerPython.Comment)  # Comments (green)
        self.python_lexer.setColor(QtGui.QColor("#b5cea8"), QsciLexerPython.Number)  # Numbers (light green)
        self.python_lexer.setColor(QtGui.QColor("#c586c0"), QsciLexerPython.Decorator)  # Decorators (purple)
        
        # JSON lexer
        self.json_lexer = QsciLexerJSON()
        self.json_lexer.setDefaultFont(font)
        self.json_lexer.setDefaultPaper(QtGui.QColor("#1e1e1e"))
        
        # Set initial lexer based on selection
        self._set_editor_lexer()
        
        editor_layout.addWidget(self.code_editor)
        
        # Output/console area
        output_label = QtWidgets.QLabel("Output / Console:")
        editor_layout.addWidget(output_label)
        
        self.code_output = QtWidgets.QPlainTextEdit()
        self.code_output.setFont(QtGui.QFont("Courier New", 9))
        self.code_output.setReadOnly(True)
        self.code_output.setMaximumHeight(150)
        self.code_output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        editor_layout.addWidget(self.code_output)
        
        # Set initial content
        self.current_editor_file = None
        self._load_default_template()
        
        return editor_container



    def _set_editor_lexer(self):
        """Set the appropriate lexer based on file type"""
        file_type = self.cmb_file_type.currentText()
        
        if "JSON" in file_type:
            self.code_editor.setLexer(self.json_lexer)
        else:
            self.code_editor.setLexer(self.python_lexer)

    def _on_editor_type_changed(self, index):
        """Load template when editor type changes"""
        self._set_editor_lexer()
        if self.current_editor_file is None:
            self._load_default_template()


    def _on_editor_type_changed(self, index):
        """Load template when editor type changes"""
        if self.current_editor_file is None:
            self._load_default_template()

    def _editor_open_file(self):
        """Open file in editor"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open File", "",
            "All Files (*);;Python (*.py);;JSON (*.json);;Text (*.txt)"
        )
        if path:
            try:
                with open(path, 'r') as f:
                    content = f.read()
                self.code_editor.setText(content)  # Use setText instead of setPlainText
                self.current_editor_file = path
                self.lbl_editor_file.setText(f"File: {os.path.basename(path)}")
                self.code_output.appendPlainText(f"Opened: {path}")
                
                # Set lexer based on file extension
                if path.endswith('.json'):
                    self.code_editor.setLexer(self.json_lexer)
                elif path.endswith('.py'):
                    self.code_editor.setLexer(self.python_lexer)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Open File", f"Failed to open:\n{e}")

    def _editor_save_file(self):
        """Save current file"""
        if self.current_editor_file is None:
            self._editor_save_file_as()
            return
        
        try:
            content = self.code_editor.text()  # Use text() instead of toPlainText()
            with open(self.current_editor_file, 'w') as f:
                f.write(content)
            self.code_output.appendPlainText(f"Saved: {self.current_editor_file}")
            QtWidgets.QMessageBox.information(self, "Save", "File saved successfully!")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save File", f"Failed to save:\n{e}")

    def _load_default_template(self):
        """Load default template based on selected type"""
        file_type = self.cmb_file_type.currentText()
        
        if "Pipeline Config" in file_type:
            template = '''{
    "processors": [
        {
        "name": "example_processor",
        "type": "custom",
        "enabled": true,
        "params": {
            "threshold": 100
        }
        }
    ]
    }'''
            self.code_editor.setText(template)  # Use setText
            
        elif "Python Processor" in file_type:
            template = '''import numpy as np

    class CustomProcessor:
        """Custom image processor"""
        
        def __init__(self, params=None):
            self.params = params or {}
        
        def process(self, image: np.ndarray) -> np.ndarray:
            """
            Process an image frame
            
            Args:
                image: Input image as numpy array
                
            Returns:
                Processed image
            """
            # Your processing code here
            processed = image.copy()
            
            # Example: apply threshold
            threshold = self.params.get('threshold', 100)
            processed[processed < threshold] = 0
            
            return processed
    '''
            self.code_editor.setText(template)
            
        else:  # Custom Script
            template = '''import numpy as np

    # Your custom script here
    # Access the viewer instance via: viewer

    def process_frame(frame):
        """Process a single frame"""
        # Your code here
        return frame
    '''
            self.code_editor.setText(template)

    def _editor_save_file_as(self):
        """Save file with new name"""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save File As", "",
            "Python (*.py);;JSON (*.json);;Text (*.txt);;All Files (*)"
        )
        if path:
            self.current_editor_file = path
            self._editor_save_file()
            self.lbl_editor_file.setText(f"File: {os.path.basename(path)}")

    def _editor_run_code(self):
        """Execute or reload the code"""
        file_type = self.cmb_file_type.currentText()
        
        try:
            if "Pipeline Config" in file_type:
                # Reload pipeline config
                self._editor_log("Reloading pipeline configuration...")
                if self.current_editor_file:
                    _init_pipeline(self.current_editor_file)
                    self._editor_log("✓ Pipeline reloaded successfully!")
                else:
                    self._editor_log("⚠ Save the config file first, then reload.")
                    
            elif "Python Processor" in file_type:
                # Execute Python processor
                self._editor_log("Loading Python processor...")
                code = self.code_editor.toPlainText()
                exec_globals = {'np': np}
                exec(code, exec_globals)
                self._editor_log("✓ Python code executed successfully!")
                
            else:  # Custom Script
                # Execute custom script with viewer access
                self._editor_log("Executing custom script...")
                code = self.code_editor.toPlainText()
                exec_globals = {
                    'np': np,
                    'viewer': self,
                    'Image': Image if 'Image' in dir() else None
                }
                exec(code, exec_globals)
                self._editor_log("✓ Script executed successfully!")
                
        except Exception as e:
            self._editor_log(f"✗ Error: {e}")
            if LOGGER:
                log_exception(LOGGER, e)

    def _editor_log(self, message: str):
        """Add message to editor output"""
        self.code_output.appendPlainText(message)



    def _create_top_bar(self):
        top_bar = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top_bar)
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setSpacing(8)
        
        # === CONNECTION GROUP ===
        conn_group = QtWidgets.QGroupBox("Connection")
        conn_layout = QtWidgets.QHBoxLayout()
        conn_layout.setSpacing(5)
        conn_layout.setContentsMargins(5, 5, 5, 5)
        
        conn_layout.addWidget(QtWidgets.QLabel("PV:"))
        self.pv_entry = QtWidgets.QLineEdit(self.cfg.get("pv_name", ""))
        self.pv_entry.setMinimumWidth(200)
        self.pv_entry.returnPressed.connect(self._connect_pv)
        conn_layout.addWidget(self.pv_entry)
        
        btn_connect = QtWidgets.QPushButton("Connect")
        btn_connect.clicked.connect(self._connect_pv)
        conn_layout.addWidget(btn_connect)
        
        btn_disconnect = QtWidgets.QPushButton("Disconnect")
        btn_disconnect.clicked.connect(self._disconnect_pv)
        conn_layout.addWidget(btn_disconnect)
        
        conn_group.setLayout(conn_layout)
        top_layout.addWidget(conn_group)
        
        # === PLAYBACK GROUP ===
        playback_group = QtWidgets.QGroupBox("Playback")
        playback_layout = QtWidgets.QHBoxLayout()
        playback_layout.setSpacing(5)
        playback_layout.setContentsMargins(5, 5, 5, 5)
        
        self.btn_pause = QtWidgets.QPushButton("Pause")
        self.btn_pause.setCheckable(True)
        self.btn_pause.clicked.connect(self._toggle_pause)
        playback_layout.addWidget(self.btn_pause)
        
        self.btn_accumulate = QtWidgets.QPushButton("Accumulate: OFF")
        self.btn_accumulate.setCheckable(True)
        self.btn_accumulate.clicked.connect(self._toggle_accumulation)
        playback_layout.addWidget(self.btn_accumulate)
        
        self.btn_record = QtWidgets.QPushButton("Record")
        self.btn_record.setCheckable(True)
        self.btn_record.clicked.connect(self._toggle_recording)
        playback_layout.addWidget(self.btn_record)
        
        playback_group.setLayout(playback_layout)
        top_layout.addWidget(playback_group)
        
        # === VIEW CONTROLS GROUP ===
        view_group = QtWidgets.QGroupBox("View")
        view_layout = QtWidgets.QHBoxLayout()
        view_layout.setSpacing(5)
        view_layout.setContentsMargins(5, 5, 5, 5)
        
        btn_home = QtWidgets.QPushButton("Home")
        btn_home.clicked.connect(self._reset_view)
        btn_home.setToolTip("Reset zoom and pan to show full image")
        view_layout.addWidget(btn_home)
        
        self.chk_autoscale = QtWidgets.QCheckBox("Autoscale")
        self.chk_autoscale.setChecked(True)
        self.chk_autoscale.stateChanged.connect(self._autoscale_toggled)
        view_layout.addWidget(self.chk_autoscale)
        
        self.chk_crosshair = QtWidgets.QCheckBox("Crosshair")
        self.chk_crosshair.stateChanged.connect(self._toggle_crosshair)
        view_layout.addWidget(self.chk_crosshair)
        
        view_group.setLayout(view_layout)
        top_layout.addWidget(view_group)
        
        # === ANALYSIS TOOLS GROUP ===
        analysis_group = QtWidgets.QGroupBox("Analysis")
        analysis_layout = QtWidgets.QHBoxLayout()
        analysis_layout.setSpacing(5)
        analysis_layout.setContentsMargins(5, 5, 5, 5)
        
        self.chk_roi = QtWidgets.QCheckBox("ROI")
        analysis_layout.addWidget(self.chk_roi)
        
        self.btn_reset_roi = QtWidgets.QPushButton("Reset ROI")
        analysis_layout.addWidget(self.btn_reset_roi)
        
        self.chk_line = QtWidgets.QCheckBox("Line")
        analysis_layout.addWidget(self.chk_line)
        
        self.btn_reset_line = QtWidgets.QPushButton("Reset Line")
        analysis_layout.addWidget(self.btn_reset_line)
        
        analysis_group.setLayout(analysis_layout)
        top_layout.addWidget(analysis_group)
        
        # === TRANSFORM GROUP ===
        transform_group = QtWidgets.QGroupBox("Transform")
        transform_layout = QtWidgets.QHBoxLayout()
        transform_layout.setSpacing(5)
        transform_layout.setContentsMargins(5, 5, 5, 5)
        
        self.chk_flip_h = QtWidgets.QCheckBox("Flip H")
        self.chk_flip_h.stateChanged.connect(self._view_changed)
        transform_layout.addWidget(self.chk_flip_h)
        
        self.chk_flip_v = QtWidgets.QCheckBox("Flip V")
        self.chk_flip_v.stateChanged.connect(self._view_changed)
        transform_layout.addWidget(self.chk_flip_v)
        
        self.chk_transpose = QtWidgets.QCheckBox("Transpose")
        self.chk_transpose.stateChanged.connect(self._view_changed)
        transform_layout.addWidget(self.chk_transpose)
        
        transform_group.setLayout(transform_layout)
        top_layout.addWidget(transform_group)
        
        # === PROCESSING GROUP ===
        processing_group = QtWidgets.QGroupBox("Processing")
        processing_layout = QtWidgets.QHBoxLayout()
        processing_layout.setSpacing(5)
        processing_layout.setContentsMargins(5, 5, 5, 5)
        
        self.chk_apply_flat = QtWidgets.QCheckBox("Apply Flat")
        self.chk_apply_flat.stateChanged.connect(self._view_changed)
        processing_layout.addWidget(self.chk_apply_flat)
        
        btn_capture = QtWidgets.QPushButton("Capture")
        btn_capture.clicked.connect(self._capture_flat)
        processing_layout.addWidget(btn_capture)
        
        btn_load = QtWidgets.QPushButton("Load...")
        btn_load.clicked.connect(self._load_flat)
        processing_layout.addWidget(btn_load)
        
        btn_save = QtWidgets.QPushButton("Save...")
        btn_save.clicked.connect(self._save_flat)
        processing_layout.addWidget(btn_save)
        
        btn_clear = QtWidgets.QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_flat)
        processing_layout.addWidget(btn_clear)
        
        btn_motor_scan = QtWidgets.QPushButton("Mosalign")
        btn_motor_scan.clicked.connect(self._open_motor_scan)
        btn_motor_scan.setToolTip("Open Mosalign GUI")
        processing_layout.addWidget(btn_motor_scan)
        
        processing_group.setLayout(processing_layout)
        top_layout.addWidget(processing_group)
        
        # Add stretch to push status labels to the right
        top_layout.addStretch()
        
        # === STATUS LABELS ===
        self.lbl_fps = QtWidgets.QLabel("FPS: —")
        self.lbl_fps.setMinimumWidth(80)
        self.lbl_fps.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(self.lbl_fps)
        
        self.lbl_uid = QtWidgets.QLabel("UID: —")
        self.lbl_uid.setMinimumWidth(100)
        self.lbl_uid.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(self.lbl_uid)
        
        return top_bar
    
    def _create_left_panel(self):
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(8)
        
        # Contrast group
        contrast_group = QtWidgets.QGroupBox("Contrast")
        contrast_layout = QtWidgets.QVBoxLayout()
        contrast_layout.setSpacing(4)
        
        contrast_layout.addWidget(QtWidgets.QLabel("Min (vmin)"))
        self.sld_min = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_min.setRange(0, 65535)
        self.sld_min.valueChanged.connect(self._slider_changed)
        contrast_layout.addWidget(self.sld_min)
        
        contrast_layout.addWidget(QtWidgets.QLabel("Max (vmax)"))
        self.sld_max = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_max.setRange(0, 65535)
        self.sld_max.setValue(65535)
        self.sld_max.valueChanged.connect(self._slider_changed)
        contrast_layout.addWidget(self.sld_max)
        
        contrast_group.setLayout(contrast_layout)
        left_layout.addWidget(contrast_group)
        
        # Histogram group
        hist_group = QtWidgets.QGroupBox("Histogram")
        hist_layout = QtWidgets.QVBoxLayout()
        self.hist_widget = pg.PlotWidget()
        self.hist_widget.setMinimumHeight(180)
        self.hist_widget.setBackground('k')
        hist_layout.addWidget(self.hist_widget)
        hist_group.setLayout(hist_layout)
        left_layout.addWidget(hist_group)
        
        # Image info group
        info_group = QtWidgets.QGroupBox("Image Info")
        info_layout = QtWidgets.QVBoxLayout()
        self.lbl_info = QtWidgets.QLabel("No image")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("QLabel { background-color: #1a1a1a; padding: 8px; border: 1px solid #333; }")
        info_layout.addWidget(self.lbl_info)
        info_group.setLayout(info_layout)
        left_layout.addWidget(info_group)


        # ROI Statistics group - ADD THESE 11 LINES
        roi_group = QtWidgets.QGroupBox("ROI Statistics")
        roi_layout = QtWidgets.QVBoxLayout()
        self.lbl_roi_info = QtWidgets.QLabel("No ROI selected")
        self.lbl_roi_info.setWordWrap(True)
        self.lbl_roi_info.setStyleSheet(
                "QLabel { background-color: #1a1a1a; padding: 8px; "
                "border: 1px solid #333; font-family: monospace; }"
        )
        roi_layout.addWidget(self.lbl_roi_info)
        roi_group.setLayout(roi_layout)
        left_layout.addWidget(roi_group)

        # Line Profile group
        line_group = QtWidgets.QGroupBox("Line Profile")
        line_layout = QtWidgets.QVBoxLayout()
        self.lbl_line_info = QtWidgets.QLabel("No line selected")
        self.lbl_line_info.setWordWrap(True)
        line_layout.addWidget(self.lbl_line_info)
        line_group.setLayout(line_layout)
        left_layout.addWidget(line_group)
        
        # Crosshair info group
        crosshair_group = QtWidgets.QGroupBox("Crosshair")
        crosshair_layout = QtWidgets.QVBoxLayout()
        self.lbl_crosshair = QtWidgets.QLabel("Disabled")
        self.lbl_crosshair.setWordWrap(True)
        self.lbl_crosshair.setStyleSheet("QLabel { background-color: #1a1a1a; padding: 8px; border: 1px solid #333; font-family: monospace; }")
        crosshair_layout.addWidget(self.lbl_crosshair)
        crosshair_group.setLayout(crosshair_layout)
        left_layout.addWidget(crosshair_group)
        
        # Recording group
        record_group = QtWidgets.QGroupBox("Recording (TIFF Stack)")
        record_layout = QtWidgets.QVBoxLayout()
        record_layout.setSpacing(6)
        
        # Path selection with label
        record_layout.addWidget(QtWidgets.QLabel("Output File:"))
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.setSpacing(4)
        self.record_path_entry = QtWidgets.QLineEdit()
        self.record_path_entry.setPlaceholderText("recording.tiff")
        self.record_path_entry.setToolTip("Path where multi-frame TIFF stack will be saved")
        path_layout.addWidget(self.record_path_entry)
        btn_browse = QtWidgets.QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_record_path)
        btn_browse.setMaximumWidth(100)
        path_layout.addWidget(btn_browse)
        record_layout.addLayout(path_layout)
        
        # Status label with instructions
        self.lbl_record_status = QtWidgets.QLabel(
            "Not recording\n\n"
            "Click 'Start Recording' to begin\n"
            "capturing all frames.\n"
            "Click 'Stop Recording' to save."
        )
        self.lbl_record_status.setWordWrap(True)
        self.lbl_record_status.setStyleSheet("QLabel { background-color: #1a1a1a; padding: 6px; border: 1px solid #333; }")
        record_layout.addWidget(self.lbl_record_status)
        
        record_group.setLayout(record_layout)
        left_layout.addWidget(record_group)
        
        # Save button
        btn_save_frame = QtWidgets.QPushButton("Save Current Frame...")
        btn_save_frame.clicked.connect(self._save_frame)
        left_layout.addWidget(btn_save_frame)
        
        left_layout.addStretch()
        
        return left_panel
    
    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { 
                background-color: #1a1a1a; 
                color: #e0e0e0; 
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
                border: 1px solid #505050;
            }
            QPushButton:pressed { 
                background-color: #252525; 
            }
            QPushButton:checked {
                background-color: #1e5a8e;
                border: 1px solid #2980b9;
            }
            QLineEdit { 
                background-color: #2d2d2d; 
                color: #e0e0e0; 
                padding: 4px 8px; 
                border: 1px solid #404040; 
                border-radius: 3px;
            }
            QCheckBox { 
                color: #e0e0e0; 
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #404040;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #2980b9;
                border: 1px solid #3a95d8;
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
            QLabel { 
                color: #e0e0e0; 
            }
            QSlider::groove:horizontal {
                border: 1px solid #404040;
                height: 6px;
                background: #2d2d2d;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2980b9;
                border: 1px solid #3a95d8;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #3a95d8;
            }
            QFrame[frameShape="4"], QFrame[frameShape="5"] {
                color: #404040;
            }
            QSplitter::handle {
                background-color: #2d2d2d;
            }
            QSplitter::handle:horizontal {
                width: 3px;
            }
        """)
    
    # ------------- PV connect/disconnect -------------
    def _connect_pv(self):
        pv = self.pv_entry.text().strip()
        if not pv:
            QtWidgets.QMessageBox.warning(self, "Connect PV", "Please enter a PV name.")
            return
        self._disconnect_pv(silent=True)
        try:
            while not self.queue.empty():
                self.queue.get_nowait()
        except Exception:
            pass
        self.current_uid = -1
        self.lbl_uid.setText("UID: —")
        try:
            self.sub = NtndaSubscriber(pv, self.queue)
            self.sub.start()
            self.setWindowTitle(f"NTNDArray PyQtGraph Viewer - {pv}")
            if LOGGER: LOGGER.info("Connected to PV %s", pv)
        except Exception as e:
            self.sub = None
            if LOGGER:
                LOGGER.error("Failed to connect to PV: %s", pv)
                log_exception(LOGGER, e)
            QtWidgets.QMessageBox.critical(self, "Connect PV", f"Failed to connect:\n{e}")
    
    def _disconnect_pv(self, silent: bool = False):
        if self.sub is not None:
            try:
                self.sub.stop()
            except Exception as e:
                if LOGGER:
                    LOGGER.warning("Error stopping subscription:")
                    log_exception(LOGGER, e)
            self.sub = None
            self.setWindowTitle("NTNDArray PyQtGraph Viewer")
            if not silent:
                QtWidgets.QMessageBox.information(self, "Disconnect PV", "Disconnected.")
            if LOGGER: LOGGER.info("Disconnected from PV")
    
    # ------------- Queue pump -------------
    def _pump_queue(self):
        if self.paused:
            return
        
        now = time.time()
        if self.max_fps > 0 and (now - self.last_draw < self.frame_interval):
            return
        
        latest = None
        try:
            while True:
                latest = self.queue.get_nowait()
        except Exception:
            pass
        
        if latest is not None:
            ts, uid, img = latest
            if PIPE is not None:
                try:
                    img = PIPE.apply(img, {"uid": uid, "timestamp": ts})
                except Exception as e:
                    if LOGGER:
                        LOGGER.error("[Plugins] pipeline error")
                        log_exception(LOGGER, e)
            self.image_ready.emit(uid, img, ts)
            self.last_draw = now
    
    # ------------- Image update -------------
    def _auto_display_bin(self, img) -> int:
        try:
            cw = max(1, self.image_view.width())
            ch = max(1, self.image_view.height())
        except Exception:
            return 1
        by = max(1, img.shape[0] // ch)
        bx = max(1, img.shape[1] // cw)
        return max(1, min(by, bx))
    
    def _apply_view_ops(self, img: np.ndarray) -> np.ndarray:
        # Decimation
        b = self.display_bin if self.display_bin > 0 else self._auto_display_bin(img)
        if b > 1:
            img = img[::b, ::b]
        
        # Transforms
        if self.transpose_img:
            img = np.swapaxes(img, 0, 1)
        if self.flip_h:
            img = img[:, ::-1]
        if self.flip_v:
            img = img[::-1, :]
        
        if not img.flags.c_contiguous:
            img = np.ascontiguousarray(img)
        
        # Flat-field
        if self.apply_flat_enabled and self.flat is not None and self.flat.shape == img.shape:
            img = self._apply_flat_field(img)
        
        return img
    
    @QtCore.pyqtSlot(int, np.ndarray, float)
    def _update_image_slot(self, uid: int, img: np.ndarray, ts: float):
        img = self._apply_view_ops(img)
        self._last_display_img = img
        self.current_uid = uid

        # ACCUMULATION LOGIC - ADD THIS AT THE START
        if self.sub and self.sub.accumulating:
            # Accumulate frames
            if self.sub.accumulated_sum is None:
                # First frame
                self.sub.accumulated_sum = img.astype(np.float64)
                self.sub.accum_frame_count = 1
            else:
                # Add to accumulation
                self.sub.accumulated_sum += img.astype(np.float64)
                self.sub.accum_frame_count += 1
            
            # Use accumulated sum for display
            img = self.sub.accumulated_sum
            
            # Update status (optional - show in window title or status bar)
            # self.setWindowTitle(f"PyStream - Accumulated: {self.subscriber.accum_frame_count} frames")

        # Compute contrast
        self._ensure_slider_range(img)
        if self.autoscale_enabled:
            if (self._auto_cnt % self._auto_every == 0) or (self.vmin is None or self.vmax is None):
                self.vmin, self.vmax = self._autoscale_values_fast(img)
            self._auto_cnt += 1
        
        vmin, vmax = self.vmin, self.vmax
        if vmin is None: vmin = 0.0
        if vmax is None: vmax = 1.0
        
        # Update PyQtGraph image - FAST rendering
        self.image_view.setImage(img, autoRange=False, autoLevels=False, levels=(vmin, vmax))
        
        # Update crosshair if enabled
        if self.crosshair_enabled:
            if self.crosshair_x is None or self.crosshair_y is None:
                self.crosshair_x = img.shape[1] // 2
                self.crosshair_y = img.shape[0] // 2
            self._update_crosshair_display()
        
        # Update ROI Statistic
        self.roi_manager.update_stats(img)
        self.line_manager.update_stats(img)

        # FPS calculation
        now = time.time()
        dt = max(1e-6, now - self._last_ts)
        inst_fps = 1.0 / dt
        self.fps_ema = inst_fps if self.fps_ema is None else (0.8 * self.fps_ema + 0.2 * inst_fps)
        self._last_ts = now
        
        self.lbl_uid.setText(f"UID: {uid}")
        self.lbl_fps.setText(f"FPS: {self.fps_ema:4.1f}")
        
        # Update image info
        self.lbl_info.setText(
            f"Shape: {img.shape}\n"
            f"Dtype: {img.dtype}\n"
            f"Min: {img.min():.2f}\n"
            f"Max: {img.max():.2f}\n"
            f"Mean: {img.mean():.2f}"
        )
        
        # Recording - capture frame
        if self.recording:
            self.recorded_frames.append(np.copy(img))
            num_frames = len(self.recorded_frames)
            self.lbl_record_status.setText(
                f"🔴 RECORDING\n\n"
                f"Frames: {num_frames}\n\n"
                f"Click 'Stop Recording' to save\n"
                f"all {num_frames} frames as TIFF stack"
            )
        
        # Histogram update (throttled)
        if (now - self._last_hist_t) >= self.hist_interval:
            self._update_histogram(img, vmin, vmax)
            self._last_hist_t = now
    
    # ------------- Flat-field -------------
    def _apply_flat_field(self, img: np.ndarray) -> np.ndarray:
        flat = self.flat
        if flat is None or flat.shape != img.shape:
            return img
        
        if self._work_f32 is None or self._work_f32.shape != img.shape:
            self._work_f32 = np.empty(img.shape, dtype=np.float32)
        
        eps = 1e-6
        np.maximum(flat, eps, out=self._work_f32)
        np.divide(img, self._work_f32, out=self._work_f32, dtype=np.float32)
        self._work_f32 *= float(np.mean(flat, dtype=np.float32))
        
        if np.issubdtype(img.dtype, np.integer):
            info = np.iinfo(img.dtype)
            np.clip(self._work_f32, info.min, info.max, out=self._work_f32)
            return self._work_f32.astype(img.dtype, copy=False)
        return self._work_f32.astype(img.dtype, copy=False)
    
    # ------------- Histogram -------------
    def _update_histogram(self, img, vmin, vmax):
        try:
            step = max(1, int(max(img.shape) / 512))
            h = img[::step, ::step].ravel()
            y, x = np.histogram(h, bins=64)
            self.hist_widget.clear()
            self.hist_widget.plot(x, y, stepMode=True, fillLevel=0, brush=(100, 100, 255, 100))
            
            # Add vmin/vmax lines
            if vmin is not None and vmax is not None:
                self.hist_widget.addLine(x=vmin, pen=pg.mkPen('r', width=2))
                self.hist_widget.addLine(x=vmax, pen=pg.mkPen('r', width=2))
        except Exception as e:
            if LOGGER:
                LOGGER.warning("Histogram update failed:")
                log_exception(LOGGER, e)
    
    # ------------- Contrast -------------
    def _ensure_slider_range(self, img: np.ndarray):
        dtype = img.dtype
        if np.issubdtype(dtype, np.integer):
            info = np.iinfo(dtype)
            lo, hi = int(info.min), int(info.max)
        else:
            step = max(1, int(max(img.shape) / 512))
            samp = img[::step, ::step]
            lo = float(np.nanmin(samp))
            hi = float(np.nanmax(samp))
            if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
                lo, hi = 0.0, 1.0
        
        if self.sld_min.maximum() != hi or self.sld_min.minimum() != lo:
            self.sld_min.blockSignals(True)
            self.sld_max.blockSignals(True)
            self.sld_min.setRange(int(lo), int(hi))
            self.sld_max.setRange(int(lo), int(hi))
            self.sld_min.blockSignals(False)
            self.sld_max.blockSignals(False)
    
    def _autoscale_values_fast(self, img: np.ndarray):
        step = max(1, int(max(img.shape) / 512))
        samp = img[::step, ::step]
        lo = float(np.percentile(samp, 0.5))
        hi = float(np.percentile(samp, 99.5))
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            lo, hi = float(np.nanmin(samp)), float(np.nanmax(samp))
        return lo, hi
    
    def _slider_changed(self):
        if hasattr(self, '_updating_sliders') and self._updating_sliders:
            return
        self.autoscale_enabled = False
        self.chk_autoscale.setChecked(False)
        vmin = float(self.sld_min.value())
        vmax = float(self.sld_max.value())
        if vmax <= vmin:
            vmax = vmin + 1e-6
        self.vmin, self.vmax = vmin, vmax
        if self._last_display_img is not None:
            self.image_view.setImage(self._last_display_img, autoRange=False, autoLevels=False, levels=(vmin, vmax))
    
    def _toggle_accumulation(self):
        """Toggle frame accumulation on/off"""
        if self.sub is None:
            QtWidgets.QMessageBox.warning(self, "Accumulate", "Not connected to a PV.")
            self.btn_accumulate.setChecked(False)
            return
    
        self.sub.accumulating = self.btn_accumulate.isChecked()
    
        if self.sub.accumulating:
            # Starting accumulation
            self.btn_accumulate.setText("Accumulate: ON")
            self.sub.accumulated_sum = None  # Reset
            self.sub.accum_frame_count = 0
            if LOGGER:
                LOGGER.info("Frame accumulation started")
        else:
            # Stopping accumulation
            self.btn_accumulate.setText("Accumulate: OFF")
            if LOGGER:
                LOGGER.info(f"Frame accumulation stopped at {self.sub.accum_frame_count} frames")


    def _autoscale_toggled(self):
        self.autoscale_enabled = self.chk_autoscale.isChecked()
        if self.autoscale_enabled and self._last_display_img is not None:
            self.vmin, self.vmax = self._autoscale_values_fast(self._last_display_img)
            self._update_sliders(self.vmin, self.vmax)
            self.image_view.setImage(self._last_display_img, autoRange=False, autoLevels=False, levels=(self.vmin, self.vmax))
    
    def _update_sliders(self, vmin, vmax):
        self._updating_sliders = True
        try:
            self.sld_min.setValue(int(vmin))
            self.sld_max.setValue(int(vmax))
        finally:
            self._updating_sliders = False
    
    def _view_changed(self):
        self.flip_h = self.chk_flip_h.isChecked()
        self.flip_v = self.chk_flip_v.isChecked()
        self.transpose_img = self.chk_transpose.isChecked()
        self.apply_flat_enabled = self.chk_apply_flat.isChecked()
    
    # ------------- Crosshair -------------
    def _toggle_crosshair(self):
        self.crosshair_enabled = self.chk_crosshair.isChecked()
        self.crosshair_vline.setVisible(self.crosshair_enabled)
        self.crosshair_hline.setVisible(self.crosshair_enabled)
        
        if not self.crosshair_enabled:
            self.lbl_crosshair.setText("Disabled")
        else:
            self.lbl_crosshair.setText("Enabled\n(click or drag on image)")
            if self._last_display_img is not None:
                if self.crosshair_x is None or self.crosshair_y is None:
                    self.crosshair_x = self._last_display_img.shape[1] // 2
                    self.crosshair_y = self._last_display_img.shape[0] // 2
                self._update_crosshair_display()
    
    def _update_crosshair_display(self):
        if not self.crosshair_enabled or self._last_display_img is None:
            return
        
        self.crosshair_vline.setPos(self.crosshair_x)
        self.crosshair_hline.setPos(self.crosshair_y)
        
        # Update label with position and value
        try:
            h, w = self._last_display_img.shape[:2]
            x = int(np.clip(self.crosshair_x, 0, w - 1))
            y = int(np.clip(self.crosshair_y, 0, h - 1))
            value = float(self._last_display_img[y, x])
            
            self.lbl_crosshair.setText(
                f"Position:\n"
                f"  X: {x}\n"
                f"  Y: {y}\n"
                f"\n"
                f"Value: {value:.4f}"
            )
        except (IndexError, ValueError):
            pass
    
    def _on_mouse_move(self, pos):
        if not self.crosshair_enabled or self._last_display_img is None:
            return
        
        # Get image coordinates from scene position
        img_pos = self.image_view.getImageItem().mapFromScene(pos)
        x, y = img_pos.x(), img_pos.y()
        
        # Update crosshair
        self.crosshair_x = x
        self.crosshair_y = y
        self._update_crosshair_display()
    
    def _on_mouse_click(self, event):
        if not self.crosshair_enabled or self._last_display_img is None:
            return
        
        pos = event.scenePos()
        img_pos = self.image_view.getImageItem().mapFromScene(pos)
        x, y = img_pos.x(), img_pos.y()
        
        self.crosshair_x = x
        self.crosshair_y = y
        self._update_crosshair_display()
    
    # ------------- Flat-field commands -------------
    def _capture_flat(self):
        if self._last_display_img is None:
            QtWidgets.QMessageBox.information(self, "Capture Flat", "No image to capture yet.")
            return
        self.flat = np.array(self._last_display_img, copy=True)
        QtWidgets.QMessageBox.information(self, "Capture Flat", "Flat captured from current view.")
    
    def _load_flat(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Flat", "", "NumPy Array (*.npy);;All Files (*)"
        )
        if not path:
            return
        try:
            arr = np.load(path)
            self.flat = arr
            QtWidgets.QMessageBox.information(
                self, "Load Flat", f"Loaded flat {arr.shape}, dtype={arr.dtype}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Flat", f"Failed to load flat:\n{e}")
            if LOGGER:
                LOGGER.error("Failed to load flat from %s", path)
                log_exception(LOGGER, e)
    
    def _save_flat(self):
        if self.flat is None:
            QtWidgets.QMessageBox.information(self, "Save Flat", "No flat to save.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Flat", "", "NumPy Array (*.npy);;All Files (*)"
        )
        if not path:
            return
        try:
            np.save(path, self.flat)
            QtWidgets.QMessageBox.information(self, "Save Flat", f"Saved flat to:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Flat", f"Failed to save flat:\n{e}")
            if LOGGER:
                LOGGER.error("Failed to save flat to %s", path)
                log_exception(LOGGER, e)
    
    def _clear_flat(self):
        self.flat = None
        QtWidgets.QMessageBox.information(self, "Clear Flat", "Flat cleared.")
    
    # ------------- Recording -------------
    def _browse_record_path(self):
        """Browse for output TIFF file path"""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Recording As", "", "TIFF Stack (*.tiff *.tif);;All Files (*)"
        )
        if path:
            self.record_path_entry.setText(path)
    
    def _toggle_recording(self):
        """Start or stop recording frames"""
        if not self.recording:
            # Start recording
            path = self.record_path_entry.text().strip()
            if not path:
                QtWidgets.QMessageBox.warning(
                    self, "Start Recording", 
                    "Please specify an output file path first."
                )
                self.btn_record.setChecked(False)
                return
            
            self.recording = True
            self.recorded_frames = []
            self.record_path = path
            self.btn_record.setText("Stop Recording")
            self.btn_record.setStyleSheet("QPushButton:checked { background-color: #8B0000; }")
            self.lbl_record_status.setText(
                "🔴 RECORDING\n\n"
                "Frames: 0\n\n"
                "Click 'Stop Recording' to save\n"
                "all captured frames as TIFF stack"
            )
            if LOGGER:
                LOGGER.info("Started recording to %s", path)
        else:
            # Stop recording and save
            self.recording = False
            self.btn_record.setText("Start Recording")
            self.btn_record.setStyleSheet("")
            
            if not self.recorded_frames:
                self.lbl_record_status.setText(
                    "Not recording\n\n"
                    "Click 'Start Recording' to begin\n"
                    "capturing all frames.\n"
                    "Click 'Stop Recording' to save."
                )
                QtWidgets.QMessageBox.information(
                    self, "Stop Recording", 
                    "No frames were recorded."
                )
                return
            
            # Save frames as TIFF stack
            try:
                from PIL import Image
                
                num_frames = len(self.recorded_frames)
                self.lbl_record_status.setText(
                    f"Saving {num_frames} frames\n"
                    f"to TIFF stack...\n\n"
                    f"Please wait..."
                )
                QtWidgets.QApplication.processEvents()  # Update UI
                
                # Convert frames to appropriate format for TIFF
                # Stack as list of PIL Images
                pil_images = []
                for frame in self.recorded_frames:
                    # Convert to uint16 if needed (TIFF supports uint16)
                    if frame.dtype != np.uint16:
                        # Normalize and scale to uint16 range
                        frame_min = frame.min()
                        frame_max = frame.max()
                        if frame_max > frame_min:
                            normalized = (frame - frame_min) / (frame_max - frame_min)
                            frame_u16 = (normalized * 65535).astype(np.uint16)
                        else:
                            frame_u16 = np.zeros_like(frame, dtype=np.uint16)
                    else:
                        frame_u16 = frame
                    
                    pil_images.append(Image.fromarray(frame_u16))
                
                # Save as multi-page TIFF
                pil_images[0].save(
                    self.record_path,
                    save_all=True,
                    append_images=pil_images[1:],
                    compression="tiff_deflate"
                )
                
                self.lbl_record_status.setText(
                    f"✓ Saved successfully!\n\n"
                    f"{num_frames} frames saved to:\n"
                    f"{os.path.basename(self.record_path)}\n\n"
                    f"Ready to record again"
                )
                if LOGGER:
                    LOGGER.info("Saved %d frames to %s", num_frames, self.record_path)
                
                QtWidgets.QMessageBox.information(
                    self, "Recording Saved", 
                    f"Successfully saved {num_frames} frames\n"
                    f"as multi-page TIFF stack to:\n\n{self.record_path}"
                )
            except Exception as e:
                self.lbl_record_status.setText(
                    "✗ Save failed!\n\n"
                    "See error message.\n\n"
                    "Ready to record again"
                )
                if LOGGER:
                    LOGGER.error("Failed to save recording:")
                    log_exception(LOGGER, e)
                QtWidgets.QMessageBox.critical(
                    self, "Save Recording", 
                    f"Failed to save recording:\n{e}"
                )
            finally:
                self.recorded_frames = []
    
    # ------------- Other commands -------------
    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.setText("Resume")
        else:
            self.btn_pause.setText("Pause")
        if LOGGER:
            LOGGER.info("Paused = %s", self.paused)

    def _reset_view(self):
        """Reset view to show entire image"""
        if self._last_display_img is not None:
            self.image_view.view.autoRange()
        else:
            QtWidgets.QMessageBox.information(self, "Reset View", "No image loaded yet.")

    def _save_frame(self):
        if self._last_display_img is None:
            QtWidgets.QMessageBox.information(self, "Save Frame", "No image to save yet.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Frame", "", "NumPy Array (*.npy);;PNG Image (*.png);;All Files (*)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".png"):
                from PIL import Image
                img = self._last_display_img.astype(np.float32)
                if self.vmin is not None and self.vmax is not None:
                    img = np.clip((img - self.vmin) / (self.vmax - self.vmin) * 255, 0, 255)
                else:
                    img_min, img_max = img.min(), img.max()
                    if img_max > img_min:
                        img = (img - img_min) / (img_max - img_min) * 255
                    else:
                        img = np.zeros_like(img)
                img = img.astype(np.uint8)
                Image.fromarray(img).save(path)
            else:
                np.save(path, self._last_display_img)
            if LOGGER:
                LOGGER.info("Saved frame to %s", path)
            QtWidgets.QMessageBox.information(self, "Save Frame", f"Saved to:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Frame", f"Failed to save frame:\n{e}")
            if LOGGER:
                LOGGER.error("Failed saving frame to %s", path)
                log_exception(LOGGER, e)

    def _open_motor_scan(self):
        """Open the motor scan dialog"""
        if self.motor_scan_dialog is None:
                self.motor_scan_dialog = MotorScanDialog(parent=self, logger=LOGGER)
        self.motor_scan_dialog.show()
        self.motor_scan_dialog.raise_()
        self.motor_scan_dialog.activateWindow()
  
    def closeEvent(self, event):
        # Stop recording if active
        if self.recording:
            reply = QtWidgets.QMessageBox.question(
                self, "Recording Active",
                f"Recording is active with {len(self.recorded_frames)} frames. Save before closing?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel
            )
            
            if reply == QtWidgets.QMessageBox.Cancel:
                event.ignore()
                return
            elif reply == QtWidgets.QMessageBox.Yes:
                self.btn_record.setChecked(False)
                self._toggle_recording()
        
        try:
            self.cfg["pv_name"] = self.pv_entry.text().strip()
            _save_config(self.cfg)
        except Exception as e:
            if LOGGER:
                LOGGER.error("[Config] Failed to persist PV on close")
                log_exception(LOGGER, e)
        
        try:
            self._disconnect_pv(silent=True)
        except Exception as e:
            if LOGGER:
                LOGGER.warning("Error during disconnect on close:")
                log_exception(LOGGER, e)
        
        # Cleanup ROI
        self.roi_manager.cleanup()
        self.line_manager.cleanup()

	# Clean mosalign
        self.pump_timer.stop()
        if self.motor_scan_dialog:
            self.motor_scan_dialog.close()  # ADD THIS        

        if LOGGER:
            LOGGER.info("Viewer closed")
        event.accept()

# ----------------------- Main -----------------------
def _parse_loglevel(s: Optional[str]) -> int:
    if not s:
        return logging.INFO
    s = s.upper().strip()
    return getattr(logging, s, logging.INFO)


def main():
    global LOGGER
    ap = argparse.ArgumentParser(description="NTNDArray Viewer (PyQtGraph - SSH Compatible)")
    ap.add_argument("--pv", help="PVAccess NTNDArray PV name")
    ap.add_argument("--max-fps", type=int, default=0, help="Max redraw FPS (0 = unthrottled)")
    ap.add_argument("--hist-fps", type=float, default=4.0, help="Histogram updates per second")
    ap.add_argument("--display-bin", type=int, default=0, help="0=auto-decimate; N=fixed decimation")
    ap.add_argument("--auto-every", type=int, default=10, help="Recompute autoscale every N frames")
    ap.add_argument("--proc-config", default="pipelines/processors.json", help="Plugin pipeline JSON")
    ap.add_argument("--no-plugins", action="store_true", help="Disable plugin processing")
    ap.add_argument("--log-file", default=None, help="Optional log file path")
    ap.add_argument("--log-level", default="INFO", help="Logging level")
    args = ap.parse_args()
    
    # Logger
    LOGGER = setup_custom_logger(
        name="pyqtgraph_viewer",
        lfname=args.log_file,
        stream_to_console=True,
        level=_parse_loglevel(args.log_level),
    )
    LOGGER.info("Starting NTNDArray PyQtGraph Viewer (SSH-compatible)")
    LOGGER.info("Args: %s", vars(args))
    
    # Initialize plugins
    if not args.no_plugins:
        _init_pipeline(args.proc_config)
    else:
        LOGGER.info("[Plugins] Disabled via --no-plugins")
    
    # Create Qt application
    app = QtWidgets.QApplication([])
    app.setApplicationName("NTNDArray PyQtGraph Viewer")
    
    # Create viewer window
    viewer = PvViewerApp(
        pv_name=args.pv,
        max_fps=args.max_fps,
        display_bin=args.display_bin,
        hist_fps=args.hist_fps,
        auto_every=args.auto_every
    )
    viewer.show()
    
    try:
        app.exec_()
    except Exception as e:
        LOGGER.critical("Unhandled exception in event loop:")
        log_exception(LOGGER, e)
        raise


if __name__ == "__main__":
    main()
