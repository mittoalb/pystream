"""PyQt5 + pyqtgraph GUI for the x-ray source spectrum calculator.

Layout:
    left column   : source selector + machine/ID params, slit params
    middle column : filter stack table (material, thickness, density, on/off)
    right column  : spectrum plot (flux at slit, transmission, filtered flux)

The plot shows three curves:
    - Flux at slit          : source flux integrated over the slit
    - Filter transmission   : product of the stack
    - Filtered flux         : the two multiplied (what reaches the sample)
"""
from __future__ import annotations

import sys
import numpy as np

from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from .bending_magnet import BendingMagnet
from .wiggler import Wiggler
from .undulator import Undulator
from .filters import Filter, FilterStack, _lookup_compound, _density
from .slits import Slit
from .beamline import Beamline, ElectronBeam
from . import materials_store
from .logger import configure_logging, get_logger, QtLogHandler
import logging as _logging

_log = get_logger("xraysource.gui")

pg.setConfigOptions(antialias=True, background="w", foreground="k")


# ----------------------------------------------------------------------
# Presets
# ----------------------------------------------------------------------
MACHINE_PRESETS = {
    "APS-U (6 GeV, 200 mA)":       dict(E_GeV=6.0, current_A=0.200),
    "APS (7 GeV, 100 mA)":         dict(E_GeV=7.0, current_A=0.100),
    "ESRF-EBS (6 GeV, 200 mA)":    dict(E_GeV=6.0, current_A=0.200),
    "PETRA III (6 GeV, 100 mA)":   dict(E_GeV=6.0, current_A=0.100),
    "NSLS-II (3 GeV, 400 mA)":     dict(E_GeV=3.0, current_A=0.400),
    "SPring-8 (8 GeV, 100 mA)":    dict(E_GeV=8.0, current_A=0.100),
    "MAX IV (3 GeV, 500 mA)":      dict(E_GeV=3.0, current_A=0.500),
    "Diamond (3 GeV, 300 mA)":     dict(E_GeV=3.0, current_A=0.300),
    "Custom":                       None,
}


COMMON_FILTERS = [
    ("Be", 1.848, 500.0),
    ("diamond", 3.515, 300.0),
    ("Al", 2.699, 100.0),
    ("Cu", 8.96, 25.0),
    ("Kapton", 1.42, 125.0),
    ("SiO2", 2.20, 500.0),
    ("Mo", 10.28, 25.0),
    ("Sn", 7.31, 100.0),
    ("W", 19.25, 50.0),
    ("Pb", 11.34, 200.0),
    ("H2O", 1.0, 1000.0),
    ("air", 1.204e-3, 1000.0),
]


# ----------------------------------------------------------------------
# Custom materials dialog
# ----------------------------------------------------------------------
class MaterialDialog(QtWidgets.QDialog):
    """Add / edit / delete user materials in ~/.xraysource/materials.json.

    User materials override built-in aliases (shadowing "kapton" with a
    different density is a valid use of this).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom materials")
        self.resize(560, 380)

        v = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Saved to <code>~/.xraysource/materials.json</code>. "
            "Formula uses xraylib syntax (e.g. <code>Fe0.68Cr0.18Ni0.12Mn0.02</code>, "
            "<code>SiO2</code>, <code>C22H10N2O5</code>).")
        info.setWordWrap(True)
        v.addWidget(info)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Formula", "ρ (g/cm³)", "Note"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        v.addWidget(self.table)

        row = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Add row")
        self.add_btn.clicked.connect(lambda: self._append("", "", 0.0, ""))
        row.addWidget(self.add_btn)
        self.del_btn = QtWidgets.QPushButton("Remove selected")
        self.del_btn.clicked.connect(self._remove_selected)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.close_btn)
        v.addLayout(row)

        self._reload()

    def _reload(self):
        self.table.setRowCount(0)
        mats = materials_store.load()
        for name in sorted(mats.keys()):
            m = mats[name]
            self._append(name, m.get("formula", ""),
                          m.get("density_g_cm3", 0.0) or 0.0,
                          m.get("note", ""))

    def _append(self, name, formula, rho, note):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(name)))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(formula)))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{rho:g}"))
        self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(note)))

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                       reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _save(self):
        mats = {}
        errors = []
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 0).text().strip()
            formula = self.table.item(r, 1).text().strip()
            rho_txt = self.table.item(r, 2).text().strip()
            note = (self.table.item(r, 3).text().strip()
                    if self.table.item(r, 3) else "")
            if not name:
                continue
            if not formula:
                errors.append(f"row {r+1} '{name}': missing formula")
                continue
            try:
                rho = float(rho_txt)
            except ValueError:
                errors.append(f"row {r+1} '{name}': bad density {rho_txt!r}")
                continue
            if rho <= 0:
                errors.append(f"row {r+1} '{name}': density must be > 0")
                continue
            # Validate the formula parses
            try:
                _lookup_compound(formula)
            except Exception as exc:
                errors.append(f"row {r+1} '{name}': formula {formula!r}: {exc}")
                continue
            mats[name] = {
                "formula": formula,
                "density_g_cm3": rho,
                "note": note,
            }
        if errors:
            QtWidgets.QMessageBox.warning(
                self, "Cannot save",
                "Fix these before saving:\n\n" + "\n".join(errors))
            return
        materials_store.save(mats)
        self.accept()


# ----------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------
class MachinePanel(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Storage ring", parent)
        lay = QtWidgets.QFormLayout(self)

        self.preset = QtWidgets.QComboBox()
        self.preset.addItems(list(MACHINE_PRESETS.keys()))
        self.preset.currentTextChanged.connect(self._apply_preset)
        lay.addRow("Preset:", self.preset)

        self.E_GeV = QtWidgets.QDoubleSpinBox()
        self.E_GeV.setRange(0.1, 20.0); self.E_GeV.setDecimals(3)
        self.E_GeV.setSingleStep(0.1); self.E_GeV.setValue(6.0)
        self.E_GeV.setSuffix(" GeV")
        lay.addRow("Electron energy:", self.E_GeV)

        self.current_mA = QtWidgets.QDoubleSpinBox()
        self.current_mA.setRange(0.1, 1000.0); self.current_mA.setDecimals(1)
        self.current_mA.setValue(200.0); self.current_mA.setSuffix(" mA")
        lay.addRow("Ring current:", self.current_mA)

        self.energy_spread = QtWidgets.QDoubleSpinBox()
        self.energy_spread.setRange(0.0, 1e-2); self.energy_spread.setDecimals(6)
        self.energy_spread.setValue(1.0e-3)
        self.energy_spread.setSuffix(" (dE/E rms)")
        lay.addRow("Energy spread:", self.energy_spread)

        # Electron beam emittance (source size + divergence) — blurs the 2D
        # beam profile at the observation plane
        self.sigma_x = QtWidgets.QDoubleSpinBox()
        self.sigma_x.setRange(0.0, 5000.0); self.sigma_x.setDecimals(2)
        self.sigma_x.setValue(15.0); self.sigma_x.setSuffix(" µm rms")
        self.sigma_x.setToolTip("Horizontal electron-beam size at source (rms)")
        lay.addRow("σ<sub>x</sub> (H size):", self.sigma_x)
        self.sigma_y = QtWidgets.QDoubleSpinBox()
        self.sigma_y.setRange(0.0, 5000.0); self.sigma_y.setDecimals(2)
        self.sigma_y.setValue(8.0); self.sigma_y.setSuffix(" µm rms")
        self.sigma_y.setToolTip("Vertical electron-beam size at source (rms)")
        lay.addRow("σ<sub>y</sub> (V size):", self.sigma_y)
        self.sigma_xp = QtWidgets.QDoubleSpinBox()
        self.sigma_xp.setRange(0.0, 1000.0); self.sigma_xp.setDecimals(3)
        self.sigma_xp.setValue(3.0); self.sigma_xp.setSuffix(" µrad rms")
        self.sigma_xp.setToolTip("Horizontal electron-beam angular divergence (rms)")
        lay.addRow("σ<sub>x'</sub> (H div):", self.sigma_xp)
        self.sigma_yp = QtWidgets.QDoubleSpinBox()
        self.sigma_yp.setRange(0.0, 1000.0); self.sigma_yp.setDecimals(3)
        self.sigma_yp.setValue(1.5); self.sigma_yp.setSuffix(" µrad rms")
        self.sigma_yp.setToolTip("Vertical electron-beam angular divergence (rms)")
        lay.addRow("σ<sub>y'</sub> (V div):", self.sigma_yp)

        for w in (self.E_GeV, self.current_mA, self.energy_spread,
                   self.sigma_x, self.sigma_y, self.sigma_xp, self.sigma_yp):
            w.valueChanged.connect(self.changed)

    def _apply_preset(self, name):
        p = MACHINE_PRESETS.get(name)
        if not p:
            return
        self.E_GeV.blockSignals(True)
        self.current_mA.blockSignals(True)
        self.E_GeV.setValue(p["E_GeV"])
        self.current_mA.setValue(p["current_A"] * 1000)
        self.E_GeV.blockSignals(False)
        self.current_mA.blockSignals(False)
        self.changed.emit()

    def values(self):
        return dict(
            E_GeV=self.E_GeV.value(),
            current_A=self.current_mA.value() * 1e-3,
            energy_spread=self.energy_spread.value(),
            ebeam=ElectronBeam(
                sigma_x_um=self.sigma_x.value(),
                sigma_y_um=self.sigma_y.value(),
                sigma_xp_urad=self.sigma_xp.value(),
                sigma_yp_urad=self.sigma_yp.value(),
            ),
        )


class SourcePanel(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Source", parent)
        v = QtWidgets.QVBoxLayout(self)

        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["Bending magnet", "Wiggler", "Undulator"])
        self.kind.currentIndexChanged.connect(self._switch)
        v.addWidget(self.kind)

        self.stack = QtWidgets.QStackedWidget()
        v.addWidget(self.stack)

        # ---- BM page ----
        bm_page = QtWidgets.QWidget(); bmf = QtWidgets.QFormLayout(bm_page)
        self.bm_B = QtWidgets.QDoubleSpinBox()
        self.bm_B.setRange(0.01, 15.0); self.bm_B.setDecimals(4)
        self.bm_B.setSingleStep(0.05); self.bm_B.setValue(0.60)
        self.bm_B.setSuffix(" T")
        bmf.addRow("Field B:", self.bm_B)
        self.stack.addWidget(bm_page)

        # ---- Wiggler page ----
        wg_page = QtWidgets.QWidget(); wgf = QtWidgets.QFormLayout(wg_page)
        self.wg_period = QtWidgets.QDoubleSpinBox()
        self.wg_period.setRange(1.0, 500.0); self.wg_period.setDecimals(2)
        self.wg_period.setValue(85.0); self.wg_period.setSuffix(" mm")
        wgf.addRow("Period:", self.wg_period)
        self.wg_N = QtWidgets.QSpinBox()
        self.wg_N.setRange(1, 500); self.wg_N.setValue(28)
        wgf.addRow("N periods:", self.wg_N)
        self.wg_B = QtWidgets.QDoubleSpinBox()
        self.wg_B.setRange(0.01, 15.0); self.wg_B.setDecimals(4)
        self.wg_B.setSingleStep(0.05); self.wg_B.setValue(1.5)
        self.wg_B.setSuffix(" T")
        wgf.addRow("Peak field B:", self.wg_B)
        self.stack.addWidget(wg_page)

        # ---- Undulator page ----
        un_page = QtWidgets.QWidget(); unf = QtWidgets.QFormLayout(un_page)
        self.un_period = QtWidgets.QDoubleSpinBox()
        self.un_period.setRange(1.0, 500.0); self.un_period.setDecimals(2)
        self.un_period.setValue(33.0); self.un_period.setSuffix(" mm")
        unf.addRow("Period:", self.un_period)
        self.un_N = QtWidgets.QSpinBox()
        self.un_N.setRange(1, 500); self.un_N.setValue(72)
        unf.addRow("N periods:", self.un_N)
        self.un_K = QtWidgets.QDoubleSpinBox()
        self.un_K.setRange(0.01, 20.0); self.un_K.setDecimals(4)
        self.un_K.setSingleStep(0.05); self.un_K.setValue(2.50)
        unf.addRow("K:", self.un_K)
        self.un_max_h = QtWidgets.QSpinBox()
        self.un_max_h.setRange(1, 51); self.un_max_h.setValue(15)
        unf.addRow("Max harmonic:", self.un_max_h)
        self.stack.addWidget(un_page)

        for w in (self.bm_B,
                  self.wg_period, self.wg_N, self.wg_B,
                  self.un_period, self.un_N, self.un_K, self.un_max_h):
            (w.valueChanged if hasattr(w, "valueChanged") else w.currentIndexChanged).connect(self.changed)

    def _switch(self, i):
        self.stack.setCurrentIndex(i)
        self.changed.emit()

    def build_source(self, machine):
        kind = self.kind.currentText()
        E_GeV = machine["E_GeV"]
        I_A = machine["current_A"]
        if kind == "Bending magnet":
            return BendingMagnet(E_GeV=E_GeV, current_A=I_A,
                                 B_T=self.bm_B.value())
        if kind == "Wiggler":
            return Wiggler(E_GeV=E_GeV, current_A=I_A,
                           period_mm=self.wg_period.value(),
                           N_periods=self.wg_N.value(),
                           B_T=self.wg_B.value())
        return Undulator(E_GeV=E_GeV, current_A=I_A,
                         period_mm=self.un_period.value(),
                         N_periods=self.un_N.value(),
                         K=self.un_K.value(),
                         energy_spread=machine["energy_spread"],
                         max_harmonic=self.un_max_h.value())


class SlitPanel(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Slit / aperture", parent)
        f = QtWidgets.QFormLayout(self)
        self.dist = QtWidgets.QDoubleSpinBox()
        self.dist.setRange(0.1, 1000.0); self.dist.setDecimals(3)
        self.dist.setValue(30.0); self.dist.setSuffix(" m")
        f.addRow("Distance from source:", self.dist)
        self.hmm = QtWidgets.QDoubleSpinBox()
        self.hmm.setRange(0.001, 500.0); self.hmm.setDecimals(3)
        self.hmm.setValue(1.0); self.hmm.setSuffix(" mm (H)")
        f.addRow("Slit H:", self.hmm)
        self.vmm = QtWidgets.QDoubleSpinBox()
        self.vmm.setRange(0.001, 500.0); self.vmm.setDecimals(3)
        self.vmm.setValue(1.0); self.vmm.setSuffix(" mm (V)")
        f.addRow("Slit V:", self.vmm)
        self.hoff = QtWidgets.QDoubleSpinBox()
        self.hoff.setRange(-500.0, 500.0); self.hoff.setDecimals(3)
        self.hoff.setSuffix(" mm")
        f.addRow("H offset:", self.hoff)
        self.voff = QtWidgets.QDoubleSpinBox()
        self.voff.setRange(-500.0, 500.0); self.voff.setDecimals(3)
        self.voff.setSuffix(" mm")
        f.addRow("V offset:", self.voff)
        self.nsamp = QtWidgets.QSpinBox()
        self.nsamp.setRange(3, 51); self.nsamp.setValue(11)
        f.addRow("Integration pts/axis:", self.nsamp)
        for w in (self.dist, self.hmm, self.vmm, self.hoff, self.voff, self.nsamp):
            w.valueChanged.connect(self.changed)

    def build_slit(self):
        return Slit(distance_m=self.dist.value(),
                    h_mm=self.hmm.value(), v_mm=self.vmm.value(),
                    h_offset_mm=self.hoff.value(),
                    v_offset_mm=self.voff.value())


class FilterTable(QtWidgets.QGroupBox):
    """Filter stack editor: material, thickness (um), density (g/cm^3), on/off."""
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Filter stack", parent)
        v = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox()
        self._refresh_combo()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        row.addWidget(self.combo, 1)
        self.add_btn = QtWidgets.QPushButton("Add")
        self.add_btn.clicked.connect(self._add_from_combo)
        row.addWidget(self.add_btn)
        self.del_btn = QtWidgets.QPushButton("Remove")
        self.del_btn.clicked.connect(self._remove_selected)
        row.addWidget(self.del_btn)
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)
        v.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.manage_btn = QtWidgets.QPushButton("Manage custom materials…")
        self.manage_btn.clicked.connect(self._manage_materials)
        row2.addWidget(self.manage_btn)
        row2.addStretch(1)
        v.addLayout(row2)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["On", "Material", "Thickness (µm)", "ρ (g/cm³)"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._row_changed)
        v.addWidget(self.table)

    def _refresh_combo(self):
        """(Re)populate the material dropdown from built-ins + user store."""
        self.combo.blockSignals(True)
        current_text = self.combo.currentText() if self.combo.count() else ""
        self.combo.clear()
        for name, rho, t in COMMON_FILTERS:
            self.combo.addItem(f"{name} ({t:g} um)", (name, rho, t))
        user_mats = materials_store.load()
        if user_mats:
            self.combo.insertSeparator(self.combo.count())
            for name in sorted(user_mats.keys()):
                m = user_mats[name]
                rho = m.get("density_g_cm3") or 1.0
                self.combo.addItem(f"[user] {name} (100 um)",
                                   (name, rho, 100.0))
        if current_text:
            self.combo.setEditText(current_text)
        self.combo.blockSignals(False)

    def _manage_materials(self):
        dlg = MaterialDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._refresh_combo()
            # Refresh densities of rows whose name is now a user material
            for r in range(self.table.rowCount()):
                name = self.table.item(r, 1).text().strip()
                try:
                    cd = _lookup_compound(name)
                    rho = _density(name, cd)
                    self.table.blockSignals(True)
                    self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{rho:g}"))
                    self.table.blockSignals(False)
                except Exception:
                    pass
            self.changed.emit()

    def _add_from_combo(self):
        data = self.combo.currentData()
        if data is None:
            # Manual entry: parse "name (thickness um)" or just "name"
            txt = self.combo.currentText().strip()
            try:
                if "(" in txt and "um" in txt:
                    name = txt.split("(")[0].strip()
                    t = float(txt.split("(")[1].split("um")[0])
                else:
                    name = txt; t = 100.0
                cd = _lookup_compound(name)
                rho = _density(name, cd)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Unknown material", str(exc))
                return
        else:
            name, rho, t = data
        self._append_row(name, t, rho, True)

    def _append_row(self, name, thickness_um, rho, enabled):
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        chk = QtWidgets.QTableWidgetItem()
        chk.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
        chk.setCheckState(QtCore.Qt.Checked if enabled else QtCore.Qt.Unchecked)
        self.table.setItem(r, 0, chk)
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{thickness_um:g}"))
        self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{rho:g}"))
        self.table.blockSignals(False)
        self.changed.emit()

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.changed.emit()

    def _clear(self):
        self.table.setRowCount(0)
        self.changed.emit()

    def _row_changed(self, item):
        # If material name changed, re-resolve density
        if item.column() == 1:
            r = item.row()
            name = item.text().strip()
            try:
                cd = _lookup_compound(name)
                rho = _density(name, cd)
                self.table.blockSignals(True)
                self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{rho:g}"))
                self.table.blockSignals(False)
            except Exception:
                pass
        self.changed.emit()

    def build_stack(self):
        stack = FilterStack()
        for r in range(self.table.rowCount()):
            enabled = self.table.item(r, 0).checkState() == QtCore.Qt.Checked
            name = self.table.item(r, 1).text().strip()
            try:
                t = float(self.table.item(r, 2).text())
                rho = float(self.table.item(r, 3).text())
                stack.filters.append(Filter(name, t, rho, enabled))
            except Exception:
                continue
        return stack


class BeamProfilePanel(QtWidgets.QWidget):
    """2D beam intensity on a plane at a chosen distance.

    Renders `Beamline.beam_2d(...)` as a pyqtgraph ImageView with axis
    tickmarks in mm and a colorbar. The user can toggle between a
    single-energy map and a band-integrated map.
    """
    calculate_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        # ---- toolbar row 1: compute + observation plane (prominent) ----
        row = QtWidgets.QHBoxLayout()
        self.calc_btn = QtWidgets.QPushButton("Compute 2D beam")
        self.calc_btn.setStyleSheet(
            "QPushButton { background-color: #2c7be5; color: white; "
            "font-weight: bold; padding: 6px 14px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1a5fc5; }")
        self.calc_btn.clicked.connect(self.calculate_requested)
        row.addWidget(self.calc_btn)

        row.addSpacing(20)
        obs_lbl = QtWidgets.QLabel("Observation plane distance:")
        obs_lbl.setStyleSheet("font-weight: bold; color: #c04020;")
        obs_lbl.setToolTip(
            "Distance from the source to the plane where the beam is\n"
            "observed. This is INDEPENDENT of the slit distance (set in\n"
            "the Slit / aperture panel on the left). If this plane is\n"
            "upstream of the slit, the beam is not yet clipped.")
        row.addWidget(obs_lbl)
        self.plane_m = QtWidgets.QDoubleSpinBox()
        self.plane_m.setRange(0.1, 1000.0); self.plane_m.setDecimals(3)
        self.plane_m.setValue(40.0); self.plane_m.setSuffix(" m")
        self.plane_m.setMinimumWidth(110)
        self.plane_m.setStyleSheet("font-weight: bold;")
        self.plane_m.setToolTip(obs_lbl.toolTip())
        row.addWidget(self.plane_m)

        row.addSpacing(20)
        row.addWidget(QtWidgets.QLabel("View range:"))
        self.range_mm = QtWidgets.QDoubleSpinBox()
        self.range_mm.setRange(0.01, 500.0); self.range_mm.setDecimals(3)
        self.range_mm.setValue(3.0); self.range_mm.setSuffix(" mm ±")
        self.range_mm.setToolTip("Half-width of the plotted view around (0,0)")
        row.addWidget(self.range_mm)

        row.addWidget(QtWidgets.QLabel("Grid:"))
        self.grid_n = QtWidgets.QSpinBox()
        self.grid_n.setRange(11, 401); self.grid_n.setValue(101)
        self.grid_n.setToolTip("Pixels per axis")
        row.addWidget(self.grid_n)

        row.addStretch(1)
        self.export_btn = QtWidgets.QPushButton("Export TIFF…")
        row.addWidget(self.export_btn)
        v.addLayout(row)

        # ---- toolbar row 2: energy + display options ----
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("Energy:"))
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["single E", "band integral"])
        row2.addWidget(self.mode)
        self.e_lo = QtWidgets.QDoubleSpinBox()
        self.e_lo.setRange(0.05, 2000.0); self.e_lo.setDecimals(3)
        self.e_lo.setValue(20.0); self.e_lo.setSuffix(" keV")
        row2.addWidget(self.e_lo)
        self.e_hi = QtWidgets.QDoubleSpinBox()
        self.e_hi.setRange(0.05, 2000.0); self.e_hi.setDecimals(3)
        self.e_hi.setValue(30.0); self.e_hi.setSuffix(" keV")
        row2.addWidget(self.e_hi)
        self.e_n = QtWidgets.QSpinBox()
        self.e_n.setRange(2, 5000); self.e_n.setValue(400)
        self.e_n.setPrefix("N=")
        self.e_n.setToolTip(
            "Number of energy samples across the band. "
            "For undulators, beam_2d auto-densifies to resolve harmonic peaks "
            "(~30 eV wide); values below the auto-minimum are silently raised.")
        row2.addWidget(self.e_n)
        row2.addStretch(1)
        self.energy_map_cb = QtWidgets.QCheckBox("energy map")
        self.energy_map_cb.setToolTip(
            "Undulator only: colour each pixel by the red-shifted resonance "
            "energy E_n(θ) of the dominant harmonic at that angle.")
        row2.addWidget(self.energy_map_cb)
        self.log_cb = QtWidgets.QCheckBox("log color"); self.log_cb.setChecked(False)
        row2.addWidget(self.log_cb)
        v.addLayout(row2)
        self._toggle_band(False)
        self.mode.currentIndexChanged.connect(
            lambda i: self._toggle_band(i == 1))

        # ---- image view ----
        self.image_view = pg.ImageView(view=pg.PlotItem())
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        vb = self.image_view.getView()
        vb.setLabel("bottom", "x (mm)")
        vb.setLabel("left", "y (mm)")
        vb.setAspectLocked(True)
        v.addWidget(self.image_view, 1)

        # ---- info line ----
        self.info = QtWidgets.QLabel(" ")
        self.info.setStyleSheet("font-family: monospace;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        self._img = None; self._extent = None

    def _toggle_band(self, on):
        self.e_hi.setVisible(on)
        self.e_n.setVisible(on)

    def update_image(self, img, extent, info_text,
                     unit_label=None, colormap=None):
        self._img = img; self._extent = extent
        arr = np.asarray(img, dtype=float).T   # (nx, ny) for pyqtgraph
        if self.log_cb.isChecked() and (colormap is None):
            fin = np.isfinite(arr) & (arr > 0)
            if fin.any():
                m = arr[fin].max()
                arr = np.where(fin, np.log10(np.maximum(arr, m * 1e-6)), np.nan)
        xmin, xmax, ymin, ymax = extent
        pos = (xmin, ymin)
        scale = ((xmax - xmin) / max(arr.shape[0] - 1, 1),
                  (ymax - ymin) / max(arr.shape[1] - 1, 1))
        # Colormap: viridis for energy map, gray for intensity
        try:
            self.image_view.setColorMap(pg.colormap.get(colormap or "gray"))
        except Exception:
            pass
        # Levels: use only finite pixels so NaN doesn't skew autoLevels
        fin = np.isfinite(arr)
        if fin.any():
            lo, hi = float(arr[fin].min()), float(arr[fin].max())
            if hi <= lo:
                hi = lo + 1.0
            self.image_view.setImage(arr, autoLevels=False, autoRange=True,
                                      pos=pos, scale=scale, levels=(lo, hi))
        else:
            self.image_view.setImage(arr, autoLevels=True, autoRange=True,
                                      pos=pos, scale=scale)
        # Zoom the view to the bounding box of non-NaN pixels (with a
        # small margin). This makes the energy map immediately visible
        # even when the view range is much larger than the slit shadow.
        if fin.any():
            # find x/y bounding box of finite values
            row_ok = fin.any(axis=1)   # per-x (arr is (nx, ny))
            col_ok = fin.any(axis=0)   # per-y
            ix0, ix1 = np.where(row_ok)[0][[0, -1]]
            iy0, iy1 = np.where(col_ok)[0][[0, -1]]
            x0 = xmin + ix0 * scale[0]; x1 = xmin + ix1 * scale[0]
            y0 = ymin + iy0 * scale[1]; y1 = ymin + iy1 * scale[1]
            mx = 0.15 * max(x1 - x0, scale[0])
            my = 0.15 * max(y1 - y0, scale[1])
            self.image_view.getView().setRange(
                xRange=(x0 - mx, x1 + mx),
                yRange=(y0 - my, y1 + my),
                padding=0.0)
        self.info.setText(info_text)


class PlotPanel(QtWidgets.QWidget):
    """Two stacked plots sharing the X axis:
        top    : flux at slit (blue) + filtered flux (red), log-log
        bottom : filter transmission (green), linear 0..1
    """
    calculate_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        # ---- toolbar ----
        row = QtWidgets.QHBoxLayout()
        self.calc_btn = QtWidgets.QPushButton("Calculate")
        self.calc_btn.setStyleSheet(
            "QPushButton { background-color: #2c7be5; color: white; "
            "font-weight: bold; padding: 6px 14px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1a5fc5; }"
            "QPushButton:pressed { background-color: #12468f; }")
        self.calc_btn.clicked.connect(self.calculate_requested)
        row.addWidget(self.calc_btn)

        self.autocalc = QtWidgets.QCheckBox("auto")
        self.autocalc.setChecked(True)
        self.autocalc.setToolTip("Recompute automatically when parameters change")
        row.addWidget(self.autocalc)

        row.addSpacing(15)
        row.addWidget(QtWidgets.QLabel("E:"))
        self.e_min = QtWidgets.QDoubleSpinBox()
        self.e_min.setRange(0.05, 1000.0); self.e_min.setDecimals(3)
        self.e_min.setValue(1.0); self.e_min.setSuffix(" keV")
        row.addWidget(self.e_min)
        row.addWidget(QtWidgets.QLabel("–"))
        self.e_max = QtWidgets.QDoubleSpinBox()
        self.e_max.setRange(0.1, 2000.0); self.e_max.setDecimals(3)
        self.e_max.setValue(100.0); self.e_max.setSuffix(" keV")
        row.addWidget(self.e_max)
        row.addWidget(QtWidgets.QLabel("N:"))
        self.n_pts = QtWidgets.QSpinBox()
        self.n_pts.setRange(50, 20000); self.n_pts.setValue(800)
        row.addWidget(self.n_pts)
        self.log_e = QtWidgets.QCheckBox("log E"); self.log_e.setChecked(True)
        row.addWidget(self.log_e)
        self.log_y = QtWidgets.QCheckBox("log flux"); self.log_y.setChecked(True)
        row.addWidget(self.log_y)
        row.addStretch(1)
        self.export_btn = QtWidgets.QPushButton("Export CSV…")
        row.addWidget(self.export_btn)
        v.addLayout(row)

        # ---- two stacked plots, X-linked ----
        self._glw = pg.GraphicsLayoutWidget()
        v.addWidget(self._glw, 1)

        self.plot_flux = self._glw.addPlot(row=0, col=0)
        self.plot_flux.showGrid(x=True, y=True, alpha=0.3)
        self.plot_flux.setLabel("left", "Flux [ph/s/0.1%BW]")
        self.plot_flux.addLegend(offset=(-10, 10))
        self._c_slit = self.plot_flux.plot(
            pen=pg.mkPen(color=(0, 100, 180), width=2), name="flux @ slit")
        self._c_out = self.plot_flux.plot(
            pen=pg.mkPen(color=(200, 40, 40), width=2), name="filtered flux")

        self.plot_trans = self._glw.addPlot(row=1, col=0)
        self.plot_trans.showGrid(x=True, y=True, alpha=0.3)
        self.plot_trans.setLabel("left", "Transmission")
        self.plot_trans.setLabel("bottom", "Photon energy", units="keV")
        self.plot_trans.setYRange(0.0, 1.05)
        self._c_trans = self.plot_trans.plot(
            pen=pg.mkPen(color=(30, 140, 30), width=2))

        self.plot_trans.setXLink(self.plot_flux)
        self.plot_flux.getAxis("bottom").setStyle(showValues=False)

        # 2:1 vertical split
        self._glw.ci.layout.setRowStretchFactor(0, 2)
        self._glw.ci.layout.setRowStretchFactor(1, 1)

        self.plot_flux.setLogMode(x=True, y=True)
        self.plot_trans.setLogMode(x=True, y=False)

        # ---- info line ----
        self.info = QtWidgets.QLabel(" ")
        self.info.setStyleSheet("font-family: monospace;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        self.log_e.toggled.connect(self._apply_log)
        self.log_y.toggled.connect(self._apply_log)

        self._E = None; self._F = None; self._T = None; self._F0 = None

    def _apply_log(self):
        lx = self.log_e.isChecked()
        ly = self.log_y.isChecked()
        self.plot_flux.setLogMode(x=lx, y=ly)
        self.plot_trans.setLogMode(x=lx, y=False)

    def update_curves(self, E, F, T, F0):
        self._E, self._F, self._T, self._F0 = E, F, T, F0
        eps = 1e-30
        self._c_slit.setData(E, np.maximum(F0, eps))
        self._c_out.setData(E, np.maximum(F, eps))
        self._c_trans.setData(E, np.clip(T, 0.0, 1.05))
        finite = np.isfinite(F0) & (F0 > 0)
        if finite.any():
            fmax = float(F0[finite].max())
            fmin = max(fmax * 1e-8, 1e-6)
            if self.log_y.isChecked():
                self.plot_flux.setYRange(np.log10(fmin), np.log10(fmax * 3.0))
            else:
                self.plot_flux.setYRange(0, fmax * 1.1)
        self.plot_trans.setYRange(0.0, 1.05)


# ----------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("X-ray source spectrum calculator")
        self.resize(1400, 850)

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        h = QtWidgets.QHBoxLayout(central)

        # Left column: machine + source + slit
        left = QtWidgets.QVBoxLayout()
        self.machine = MachinePanel()
        self.source = SourcePanel()
        self.slit = SlitPanel()
        left.addWidget(self.machine)
        left.addWidget(self.source)
        left.addWidget(self.slit)
        left.addStretch(1)
        lw = QtWidgets.QWidget(); lw.setLayout(left); lw.setMaximumWidth(360)
        h.addWidget(lw)

        # Middle column: filters
        self.filters = FilterTable()
        self.filters.setMinimumWidth(360); self.filters.setMaximumWidth(460)
        h.addWidget(self.filters)

        # Right column: tabs (Spectrum + Beam profile)
        self.tabs = QtWidgets.QTabWidget()
        self.plot = PlotPanel()
        self.beam = BeamProfilePanel()
        self.tabs.addTab(self.plot, "Spectrum")
        self.tabs.addTab(self.beam, "Beam profile (2D)")
        h.addWidget(self.tabs, 1)

        # Debounced replot (only fires when "auto" is on)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recompute)
        for w in (self.machine, self.source, self.slit, self.filters):
            w.changed.connect(self._schedule)
        for w in (self.plot.e_min, self.plot.e_max, self.plot.n_pts):
            w.valueChanged.connect(self._schedule)
        self.plot.export_btn.clicked.connect(self._export)
        # Explicit Calculate button (always works, ignores auto toggle)
        self.plot.calculate_requested.connect(self.recompute)
        # Ctrl+R / F5 also trigger a recompute
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+R"), self, self.recompute)
        QtWidgets.QShortcut(QtGui.QKeySequence("F5"), self, self.recompute)

        # Beam tab: only computes on demand (2D is expensive)
        self.beam.calc_btn.clicked.connect(self.recompute_beam2d)
        self.beam.export_btn.clicked.connect(self._export_beam2d)
        # Gray out "energy map" when the source doesn't support it
        self.source.changed.connect(self._update_beam_controls)
        self._update_beam_controls()

        # Seed the filter stack with a typical APS front-end
        self.filters._append_row("Be", 500.0, 1.848, True)
        self.filters._append_row("diamond", 300.0, 3.515, True)

        # Status + menu
        self._status = self.statusBar()
        self._status.showMessage("Press Calculate (or Ctrl+R / F5) to compute the spectrum.")
        self._build_menu()
        self._install_log_bridge()

        # Compute once at startup, after the window is shown, so pyqtgraph
        # has real widget sizes to render into.
        QtCore.QTimer.singleShot(50, self.recompute)

    def _schedule(self):
        if self.plot.autocalc.isChecked():
            self._timer.start()

    def recompute(self):
        try:
            machine = self.machine.values()
            src = self.source.build_source(machine)
            slit = self.slit.build_slit()
            slit_n = self.slit.nsamp.value()
            filt = self.filters.build_stack()
            bl = Beamline(source=src, slit=slit, filters=filt, n_theta=slit_n)
            E_min = self.plot.e_min.value()
            E_max = max(self.plot.e_max.value(), E_min + 0.1)
            n = self.plot.n_pts.value()
            E, F, T, F0 = bl.spectrum(E_min_keV=E_min, E_max_keV=E_max,
                                       n=n, log=self.plot.log_e.isChecked())
            self.plot.update_curves(E, F, T, F0)
            # Info line
            try:
                P_slit = bl.power_W(E_min_keV=max(0.1, E_min),
                                     E_max_keV=E_max, n=1000)
            except Exception:
                P_slit = float("nan")
            F_peak = float(np.nanmax(F))
            E_peak = float(E[np.nanargmax(F)])
            msg = (f"Source: {src.__class__.__name__}   "
                   f"Slit accept: {slit.h_accept_mrad()*1e3:.1f}×{slit.v_accept_mrad()*1e3:.1f} µrad   "
                   f"Peak filtered flux: {F_peak:.2e} @ {E_peak:.2f} keV   "
                   f"Power (E_min→E_max): {P_slit*1e3:.2f} mW")
            self.plot.info.setText(msg)
            self._status.showMessage("OK", 1500)
        except Exception as exc:
            self._status.showMessage(f"Error: {exc}", 5000)
            import traceback; traceback.print_exc()

    def _export(self):
        if self.plot._E is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save spectrum as CSV", "spectrum.csv", "CSV (*.csv)")
        if not path:
            return
        arr = np.column_stack([self.plot._E, self.plot._F0,
                                self.plot._T, self.plot._F])
        np.savetxt(path, arr, delimiter=",",
                    header="E_keV,flux_at_slit_ph_s_0.1%BW,transmission,filtered_flux_ph_s_0.1%BW",
                    comments="")
        self._status.showMessage(f"Saved {path}", 3000)

    # ---- menu + logging --------------------------------------------
    def _build_menu(self):
        mb = self.menuBar()
        m_view = mb.addMenu("&View")
        m_log = m_view.addMenu("Log &level")
        self._log_actions = {}
        cur = _logging.getLevelName(get_logger().level or _logging.INFO)
        group = QtWidgets.QActionGroup(self); group.setExclusive(True)
        for name in ("DEBUG", "INFO", "WARNING", "ERROR"):
            act = QtWidgets.QAction(name, self, checkable=True)
            act.setChecked(name == cur)
            act.triggered.connect(lambda _c, n=name: self._set_log_level(n))
            group.addAction(act)
            m_log.addAction(act)
            self._log_actions[name] = act

    def _set_log_level(self, name):
        configure_logging(level=name)
        _log.info("log level -> %s", name)

    def _install_log_bridge(self):
        """Forward WARNING+ records to the status bar (colour applied)."""
        def cb(level, text):
            # Strip ANSI codes for the status bar (Qt doesn't render them)
            import re
            plain = re.sub(r"\033\[[0-9;]*m", "", text)
            ms = 5000 if level >= _logging.WARNING else 2000
            self._status.showMessage(plain, ms)
        h = QtLogHandler(cb)
        h.setLevel(_logging.INFO)
        h.setFormatter(_logging.Formatter("%(levelname)s: %(message)s"))
        get_logger().addHandler(h)

    # ---- 2D beam profile --------------------------------------------
    def _update_beam_controls(self):
        """Enable/disable beam-tab controls based on the current source."""
        cb = self.beam.energy_map_cb
        cb.setEnabled(True)
        kind = self.source.kind.currentText()
        if kind == "Undulator":
            cb.setToolTip(
                "Colour each pixel by the red-shifted resonance energy "
                "E_n(θ) of the dominant harmonic at that angle.")
        else:
            cb.setToolTip(
                f"Colour each pixel by the peak-emission energy at that "
                f"angle (argmax_E of flux_density). For a "
                f"{kind.lower()} the peak shifts to lower energies at "
                f"larger vertical angles (|γψ|~1).")

    def _current_beamline(self):
        machine = self.machine.values()
        src = self.source.build_source(machine)
        slit = self.slit.build_slit()
        filt = self.filters.build_stack()
        return Beamline(source=src, slit=slit, filters=filt,
                         n_theta=self.slit.nsamp.value(),
                         ebeam=machine.get("ebeam"))

    def recompute_beam2d(self):
        try:
            bl = self._current_beamline()
            D_plane = self.beam.plane_m.value()
            r = self.beam.range_mm.value()
            n = self.beam.grid_n.value()
            x = np.linspace(-r, r, n)
            y = np.linspace(-r, r, n)

            # Energy map mode overrides the intensity image.
            if self.beam.energy_map_cb.isChecked():
                E_map, ext = bl.beam_2d_peak_energy(D_plane, x, y)
                Emin = np.nanmin(E_map); Emax = np.nanmax(E_map)
                info = (f"Plane @ {D_plane:g} m   view {2*r:g}×{2*r:g} mm   "
                        f"grid {n}×{n}   ENERGY MAP\n"
                        f"E range (dominant harmonic): {Emin:.3f} – {Emax:.3f} keV   "
                        f"(on-axis pixel: {E_map[n//2, n//2]:.3f} keV)")
                self.beam.update_image(E_map, ext, info,
                                        unit_label="keV",
                                        colormap="viridis")
                self._status.showMessage("Energy map OK", 1500)
                return

            mode_band = self.beam.mode.currentIndex() == 1
            if mode_band:
                E = np.linspace(self.beam.e_lo.value(),
                                 max(self.beam.e_hi.value(),
                                     self.beam.e_lo.value() + 1e-3),
                                 self.beam.e_n.value())
                img, ext = bl.beam_2d(D_plane, x, y, E, integrate_band=True)
                unit = "ph/s/mm²"
                E_label = f"{E[0]:.2f}–{E[-1]:.2f} keV ({len(E)} pts)"
                E_scale = 0.5 * (E[0] + E[-1])
            else:
                E = self.beam.e_lo.value()
                img, ext = bl.beam_2d(D_plane, x, y, E)
                unit = "ph/s/mm²/0.1%BW"
                E_label = f"{E:.3f} keV"
                E_scale = E
            peak = float(np.nanmax(img))
            iy, ix = np.unravel_index(np.nanargmax(img), img.shape)
            # Slit shadow at the plane (only meaningful if plane is downstream)
            if D_plane >= bl.slit.distance_m:
                shadow_h_mm = bl.slit.h_mm * D_plane / bl.slit.distance_m
                shadow_v_mm = bl.slit.v_mm * D_plane / bl.slit.distance_m
                slit_desc = f"slit shadow {shadow_h_mm:.2f}×{shadow_v_mm:.2f} mm"
            else:
                slit_desc = (f"plane {D_plane:g} m < slit {bl.slit.distance_m:g} m "
                             f"(upstream of slit — no clipping applied)")
            # Natural source angular scale -> size at plane
            src = bl.source
            if hasattr(src, "central_cone_sigma_mrad"):
                # Undulator central cone (n=1 is widest)
                sig_urad = src.central_cone_sigma_mrad(1) * 1e3
                nat = f"und. central cone σ(n=1)={sig_urad:.1f} µrad " \
                      f"({sig_urad*1e-6*D_plane*1e3:.3f} mm at plane)"
            elif hasattr(src, "gamma"):
                inv_gamma_urad = 1e6 / src.gamma
                nat = f"BM natural V half-width 1/γ={inv_gamma_urad:.1f} µrad " \
                      f"({inv_gamma_urad*1e-6*D_plane*1e3:.2f} mm at plane)"
            else:
                nat = ""
            hint = ""
            # Warn when the slit clips much narrower than the natural pattern
            slit_v_urad = bl.slit.v_accept_mrad() * 500  # half-width in µrad
            if hasattr(src, "gamma") and not hasattr(src, "central_cone_sigma_mrad"):
                if slit_v_urad < 0.5e6 / src.gamma:
                    hint = "  ⓘ slit V << 1/γ — vertical structure is clipped, image will look flat"
            info = (f"Plane @ {D_plane:g} m   view {2*r:g}×{2*r:g} mm   "
                    f"grid {n}×{n}   E={E_label}\n"
                    f"peak={peak:.3e} {unit} @ (x,y)=({x[ix]:.3f}, {y[iy]:.3f}) mm   "
                    f"{slit_desc}   "
                    f"{nat}{hint}")
            self.beam.update_image(img, ext, info)
            self._status.showMessage("2D beam OK", 1500)
        except Exception as exc:
            self._status.showMessage(f"Error: {exc}", 5000)
            import traceback; traceback.print_exc()

    def _export_beam2d(self):
        if self.beam._img is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save 2D beam", "beam2d.tif",
            "TIFF image (*.tif *.tiff);;NumPy (.npy) (*.npy);;CSV (*.csv)")
        if not path:
            return
        img = np.asarray(self.beam._img, dtype=np.float32)
        low = path.lower()
        try:
            if low.endswith(".npy"):
                np.save(path, img)
            elif low.endswith(".csv"):
                np.savetxt(path, img, delimiter=",")
            else:
                try:
                    import tifffile
                    tifffile.imwrite(path, img)
                except ImportError:
                    from PIL import Image
                    Image.fromarray(img).save(path)
            self._status.showMessage(f"Saved {path}", 3000)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Save failed", str(exc))


def main(argv=None):
    import argparse
    argv = argv or sys.argv
    ap = argparse.ArgumentParser(prog="xraysource-gui", add_help=False)
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--no-color", action="store_true")
    known, rest = ap.parse_known_args(argv[1:])
    configure_logging(level=known.log_level,
                       use_colour=False if known.no_color else None)
    _log.info("xraysource-gui starting")

    app = QtWidgets.QApplication([argv[0]] + rest)
    w = MainWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
