"""
DataMap plugin for bl32ID.

Two tabs:

  * "Acquisition & Positions" — common acquisition settings, a Mode
                                selector (2D Projection or Tomoscan)
                                with collapsible per-mode settings, and
                                the positions table. Columns are motors
                                (add/remove); rows are positions
                                (add/remove). Every row runs with the
                                same selected mode.
  * "Motor PVs"               — the PV assigned to each motor column.
                                Editing names here updates the column
                                headers in the positions table.

Modes:
  * 2D Projection — move all motors to the row's positions, snap a
                    sample frame, move REF X/Z out, snap a flat,
                    restore X/Z, save to
                    <output_dir>/datamap_rowN_<ts>.h5 under
                    /exchange/data and /exchange/data_flat.
  * Tomoscan     — move motors to the row's positions, then trigger
                   the TomoScan IOC by writing 1 to its StartScan
                   busy record.

Settings persist to ~/.pystream/bl32ID_settings.json under key
"DataMapDialog".
"""

import os
import time
import logging
import subprocess
from typing import Optional, List, Dict, Any

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .plugin_settings import load_settings, save_settings, PYSTREAM_HOME

try:
    from epics import caget, caput
    HAS_EPICS = True
except ImportError:
    HAS_EPICS = False

try:
    import h5py
    HAS_H5PY = True
except ImportError:
    HAS_H5PY = False

try:
    import pvaccess as pva
    HAS_PVA = True
except ImportError:
    HAS_PVA = False


# ── Defaults ─────────────────────────────────────────────────────────────

DEFAULT_MOTORS = [
    {"name": "TopX", "pv": "32idbTXM:mcs:c1:m2"},
    {"name": "TopZ", "pv": "32idbTXM:mcs:c1:m1"},
]

DEFAULT_TOMOSCAN_START_PV = "32id:TomoScan:StartScan"
DEFAULT_DETECTOR_PVA      = "32idbSP1:Pva1:Image"
DEFAULT_CAMERA_PREFIX     = "32idbSP1:cam1:"   # used for Acquire / NumImages
DEFAULT_REF_X_PV          = "32idbTXM:mcs:c1:m2"
DEFAULT_REF_Z_PV          = "32idbTXM:mcs:c1:m1"
DEFAULT_REF_ROT_PV        = "32idbTXM:ens:c1:m1"
DEFAULT_OUTPUT_DIR        = "/tmp"


# ── Collapsible section helper ───────────────────────────────────────────

class _CollapsibleSection(QtWidgets.QWidget):
    """A toggle-button header with a content area that can be collapsed.
    Use ``content_layout`` to add child widgets via QFormLayout API."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; }")
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.RightArrow)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._on_toggled)

        self.content = QtWidgets.QFrame()
        self.content.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.content_layout = QtWidgets.QFormLayout(self.content)
        self.content.setVisible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

    def _on_toggled(self, checked: bool):
        self.toggle.setArrowType(
            QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
        self.content.setVisible(checked)

    def setExpanded(self, expanded: bool):
        self.toggle.setChecked(expanded)


# ── Worker ───────────────────────────────────────────────────────────────

class _DataMapWorker(QtCore.QThread):
    """Runs a queue of (row_index, action) jobs sequentially."""

    log      = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)   # done, total
    done     = QtCore.pyqtSignal()
    error    = QtCore.pyqtSignal(str)

    def __init__(self, jobs, motors, positions, params, parent=None):
        super().__init__(parent)
        self.jobs       = jobs          # [(row_idx, "2d" | "tomo"), ...]
        self.motors     = motors        # [{"name", "pv"}, ...]
        self.positions  = positions     # [[v0, v1, ...], ...] one per row
        self.params     = params
        self._stop      = False

    def stop(self):
        self._stop = True

    # ── EPICS helpers ───────────────────────────────────────────────────

    def _caput(self, pv, val, wait=True, timeout=30.0):
        if not HAS_EPICS:
            raise RuntimeError("pyepics not installed")
        caput(pv, val, wait=wait, timeout=timeout)

    def _caget(self, pv, timeout=3.0):
        if not HAS_EPICS:
            return None
        return caget(pv, timeout=timeout)

    def _move_motor(self, pv, target, settle_s):
        self.log.emit(f"    move {pv} → {target}")
        self._caput(pv, float(target), wait=True, timeout=120.0)
        if settle_s > 0:
            time.sleep(settle_s)

    def _move_all(self, target_values):
        settle = self.params.get("motor_settle_s", 0.1)
        for motor, target in zip(self.motors, target_values):
            if self._stop:
                return
            if target is None or (isinstance(target, str) and target.strip() == ""):
                continue
            self._move_motor(motor["pv"], target, settle)

    # ── Acquisition ─────────────────────────────────────────────────────

    def _snap_frame(self):
        """Snap one frame from the PVA detector and return it as ndarray.
        Falls back to None if PVA isn't installed."""
        if not HAS_PVA:
            self.log.emit("    [WARN] pvaccess not installed; no frame captured")
            return None
        det_pv = self.params["detector_pva"]
        cam    = self.params["camera_prefix"]
        exp    = float(self.params.get("exposure_s", 0.1))

        try:
            self._caput(f"{cam}AcquireTime", exp, wait=False)
            self._caput(f"{cam}ImageMode",   0,   wait=False)  # Single
            self._caput(f"{cam}TriggerMode", 0,   wait=False)  # Internal
        except Exception as e:
            self.log.emit(f"    [WARN] camera config failed: {e}")

        ch = pva.Channel(det_pv)
        # Trigger Acquire
        try:
            self._caput(f"{cam}Acquire", 1, wait=True, timeout=max(5.0, exp * 3 + 5))
        except Exception as e:
            self.log.emit(f"    [WARN] Acquire failed: {e}")

        try:
            st = ch.get()
        except Exception as e:
            self.log.emit(f"    [WARN] PVA get failed: {e}")
            return None
        return self._ndarray_from_struct(st)

    @staticmethod
    def _ndarray_from_struct(st):
        try:
            d = st.toDict()
        except Exception:
            d = {}
        val = d.get("value")
        flat = None
        if isinstance(val, dict):
            for key in val:
                try:
                    flat = np.asarray(val[key])
                    break
                except Exception:
                    pass
        if flat is None:
            return None
        dims = d.get("dimension")
        if isinstance(dims, list) and len(dims) >= 2:
            try:
                h = int(dims[1].get("size"))
                w = int(dims[0].get("size"))
                if h * w == flat.size:
                    return flat.reshape(h, w)
            except Exception:
                pass
        side = int(np.sqrt(flat.size))
        if side * side == flat.size:
            return flat.reshape(side, side)
        return flat

    # ── Per-row actions ─────────────────────────────────────────────────

    def _do_2d(self, row_idx, targets):
        self.log.emit(f"[row {row_idx+1}] 2D image")
        self._move_all(targets)
        if self._stop:
            return
        sample = self._snap_frame()
        if sample is None:
            self.log.emit("    [WARN] no sample frame captured")

        # REF / flat
        ref_x_pv   = self.params.get("ref_x_pv")
        ref_z_pv   = self.params.get("ref_z_pv")
        ref_rot_pv = self.params.get("ref_rot_pv")
        ref_x      = self.params.get("ref_x_mm")
        ref_z      = self.params.get("ref_z_mm")
        ref_rot    = self.params.get("ref_rot_deg")
        # Remember current values so we can return after flat
        cur_x   = self._caget(ref_x_pv)   if ref_x_pv   else None
        cur_z   = self._caget(ref_z_pv)   if ref_z_pv   else None
        cur_rot = self._caget(ref_rot_pv) if ref_rot_pv else None
        settle = self.params.get("motor_settle_s", 0.1)
        if ref_x_pv   and ref_x   is not None:
            self._move_motor(ref_x_pv,   ref_x,   settle)
        if ref_z_pv   and ref_z   is not None:
            self._move_motor(ref_z_pv,   ref_z,   settle)
        if ref_rot_pv and ref_rot is not None:
            self._move_motor(ref_rot_pv, ref_rot, settle)
        flat = self._snap_frame()
        if flat is None:
            self.log.emit("    [WARN] no flat frame captured")
        # Return X/Z/Rot to the row's data position (which the motor loop set)
        if ref_x_pv   and cur_x   is not None:
            self._move_motor(ref_x_pv,   cur_x,   settle)
        if ref_z_pv   and cur_z   is not None:
            self._move_motor(ref_z_pv,   cur_z,   settle)
        if ref_rot_pv and cur_rot is not None:
            self._move_motor(ref_rot_pv, cur_rot, settle)

        if HAS_H5PY:
            out_dir = self.params.get("output_dir", DEFAULT_OUTPUT_DIR)
            os.makedirs(out_dir, exist_ok=True)
            ts   = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(out_dir, f"datamap_row{row_idx+1}_{ts}.h5")
            with h5py.File(path, "w") as f:
                ex = f.create_group("exchange")
                if sample is not None:
                    ex.create_dataset("data",      data=sample[np.newaxis, ...])
                if flat is not None:
                    ex.create_dataset("data_flat", data=flat[np.newaxis, ...])
                meta = f.create_group("measurement/instrument/datamap")
                meta.attrs["row"] = row_idx + 1
                for motor, tgt in zip(self.motors, targets):
                    if tgt is None or (isinstance(tgt, str) and tgt.strip() == ""):
                        continue
                    meta.attrs[f"{motor['name']}_target"] = float(tgt)
                    rbv = self._caget(motor['pv'])
                    if rbv is not None:
                        try:
                            meta.attrs[f"{motor['name']}_rbv"] = float(rbv)
                        except (TypeError, ValueError):
                            pass
            self.log.emit(f"    saved {path}")
        else:
            self.log.emit("    [WARN] h5py not installed; frames not saved")

    def _do_tomo(self, row_idx, targets):
        self.log.emit(f"[row {row_idx+1}] Tomoscan")
        self._move_all(targets)
        if self._stop:
            return
        start_pv = self.params.get("tomo_start_pv", DEFAULT_TOMOSCAN_START_PV)
        wait     = bool(self.params.get("tomo_wait", True))
        self.log.emit(f"    trigger {start_pv} (wait={wait})")
        try:
            timeout = float(self.params.get("tomo_timeout_s", 3600))
            self._caput(start_pv, 1, wait=wait, timeout=timeout)
        except Exception as e:
            raise RuntimeError(f"TomoScan trigger failed: {e}")

    # ── Main loop ───────────────────────────────────────────────────────

    def run(self):
        try:
            total = len(self.jobs)
            for i, (row_idx, action) in enumerate(self.jobs, start=1):
                if self._stop:
                    self.log.emit("Stopped by user.")
                    break
                targets = self.positions[row_idx]
                if action == "2d":
                    self._do_2d(row_idx, targets)
                elif action == "tomo":
                    self._do_tomo(row_idx, targets)
                else:
                    self.log.emit(f"[row {row_idx+1}] unknown action: {action}")
                self.progress.emit(i, total)
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


# ── Dialog ───────────────────────────────────────────────────────────────

class DataMapDialog(QtWidgets.QDialog):
    """Two tabs: (1) Acquisition + Positions table, (2) Motor PVs."""

    BUTTON_TEXT  = "DataMap"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("DataMap — bl32ID")
        self.resize(950, 750)

        self._worker = None
        # Single source of truth for the motor list.
        self._motors: List[Dict[str, str]] = []
        # Per-row positions, kept in sync with self._motors length.
        # Each entry: {"values": [str, ...], "action": "2D Image"}
        self._rows: List[Dict[str, Any]] = []

        # Internal flag to suppress on-edit syncing while we rebuild tables
        # programmatically.
        self._suppress_sync = False

        self._build_ui()
        self._restore_settings()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_main_tab(),   "Acquisition && Positions")
        tabs.addTab(self._build_motors_tab(), "Motor PVs")
        v.addWidget(tabs)

        # Run controls
        run_row = QtWidgets.QHBoxLayout()
        self.run_selected_btn = QtWidgets.QPushButton("Run Selected Row")
        self.run_selected_btn.clicked.connect(self._on_run_selected)
        self.run_all_btn = QtWidgets.QPushButton("Run All")
        self.run_all_btn.clicked.connect(self._on_run_all)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        run_row.addWidget(self.run_selected_btn)
        run_row.addWidget(self.run_all_btn)
        run_row.addWidget(self.stop_btn)
        run_row.addStretch()
        v.addLayout(run_row)

        # Log
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(2000)
        v.addWidget(self.log_text, 1)

        # Footer
        foot = QtWidgets.QHBoxLayout()
        foot.addStretch()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        foot.addWidget(close_btn)
        v.addLayout(foot)

    def _build_main_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        # ── Common acquisition group ───────────────────────────────────
        acq_box = QtWidgets.QGroupBox("Acquisition")
        f = QtWidgets.QFormLayout(acq_box)

        self.detector_pva_edit  = QtWidgets.QLineEdit(DEFAULT_DETECTOR_PVA)
        self.camera_prefix_edit = QtWidgets.QLineEdit(DEFAULT_CAMERA_PREFIX)
        self.exposure_spin = QtWidgets.QDoubleSpinBox()
        self.exposure_spin.setRange(0.001, 60.0)
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setValue(0.1)
        self.settle_spin = QtWidgets.QDoubleSpinBox()
        self.settle_spin.setRange(0.0, 10.0)
        self.settle_spin.setDecimals(2)
        self.settle_spin.setValue(0.1)

        self.output_dir_edit = QtWidgets.QLineEdit(DEFAULT_OUTPUT_DIR)
        browse_btn = QtWidgets.QPushButton("…")
        browse_btn.setMaximumWidth(30)
        browse_btn.clicked.connect(self._browse_output)
        out_row = QtWidgets.QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.addWidget(self.output_dir_edit)
        out_row.addWidget(browse_btn)
        out_w = QtWidgets.QWidget(); out_w.setLayout(out_row)

        f.addRow("Detector PVA channel:",  self.detector_pva_edit)
        f.addRow("Camera prefix:",         self.camera_prefix_edit)
        f.addRow("Exposure [s]:",          self.exposure_spin)
        f.addRow("Motor settle [s]:",      self.settle_spin)
        f.addRow("Output directory:",      out_w)
        v.addWidget(acq_box)

        # ── Mode selector ──────────────────────────────────────────────
        mode_box = QtWidgets.QGroupBox("Mode")
        mh = QtWidgets.QHBoxLayout(mode_box)
        self.mode_2d   = QtWidgets.QRadioButton("2D Projection")
        self.mode_tomo = QtWidgets.QRadioButton("Tomoscan")
        self.mode_2d.setChecked(True)
        mh.addWidget(self.mode_2d)
        mh.addWidget(self.mode_tomo)
        mh.addStretch()
        v.addWidget(mode_box)

        # ── 2D Projection settings (collapsible) ───────────────────────
        self.sec_2d = _CollapsibleSection("2D Projection settings")
        self.ref_x_pv_edit   = QtWidgets.QLineEdit(DEFAULT_REF_X_PV)
        self.ref_z_pv_edit   = QtWidgets.QLineEdit(DEFAULT_REF_Z_PV)
        self.ref_rot_pv_edit = QtWidgets.QLineEdit(DEFAULT_REF_ROT_PV)
        self.ref_x_mm_spin = QtWidgets.QDoubleSpinBox()
        self.ref_x_mm_spin.setRange(-100, 100); self.ref_x_mm_spin.setDecimals(4)
        self.ref_z_mm_spin = QtWidgets.QDoubleSpinBox()
        self.ref_z_mm_spin.setRange(-100, 100); self.ref_z_mm_spin.setDecimals(4)
        self.ref_rot_deg_spin = QtWidgets.QDoubleSpinBox()
        self.ref_rot_deg_spin.setRange(-360, 360); self.ref_rot_deg_spin.setDecimals(3)
        self.sec_2d.content_layout.addRow("Ref X PV:",              self.ref_x_pv_edit)
        self.sec_2d.content_layout.addRow("Ref X position [mm]:",   self.ref_x_mm_spin)
        self.sec_2d.content_layout.addRow("Ref Z PV:",              self.ref_z_pv_edit)
        self.sec_2d.content_layout.addRow("Ref Z position [mm]:",   self.ref_z_mm_spin)
        self.sec_2d.content_layout.addRow("Ref Rotation PV:",       self.ref_rot_pv_edit)
        self.sec_2d.content_layout.addRow("Ref Rotation [deg]:",    self.ref_rot_deg_spin)
        v.addWidget(self.sec_2d)

        # ── Tomoscan settings (collapsible) ────────────────────────────
        self.sec_tomo = _CollapsibleSection("Tomoscan settings")
        self.tomo_start_pv_edit = QtWidgets.QLineEdit(DEFAULT_TOMOSCAN_START_PV)
        self.tomo_wait_chk = QtWidgets.QCheckBox("Wait for scan to finish")
        self.tomo_wait_chk.setChecked(True)
        self.tomo_timeout_spin = QtWidgets.QSpinBox()
        self.tomo_timeout_spin.setRange(60, 24 * 3600)
        self.tomo_timeout_spin.setValue(3600)
        self.tomo_timeout_spin.setSuffix(" s")
        self.sec_tomo.content_layout.addRow("StartScan PV:", self.tomo_start_pv_edit)
        self.sec_tomo.content_layout.addRow("",              self.tomo_wait_chk)
        self.sec_tomo.content_layout.addRow("Timeout:",      self.tomo_timeout_spin)
        v.addWidget(self.sec_tomo)

        # Auto-expand the active mode's section
        def _expand_for_mode():
            self.sec_2d.setExpanded(self.mode_2d.isChecked())
            self.sec_tomo.setExpanded(self.mode_tomo.isChecked())
        self.mode_2d.toggled.connect(lambda _=None: _expand_for_mode())
        self.mode_tomo.toggled.connect(lambda _=None: _expand_for_mode())
        _expand_for_mode()

        # ── Positions group ────────────────────────────────────────────
        pos_box = QtWidgets.QGroupBox("Positions")
        pv = QtWidgets.QVBoxLayout(pos_box)

        self.pos_table = QtWidgets.QTableWidget(0, 0)
        self.pos_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.pos_table.itemChanged.connect(self._on_pos_item_changed)
        pv.addWidget(self.pos_table, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.add_col_btn = QtWidgets.QPushButton("Add Motor Column")
        self.add_col_btn.clicked.connect(self._on_add_motor)
        self.rm_col_btn = QtWidgets.QPushButton("Remove Selected Column")
        self.rm_col_btn.clicked.connect(self._on_remove_selected_motor)
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.VLine)
        self.add_row_btn = QtWidgets.QPushButton("Add Row")
        self.add_row_btn.clicked.connect(lambda: self._on_add_row())
        self.rm_row_btn = QtWidgets.QPushButton("Remove Selected Row")
        self.rm_row_btn.clicked.connect(self._on_remove_row)
        self.cap_row_btn = QtWidgets.QPushButton("Capture Live Values → New Row")
        self.cap_row_btn.clicked.connect(self._on_capture_row)
        btn_row.addWidget(self.add_col_btn)
        btn_row.addWidget(self.rm_col_btn)
        btn_row.addWidget(sep)
        btn_row.addWidget(self.add_row_btn)
        btn_row.addWidget(self.rm_row_btn)
        btn_row.addWidget(self.cap_row_btn)
        btn_row.addStretch()
        pv.addLayout(btn_row)
        v.addWidget(pos_box, 1)
        return w

    def _build_motors_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.motor_table = QtWidgets.QTableWidget(0, 2)
        self.motor_table.setHorizontalHeaderLabels(["Name", "PV"])
        self.motor_table.horizontalHeader().setStretchLastSection(True)
        self.motor_table.itemChanged.connect(self._on_motor_item_changed)
        v.addWidget(self.motor_table, 1)
        return w

    # ── Motor model (single source of truth) ────────────────────────────

    def _add_motor(self, name: str = "", pv: str = ""):
        # Auto-name if blank
        if not name:
            name = f"M{len(self._motors) + 1}"
        self._motors.append({"name": name, "pv": pv})
        for row in self._rows:
            row["values"].append("")
        self._refresh_all_views()

    def _remove_motor_at(self, col: int):
        if not (0 <= col < len(self._motors)):
            return
        self._motors.pop(col)
        for row in self._rows:
            if col < len(row["values"]):
                row["values"].pop(col)
        self._refresh_all_views()

    def _refresh_all_views(self):
        self._suppress_sync = True
        try:
            self._refresh_motor_table()
            self._refresh_position_table()
        finally:
            self._suppress_sync = False

    def _refresh_motor_table(self):
        self.motor_table.setRowCount(0)
        for m in self._motors:
            r = self.motor_table.rowCount()
            self.motor_table.insertRow(r)
            self.motor_table.setItem(r, 0, QtWidgets.QTableWidgetItem(m["name"]))
            self.motor_table.setItem(r, 1, QtWidgets.QTableWidgetItem(m["pv"]))

    def _refresh_position_table(self):
        headers = [m["name"] for m in self._motors]
        self.pos_table.clear()
        self.pos_table.setColumnCount(len(headers))
        self.pos_table.setHorizontalHeaderLabels(headers)
        self.pos_table.setRowCount(0)
        for row in self._rows:
            self._insert_pos_row_widget(row)
        self.pos_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)

    def _insert_pos_row_widget(self, row: Dict[str, Any]):
        r = self.pos_table.rowCount()
        self.pos_table.insertRow(r)
        for c, m in enumerate(self._motors):
            val = ""
            if c < len(row["values"]):
                val = str(row["values"][c])
            self.pos_table.setItem(r, c, QtWidgets.QTableWidgetItem(val))

    # ── Edit-sync handlers ──────────────────────────────────────────────

    def _on_motor_item_changed(self, item: QtWidgets.QTableWidgetItem):
        if self._suppress_sync:
            return
        r, c = item.row(), item.column()
        if not (0 <= r < len(self._motors)):
            return
        text = item.text().strip()
        if c == 0:
            self._motors[r]["name"] = text or f"M{r+1}"
            # Update only the column header to avoid a full rebuild
            self._suppress_sync = True
            try:
                self.pos_table.setHorizontalHeaderItem(
                    r, QtWidgets.QTableWidgetItem(self._motors[r]["name"]))
            finally:
                self._suppress_sync = False
        elif c == 1:
            self._motors[r]["pv"] = text

    def _on_pos_item_changed(self, item: QtWidgets.QTableWidgetItem):
        if self._suppress_sync:
            return
        r, c = item.row(), item.column()
        if c >= len(self._motors):
            return
        while r >= len(self._rows):
            self._rows.append({"values": [""] * len(self._motors)})
        # Pad values list to match motor count
        while len(self._rows[r]["values"]) < len(self._motors):
            self._rows[r]["values"].append("")
        self._rows[r]["values"][c] = item.text()

    # ── Button handlers ─────────────────────────────────────────────────

    def _on_add_motor(self):
        self._add_motor()

    def _on_remove_selected_motor(self):
        c = self.pos_table.currentColumn()
        if c < 0 or c >= len(self._motors):
            # Fall back to selected row in the Motor PVs tab
            c = self.motor_table.currentRow()
        if c < 0:
            QtWidgets.QMessageBox.information(
                self, "Select column",
                "Click a motor column header (or a cell in that column) first.")
            return
        self._remove_motor_at(c)

    def _on_add_row(self):
        self._rows.append({"values": [""] * len(self._motors)})
        self._suppress_sync = True
        try:
            self._insert_pos_row_widget(self._rows[-1])
        finally:
            self._suppress_sync = False

    def _on_remove_row(self):
        r = self.pos_table.currentRow()
        if r < 0:
            return
        if r < len(self._rows):
            self._rows.pop(r)
        self._suppress_sync = True
        try:
            self.pos_table.removeRow(r)
        finally:
            self._suppress_sync = False

    def _on_capture_row(self):
        if not self._motors:
            return
        if not HAS_EPICS:
            QtWidgets.QMessageBox.warning(
                self, "EPICS",
                "pyepics not installed; cannot read live motor values.")
            return
        vals = []
        for m in self._motors:
            try:
                v = caget(m["pv"], timeout=2.0) if m["pv"] else None
            except Exception:
                v = None
            vals.append("" if v is None else f"{float(v):.4f}")
        self._rows.append({"values": vals})
        self._suppress_sync = True
        try:
            self._insert_pos_row_widget(self._rows[-1])
        finally:
            self._suppress_sync = False

    # ── Misc ────────────────────────────────────────────────────────────

    def _browse_output(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Output directory", self.output_dir_edit.text())
        if d:
            self.output_dir_edit.setText(d)

    def _log(self, msg):
        self.log_text.appendPlainText(msg)

    def _params(self) -> Dict[str, Any]:
        return {
            "detector_pva":   self.detector_pva_edit.text().strip(),
            "camera_prefix":  self.camera_prefix_edit.text().strip(),
            "exposure_s":     float(self.exposure_spin.value()),
            "motor_settle_s": float(self.settle_spin.value()),
            "output_dir":     self.output_dir_edit.text().strip(),
            "ref_x_pv":       self.ref_x_pv_edit.text().strip(),
            "ref_z_pv":       self.ref_z_pv_edit.text().strip(),
            "ref_rot_pv":     self.ref_rot_pv_edit.text().strip(),
            "ref_x_mm":       float(self.ref_x_mm_spin.value()),
            "ref_z_mm":       float(self.ref_z_mm_spin.value()),
            "ref_rot_deg":    float(self.ref_rot_deg_spin.value()),
            "tomo_start_pv":  self.tomo_start_pv_edit.text().strip(),
            "tomo_wait":      bool(self.tomo_wait_chk.isChecked()),
            "tomo_timeout_s": int(self.tomo_timeout_spin.value()),
        }

    def _positions_for_run(self) -> List[List[Optional[float]]]:
        out = []
        for row in self._rows:
            parsed = []
            for c in range(len(self._motors)):
                txt = row["values"][c] if c < len(row["values"]) else ""
                txt = str(txt).strip()
                if txt == "":
                    parsed.append(None)
                else:
                    try:
                        parsed.append(float(txt))
                    except ValueError:
                        parsed.append(None)
            out.append(parsed)
        return out

    def _current_mode(self) -> str:
        return "tomo" if self.mode_tomo.isChecked() else "2d"

    # ── Run actions ─────────────────────────────────────────────────────

    def _start_jobs(self, jobs):
        if self._worker and self._worker.isRunning():
            QtWidgets.QMessageBox.warning(
                self, "Busy", "A run is already in progress.")
            return
        motors_with_pv = [m for m in self._motors if m["pv"].strip()]
        if not motors_with_pv:
            QtWidgets.QMessageBox.warning(
                self, "No motors",
                "Assign at least one PV in the Motor PVs tab.")
            return
        if not self._rows:
            QtWidgets.QMessageBox.warning(
                self, "No rows", "Add at least one row in the Positions table.")
            return
        positions = self._positions_for_run()
        params = self._params()
        self._save_settings()

        self._worker = _DataMapWorker(jobs, self._motors, positions, params)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(
            lambda d, t: self._log(f"--- progress {d}/{t} ---"))
        self._worker.done.connect(self._on_worker_done)
        self._worker.error.connect(self._on_worker_error)

        self.run_selected_btn.setEnabled(False)
        self.run_all_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._log(f"Starting {len(jobs)} job(s)")
        self._worker.start()

    def _on_run_selected(self):
        r = self.pos_table.currentRow()
        if r < 0:
            QtWidgets.QMessageBox.information(
                self, "Select row", "Click a row in the Positions table first.")
            return
        mode = self._current_mode()
        self._start_jobs([(r, mode)])

    def _on_run_all(self):
        mode = self._current_mode()
        jobs = [(i, mode) for i in range(len(self._rows))]
        if not jobs:
            return
        self._start_jobs(jobs)

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._log("Stop requested.")

    def _on_worker_done(self):
        self._log("All jobs finished.")
        self._finish()

    def _on_worker_error(self, msg):
        self._log(f"[ERROR] {msg}")
        self._finish()

    def _finish(self):
        self.run_selected_btn.setEnabled(True)
        self.run_all_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Persistence ─────────────────────────────────────────────────────

    def _restore_settings(self):
        s = load_settings(self.__class__.__name__)
        motors = s.get("motors") or DEFAULT_MOTORS
        self._motors = [{"name": m.get("name", f"M{i+1}"),
                         "pv":   m.get("pv", "")}
                        for i, m in enumerate(motors)]
        # Positions stored as list of {values:[...]}
        # (legacy entries may have an "action" key — silently ignored)
        self._rows = []
        for p in s.get("positions", []):
            vals = list(p.get("values", []))
            while len(vals) < len(self._motors):
                vals.append("")
            self._rows.append({"values": vals})

        # Acq settings
        a = s.get("acquisition", {})
        self.detector_pva_edit.setText(a.get("detector_pva",  DEFAULT_DETECTOR_PVA))
        self.camera_prefix_edit.setText(a.get("camera_prefix", DEFAULT_CAMERA_PREFIX))
        self.exposure_spin.setValue(float(a.get("exposure_s", 0.1)))
        self.settle_spin.setValue(float(a.get("motor_settle_s", 0.1)))
        self.output_dir_edit.setText(a.get("output_dir", DEFAULT_OUTPUT_DIR))
        self.ref_x_pv_edit.setText(a.get("ref_x_pv",     DEFAULT_REF_X_PV))
        self.ref_z_pv_edit.setText(a.get("ref_z_pv",     DEFAULT_REF_Z_PV))
        self.ref_rot_pv_edit.setText(a.get("ref_rot_pv", DEFAULT_REF_ROT_PV))
        self.ref_x_mm_spin.setValue(float(a.get("ref_x_mm",   0.0)))
        self.ref_z_mm_spin.setValue(float(a.get("ref_z_mm",   0.0)))
        self.ref_rot_deg_spin.setValue(float(a.get("ref_rot_deg", 0.0)))
        self.tomo_start_pv_edit.setText(a.get("tomo_start_pv", DEFAULT_TOMOSCAN_START_PV))
        self.tomo_wait_chk.setChecked(bool(a.get("tomo_wait", True)))
        self.tomo_timeout_spin.setValue(int(a.get("tomo_timeout_s", 3600)))

        # Mode (default 2D)
        mode = s.get("mode", "2d")
        if mode == "tomo":
            self.mode_tomo.setChecked(True)
        else:
            self.mode_2d.setChecked(True)

        self._refresh_all_views()

    def _save_settings(self):
        save_settings(self.__class__.__name__, {
            "motors":      self._motors,
            "positions":   self._rows,
            "mode":        self._current_mode(),
            "acquisition": self._params(),
        })

    def closeEvent(self, e):
        try:
            self._save_settings()
        except Exception:
            pass
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(e)
