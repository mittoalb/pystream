"""
X-ray Tools plugin for bl32ID.

Qt/pyqtgraph port of /home/beams/AMITTONE/Software/xraytr (a Dash web app):

  * Tab 1 — Transmissivity & Refractive Index
      Compute transmission T(E) = exp(-µ/ρ · ρ · t) and refractive index
      components δ, β for a material formula over an energy range, using
      xraylib. Density is auto-resolved (user → xraylib elemental →
      PubChem → local cache → 1.0).

  * Tab 2 — X-ray Absorption Edges
      Filter/search a static table of K/L1/L2/L3 edges for Z = 1–103.

xraylib is required for Tab 1; if not installed the tab shows a hint
message but Tab 2 still works. PubChem lookups are best-effort and never
block the UI thread.
"""

import csv
import logging
import os
import re
from typing import Optional

import numpy as np
from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg

from .plugin_settings import PYSTREAM_HOME
from .xray_edges_data import (
    XRAY_EDGES, EDGE_COLUMN_INDEX,
    search_elements, filter_by_energy_range,
)


try:
    import xraylib  # type: ignore
    xraylib.XRayInit()
    HAS_XRAYLIB = True
    XRAYLIB_ERR = None
except Exception as ex:  # pragma: no cover — env-dependent
    xraylib = None
    HAS_XRAYLIB = False
    XRAYLIB_ERR = ex

try:
    import requests  # type: ignore
    HAS_REQUESTS = True
except Exception:
    requests = None
    HAS_REQUESTS = False


DENSITIES_CACHE = os.path.join(PYSTREAM_HOME, "xray_densities.csv")


# ── Density cache ────────────────────────────────────────────────────────

def _load_density_cache():
    """Return {formula: (density_g_cm3, name)} from the cache file. Missing
    or malformed file → empty dict."""
    out = {}
    if not os.path.exists(DENSITIES_CACHE):
        return out
    try:
        with open(DENSITIES_CACHE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                f = (row.get("formula") or "").strip()
                if not f:
                    continue
                try:
                    rho = float(row.get("density_g_cm3", "") or "nan")
                except ValueError:
                    continue
                name = (row.get("name") or "").strip() or f
                if np.isfinite(rho):
                    out[f] = (rho, name)
    except Exception:
        return out
    return out


def _append_density_cache(formula, density, name):
    """Append one row to the density cache. Creates file with header if new."""
    try:
        os.makedirs(os.path.dirname(DENSITIES_CACHE), exist_ok=True)
        is_new = not os.path.exists(DENSITIES_CACHE)
        with open(DENSITIES_CACHE, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(["formula", "density_g_cm3", "name"])
            writer.writerow([formula, f"{density:.6g}", name or formula])
    except Exception:
        pass


def _parse_energies(text):
    """Accept 'a:b:c' → np.arange or 'x' → single-element array (keV).
    Returns empty array on parse failure."""
    text = (text or "").strip()
    if not text:
        return np.array([])
    if ":" in text:
        try:
            a, b, c = [float(p) for p in text.split(":")]
            if c <= 0:
                return np.array([])
            return np.arange(a, b + 1e-9, c)
        except (TypeError, ValueError):
            return np.array([])
    try:
        return np.array([float(text)])
    except ValueError:
        return np.array([])


# ── Async PubChem lookup ─────────────────────────────────────────────────

class _PubChemWorker(QtCore.QThread):
    """Query PubChem for density + IUPAC name of a compound. Runs off the
    UI thread; result (density, name) delivered via `result` signal, or
    (None, None) on any failure/timeout."""
    result = QtCore.pyqtSignal(object, object)  # (density, name); None allowed

    def __init__(self, formula, timeout_s=5.0, parent=None):
        super().__init__(parent)
        self.formula = formula
        self.timeout_s = timeout_s

    def run(self):
        if not HAS_REQUESTS:
            self.result.emit(None, None)
            return
        try:
            url = (
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                f"formula/{self.formula}/property/Density,IUPACName/JSON"
            )
            resp = requests.get(url, timeout=self.timeout_s)
            resp.raise_for_status()
            props = resp.json()["PropertyTable"]["Properties"][0]
            rho = props.get("Density")
            name = props.get("IUPACName")
            if rho is not None:
                try:
                    rho = float(rho)
                except (TypeError, ValueError):
                    rho = None
            self.result.emit(rho, name)
        except Exception:
            self.result.emit(None, None)


# ── Main dialog ──────────────────────────────────────────────────────────

class XRayToolsDialog(QtWidgets.QDialog):
    """Two-tab dialog: transmissivity/refractive index + absorption edges."""

    BUTTON_TEXT = "X-ray Tools"
    GROUP       = "Calculators"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("X-ray Tools — bl32ID")
        self.resize(1100, 780)

        self._density_cache = _load_density_cache()
        self._pubchem_worker = None
        self._pending_calc = None  # cached inputs while waiting on PubChem

        self._build_ui()

        # Warn once at startup if xraylib is missing — Tab 1 will be disabled.
        if not HAS_XRAYLIB and self.logger:
            self.logger.warning(
                "xraylib not installed; X-ray Tools transmissivity tab "
                f"disabled: {XRAYLIB_ERR}"
            )

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("X-ray Tools")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_transmissivity_tab(),
                         "Transmissivity && Refractive Index")
        self.tabs.addTab(self._build_edges_tab(),
                         "X-ray Absorption Edges")
        layout.addWidget(self.tabs)

    # -- Tab 1 -----------------------------------------------------------
    def _build_transmissivity_tab(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)

        # Missing-xraylib banner
        if not HAS_XRAYLIB:
            banner = QtWidgets.QLabel(
                "<b>xraylib is not available in this Python environment.</b><br>"
                "Install it (e.g. <code>conda install -c conda-forge xraylib</code>) "
                "to use this tab. The Absorption Edges tab still works without it."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "padding: 10px; background-color: #4a2a2a; color: white; "
                "border-radius: 4px;"
            )
            v.addWidget(banner)

        # Inputs
        form = QtWidgets.QFormLayout()
        self.formula_input = QtWidgets.QLineEdit("SiO2")
        self.name_label = QtWidgets.QLabel("")
        self.name_label.setStyleSheet("color: #888; font-style: italic;")
        formula_row = QtWidgets.QHBoxLayout()
        formula_row.addWidget(self.formula_input, stretch=1)
        formula_row.addWidget(self.name_label, stretch=2)
        form.addRow("Formula:", formula_row)

        self.density_input = QtWidgets.QLineEdit()
        self.density_input.setPlaceholderText("auto (resolved from element / PubChem / cache)")
        self.density_note = QtWidgets.QLabel("")
        self.density_note.setStyleSheet("color: #888; font-style: italic;")
        density_row = QtWidgets.QHBoxLayout()
        density_row.addWidget(self.density_input, stretch=1)
        density_row.addWidget(self.density_note, stretch=2)
        form.addRow("Density (g/cm³):", density_row)

        self.thickness_input = QtWidgets.QDoubleSpinBox()
        self.thickness_input.setRange(0.0, 1e6)
        self.thickness_input.setDecimals(6)
        self.thickness_input.setValue(1.0)
        self.thickness_input.setSuffix(" mm")
        form.addRow("Thickness:", self.thickness_input)

        self.energy_input = QtWidgets.QLineEdit("8.0:20.0:0.5")
        self.energy_input.setToolTip(
            "Single value (e.g. 12) or range 'start:stop:step' in keV."
        )
        form.addRow("Energy (keV):", self.energy_input)

        v.addLayout(form)

        # Compute button
        btn_row = QtWidgets.QHBoxLayout()
        self.compute_btn = QtWidgets.QPushButton("Compute")
        self.compute_btn.setEnabled(HAS_XRAYLIB)
        self.compute_btn.clicked.connect(self._on_compute)
        btn_row.addWidget(self.compute_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # Plots
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        # Readout label above the plots, updated on click.
        self.readout_label = QtWidgets.QLabel(
            "Click on a plot to read the nearest data point."
        )
        self.readout_label.setStyleSheet(
            "padding: 6px 10px; background-color: #222; color: #fff; "
            "border-radius: 4px; font-family: monospace;"
        )
        v.addWidget(self.readout_label)

        self.trans_plot = pg.PlotWidget()
        self.trans_plot.setLabel("bottom", "Energy (keV)")
        self.trans_plot.setLabel("left", "Transmissivity T")
        self.trans_plot.showGrid(x=True, y=True, alpha=0.3)
        v.addWidget(self.trans_plot, stretch=1)

        self.db_plot = pg.PlotWidget()
        self.db_plot.setLabel("bottom", "Energy (keV)")
        self.db_plot.setLabel("left", "δ, β")
        self.db_plot.showGrid(x=True, y=True, alpha=0.3)
        self.db_plot.addLegend()
        v.addWidget(self.db_plot, stretch=1)

        # Cached arrays + click markers, populated on Compute.
        self._trans_E = None
        self._trans_T = None
        self._db_E = None
        self._db_delta = None
        self._db_beta = None
        self._trans_marker = None
        self._db_marker = None
        self.trans_plot.scene().sigMouseClicked.connect(self._on_trans_click)
        self.db_plot.scene().sigMouseClicked.connect(self._on_db_click)

        return page

    # -- Tab 2 -----------------------------------------------------------
    def _build_edges_tab(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)

        hint = QtWidgets.QLabel(
            "All energies in eV. Filters combine (AND). Click headers to sort."
        )
        hint.setStyleSheet("color: #666;")
        v.addWidget(hint)

        # Filters
        filt = QtWidgets.QHBoxLayout()
        filt.addWidget(QtWidgets.QLabel("Search:"))
        self.edge_search = QtWidgets.QLineEdit()
        self.edge_search.setPlaceholderText("element name or symbol")
        self.edge_search.textChanged.connect(self._refresh_edges_table)
        filt.addWidget(self.edge_search, stretch=1)

        filt.addWidget(QtWidgets.QLabel("Edge:"))
        self.edge_type_combo = QtWidgets.QComboBox()
        self.edge_type_combo.addItems(["All", "K", "L1", "L2", "L3"])
        self.edge_type_combo.currentIndexChanged.connect(self._refresh_edges_table)
        filt.addWidget(self.edge_type_combo)

        filt.addWidget(QtWidgets.QLabel("Min (eV):"))
        self.edge_min_input = QtWidgets.QLineEdit()
        self.edge_min_input.setFixedWidth(80)
        self.edge_min_input.setPlaceholderText("min")
        self.edge_min_input.textChanged.connect(self._refresh_edges_table)
        filt.addWidget(self.edge_min_input)

        filt.addWidget(QtWidgets.QLabel("Max (eV):"))
        self.edge_max_input = QtWidgets.QLineEdit()
        self.edge_max_input.setFixedWidth(80)
        self.edge_max_input.setPlaceholderText("max")
        self.edge_max_input.textChanged.connect(self._refresh_edges_table)
        filt.addWidget(self.edge_max_input)

        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_edge_filters)
        filt.addWidget(clear_btn)
        v.addLayout(filt)

        # Table
        self.edges_table = QtWidgets.QTableWidget()
        self.edges_table.setSortingEnabled(True)
        self.edges_table.setAlternatingRowColors(True)
        self.edges_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.edges_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        v.addWidget(self.edges_table, stretch=1)

        self._refresh_edges_table()
        return page

    # ── Tab 1 callbacks ─────────────────────────────────────────────────
    def _on_compute(self):
        if not HAS_XRAYLIB:
            return
        raw = self.formula_input.text().strip()
        if not raw:
            self.name_label.setText("(enter a formula)")
            return
        E = _parse_energies(self.energy_input.text())
        if E.size == 0:
            self.density_note.setText("Invalid energy input.")
            return
        thickness_mm = float(self.thickness_input.value())

        # Normalize element case: "fe" → "Fe"; multi-atom formulas passed as-is
        f = raw[0].upper() + raw[1:].lower() if re.fullmatch(r"[A-Za-z]{1,2}", raw) else raw

        # Resolve element vs compound
        try:
            Z = xraylib.SymbolToAtomicNumber(f)
            is_elem = Z > 0
        except Exception:
            is_elem = False
            Z = 0

        # User-provided density wins immediately.
        user_den = self.density_input.text().strip()
        if user_den:
            try:
                rho = float(user_den)
                note = "using user-provided density"
                name = self._density_cache.get(f, (rho, f))[1]
                self._finish_compute(f, is_elem, Z, rho, name, note, E, thickness_mm)
                return
            except ValueError:
                pass  # fall through to auto-resolve

        # Element density from xraylib
        if is_elem:
            try:
                rho = float(xraylib.ElementDensity(Z))
            except Exception:
                rho = 1.0
            name = self._density_cache.get(f, (rho, f))[1]
            self._finish_compute(f, True, Z, rho, name, "xraylib elemental density", E, thickness_mm)
            return

        # Compound: check cache, else PubChem (async)
        if f in self._density_cache:
            rho, name = self._density_cache[f]
            self._finish_compute(f, False, 0, rho, name, "cached density", E, thickness_mm)
            return

        if HAS_REQUESTS:
            self._pending_calc = (f, E, thickness_mm)
            self.density_note.setText("Querying PubChem…")
            self.compute_btn.setEnabled(False)
            self._pubchem_worker = _PubChemWorker(f)
            self._pubchem_worker.result.connect(self._on_pubchem_result)
            self._pubchem_worker.finished.connect(self._pubchem_worker.deleteLater)
            self._pubchem_worker.start()
        else:
            self._finish_compute(f, False, 0, 1.0, f,
                                 "no requests library; defaulting to 1.0", E, thickness_mm)

    def _on_pubchem_result(self, rho, name):
        if self._pending_calc is None:
            self.compute_btn.setEnabled(HAS_XRAYLIB)
            return
        f, E, thickness_mm = self._pending_calc
        self._pending_calc = None
        self.compute_btn.setEnabled(HAS_XRAYLIB)
        if rho is not None:
            self._finish_compute(f, False, 0, float(rho), name or f,
                                 f"PubChem density {float(rho):.4g} g/cm³",
                                 E, thickness_mm)
        else:
            self._finish_compute(f, False, 0, 1.0, name or f,
                                 "PubChem lookup failed; defaulting to 1.0 g/cm³",
                                 E, thickness_mm)

    def _finish_compute(self, formula, is_elem, Z, rho, name, note, E, thickness_mm):
        # Feed the cache so we don't hit PubChem twice for the same compound
        if formula not in self._density_cache and rho and np.isfinite(rho):
            self._density_cache[formula] = (rho, name or formula)
            _append_density_cache(formula, rho, name or formula)

        # Update inputs / labels
        self.density_input.setText(f"{rho:.4g}")
        self.name_label.setText(name or formula)
        self.density_note.setText(note)

        # µ/ρ per energy
        try:
            if is_elem:
                mu_rho = np.array([xraylib.CS_Total(Z, float(e)) for e in E])
            else:
                mu_rho = np.array([xraylib.CS_Total_CP(formula, float(e)) for e in E])
        except Exception as ex:
            self.density_note.setText(f"xraylib CS_Total failed: {ex}")
            self.trans_plot.clear()
            self.db_plot.clear()
            return

        t_cm = float(thickness_mm) / 10.0
        T = np.exp(-mu_rho * rho * t_cm)

        try:
            n_re = np.array([xraylib.Refractive_Index_Re(formula, float(e), rho) for e in E])
            n_im = np.array([xraylib.Refractive_Index_Im(formula, float(e), rho) for e in E])
        except Exception as ex:
            self.density_note.setText(f"Refractive_Index failed: {ex}")
            n_re = np.ones_like(E)
            n_im = np.zeros_like(E)
        delta = 1.0 - n_re
        beta = n_im

        # Cache arrays for the click-to-read handlers.
        self._trans_E = np.asarray(E, dtype=float)
        self._trans_T = np.asarray(T, dtype=float)
        self._db_E = np.asarray(E, dtype=float)
        self._db_delta = np.asarray(delta, dtype=float)
        self._db_beta = np.asarray(beta, dtype=float)
        self._trans_marker = None
        self._db_marker = None

        # Plots
        self.trans_plot.clear()
        self.trans_plot.plot(E, T, pen=pg.mkPen("c", width=2), symbol="o", symbolSize=4)
        self.trans_plot.setYRange(0, max(1e-30, float(np.nanmax(T))) * 1.05)

        self.db_plot.clear()
        # Re-add legend after clear
        self.db_plot.addLegend()
        self.db_plot.plot(E, delta, pen=pg.mkPen("m", width=2), name="δ")
        self.db_plot.plot(E, beta, pen=pg.mkPen("y", width=2), name="β")
        y_max = max(float(np.nanmax(delta)), float(np.nanmax(beta)), 1e-30)
        self.db_plot.setYRange(0, y_max * 1.05)

        self.readout_label.setText(
            "Click on a plot to read the nearest data point."
        )

    # ── Tab 1 click-to-read ─────────────────────────────────────────────
    def _on_trans_click(self, event):
        """Snap to the nearest E in the transmission trace and show T."""
        if self._trans_E is None or self._trans_E.size == 0:
            return
        if not event.button() == QtCore.Qt.LeftButton:
            return
        vb = self.trans_plot.getPlotItem().getViewBox()
        pt = vb.mapSceneToView(event.scenePos())
        idx = int(np.argmin(np.abs(self._trans_E - pt.x())))
        e = float(self._trans_E[idx])
        t = float(self._trans_T[idx])
        # Update marker
        if self._trans_marker is None:
            self._trans_marker = self.trans_plot.plot(
                [e], [t],
                pen=None, symbol="o", symbolSize=12,
                symbolBrush=(255, 60, 60), symbolPen=pg.mkPen("k", width=1.5),
            )
        else:
            self._trans_marker.setData([e], [t])
        self.readout_label.setText(f"E = {e:.4g} keV     T = {t:.4g}")

    def _on_db_click(self, event):
        """Snap to the nearest E in the δ,β traces and show both."""
        if self._db_E is None or self._db_E.size == 0:
            return
        if not event.button() == QtCore.Qt.LeftButton:
            return
        vb = self.db_plot.getPlotItem().getViewBox()
        pt = vb.mapSceneToView(event.scenePos())
        idx = int(np.argmin(np.abs(self._db_E - pt.x())))
        e = float(self._db_E[idx])
        d = float(self._db_delta[idx])
        b = float(self._db_beta[idx])
        if self._db_marker is None:
            self._db_marker = self.db_plot.plot(
                [e, e], [d, b],
                pen=None, symbol="o", symbolSize=12,
                symbolBrush=(255, 60, 60), symbolPen=pg.mkPen("k", width=1.5),
            )
        else:
            self._db_marker.setData([e, e], [d, b])
        self.readout_label.setText(
            f"E = {e:.4g} keV     δ = {d:.4g}     β = {b:.4g}"
        )

    # ── Tab 2 callbacks ─────────────────────────────────────────────────
    def _clear_edge_filters(self):
        for w in (self.edge_search, self.edge_min_input, self.edge_max_input):
            w.blockSignals(True)
            w.clear()
            w.blockSignals(False)
        self.edge_type_combo.blockSignals(True)
        self.edge_type_combo.setCurrentIndex(0)
        self.edge_type_combo.blockSignals(False)
        self._refresh_edges_table()

    def _refresh_edges_table(self):
        rows = search_elements(self.edge_search.text())
        edge_type = self.edge_type_combo.currentText()

        min_e = self._parse_optional_float(self.edge_min_input.text())
        max_e = self._parse_optional_float(self.edge_max_input.text())

        if edge_type == "All":
            # Filter across ALL edges — keep a row if any of its edges falls in range.
            if min_e is not None or max_e is not None:
                filtered = []
                for r in rows:
                    for idx in EDGE_COLUMN_INDEX.values():
                        e = r[idx]
                        if e is None:
                            continue
                        if min_e is not None and e < min_e:
                            continue
                        if max_e is not None and e > max_e:
                            continue
                        filtered.append(r)
                        break
                rows = filtered
            self._populate_edges_all(rows)
        else:
            rows = filter_by_energy_range(rows, min_e, max_e, edge_type)
            self._populate_edges_single(rows, edge_type)

    @staticmethod
    def _parse_optional_float(text):
        text = (text or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _populate_edges_all(self, rows):
        headers = ["Z", "Element", "Symbol",
                   "K-edge (eV)", "L1-edge (eV)", "L2-edge (eV)", "L3-edge (eV)"]
        self.edges_table.setSortingEnabled(False)
        self.edges_table.setColumnCount(len(headers))
        self.edges_table.setHorizontalHeaderLabels(headers)
        self.edges_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._set_int_item(i, 0, r[0])
            self._set_str_item(i, 1, r[1])
            self._set_str_item(i, 2, r[2])
            self._set_energy_item(i, 3, r[3])
            self._set_energy_item(i, 4, r[4])
            self._set_energy_item(i, 5, r[5])
            self._set_energy_item(i, 6, r[6])
        self.edges_table.resizeColumnsToContents()
        self.edges_table.setSortingEnabled(True)

    def _populate_edges_single(self, rows, edge_type):
        headers = ["Z", "Element", "Symbol", f"{edge_type}-edge (eV)"]
        idx = EDGE_COLUMN_INDEX[edge_type]
        self.edges_table.setSortingEnabled(False)
        self.edges_table.setColumnCount(len(headers))
        self.edges_table.setHorizontalHeaderLabels(headers)
        self.edges_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._set_int_item(i, 0, r[0])
            self._set_str_item(i, 1, r[1])
            self._set_str_item(i, 2, r[2])
            self._set_energy_item(i, 3, r[idx])
        self.edges_table.resizeColumnsToContents()
        self.edges_table.setSortingEnabled(True)

    def _set_str_item(self, row, col, value):
        item = QtWidgets.QTableWidgetItem(str(value))
        self.edges_table.setItem(row, col, item)

    def _set_int_item(self, row, col, value):
        item = QtWidgets.QTableWidgetItem()
        item.setData(QtCore.Qt.DisplayRole, int(value))
        self.edges_table.setItem(row, col, item)

    def _set_energy_item(self, row, col, value):
        item = QtWidgets.QTableWidgetItem()
        if value is None:
            item.setText("—")
        else:
            item.setData(QtCore.Qt.DisplayRole, float(value))
        item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.edges_table.setItem(row, col, item)

    # ── Cleanup ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self._pubchem_worker is not None and self._pubchem_worker.isRunning():
            self._pubchem_worker.requestInterruption()
            self._pubchem_worker.quit()
            self._pubchem_worker.wait(1000)
        super().closeEvent(event)
