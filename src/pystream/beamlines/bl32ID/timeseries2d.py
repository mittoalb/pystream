"""
2D Time Series plugin for bl32ID.

Every Y minutes, N times: move to the sample position and take X images,
then move to the reference position and take F reference (flat) images.
Everything goes into ONE HDF5 file, appended as it is acquired (a Stop or
crash keeps everything taken so far):

  /exchange/data            (N·X, H, W)   sample images
  /exchange/data_white      (N·F, H, W)   reference images
  /measurement/timeseries/
      data_repeat, data_time            repeat index (1-based), epoch time
      white_repeat, white_time          … per reference image
      sample_rbv, reference_rbv         (N, 3) X, Z, rotation readbacks
      attrs: images_per_repeat, references_per_repeat, repeats,
             interval_s, exposure_s, start/end time
  /measurement/positions/
      sample_target, reference_target   (3,) X, Z, rotation (NaN = not moved)
      attrs: motor PVs

Positions, motor PVs, camera PVs, exposure and the fast shutter come from
the XANES 2D plugin's saved settings (~/.xanes_gui_2d_settings.json,
"Load from XANES 2D"); they can be edited here afterwards. The interval
is start-to-start. Between repeats the sample waits at the reference
position with the fast shutter closed, and when the interval is a minute
or more the B-station shutter too (same rule as XANES 2D) (opened again, with its status checked, before
the next repeat). At the end both shutters and the camera's ImageMode / NumImages / AcquireTime /
Acquire go back to what they were before the start.

Settings persist in ~/.pystream/bl32ID_settings.json under
"TimeSeries2DDialog".
"""

import os
import time
import logging
from typing import Optional, Dict, Any, List

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .plugin_settings import load_settings, save_settings
from .datamap import XANES2D_SETTINGS, _read_json, _age

try:
    import epics
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


# Fallbacks if XANES 2D has never been saved (same names as gui_2d.DEFAULTS).
DEFAULT_PVS = {
    "detector_pv":         "32idbSP1:Pva1:Image",
    "cam_acquire_pv":      "32idbSP1:cam1:Acquire",
    "cam_acquire_time_pv": "32idbSP1:cam1:AcquireTime",
    "cam_image_mode_pv":   "32idbSP1:cam1:ImageMode",
    "cam_num_images_pv":   "32idbSP1:cam1:NumImages",
    "topx_pv":             "32idbTXM:mcs:c2:m1",
    "topz_pv":             "32idbTXM:mcs:c2:m2",
    "rot_pv":              "32idbTXM:ens:c1:m1",
    "fast_shutter_pv":     "32idbTXM:uniblitz:control",
    "b_shutter_open_pv":   "32idb:rshtrB:Open.PROC",
    "b_shutter_close_pv":  "32idb:rshtrB:Close.PROC",
    "b_shutter_status_pv": "PB:32ID:STA_B_SBS_CLSD_PL",
}
OPTIONAL_PVS = {"fast_shutter_pv", "b_shutter_open_pv", "b_shutter_close_pv",
                "b_shutter_status_pv"}
B_SHUTTER_MIN_WAIT_S = 60.0     # cycle the B shutter when the interval is this long
B_SHUTTER_MIN_LEFT_S = 10.0     # …unless less than this is left to wait (strokes)
B_SHUTTER_TIMEOUT_S = 30.0
PV_LABELS = [
    ("topx_pv", "Sample X motor"), ("topz_pv", "Sample Z motor"),
    ("rot_pv", "Rotation motor"), ("detector_pv", "Detector PVA channel"),
    ("cam_acquire_pv", "Camera Acquire"), ("cam_acquire_time_pv", "Camera AcquireTime"),
    ("cam_image_mode_pv", "Camera ImageMode"), ("cam_num_images_pv", "Camera NumImages"),
    ("fast_shutter_pv", "Fast shutter (blank = none)"),
    ("b_shutter_open_pv", "B shutter open (blank = none)"),
    ("b_shutter_close_pv", "B shutter close"),
    ("b_shutter_status_pv", "B shutter status (1 = closed)"),
]
_NTNDA_KEYS = ("ushortValue", "shortValue", "intValue", "uintValue",
               "floatValue", "doubleValue", "ubyteValue", "byteValue")


def next_indexed_path(path: str) -> str:
    """<dir>/<stem>_NNN<ext> with NNN one above the highest existing index
    (001 if none), so a new series never overwrites an old one. A trailing
    _NNN already in the name is treated as the stem's index."""
    import re
    d, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    ext = ext or ".h5"
    stem = re.sub(r"_\d{3,}$", "", stem)
    pat = re.compile(r"^" + re.escape(stem) + r"_(\d{3,})" + re.escape(ext) + r"$")
    try:
        used = [int(m.group(1)) for fn in os.listdir(d or ".") if (m := pat.match(fn))]
    except OSError:
        used = []
    return os.path.join(d, f"{stem}_{max(used, default=0) + 1:03d}{ext}")


def _decode(st) -> np.ndarray:
    """NTNDArray → 2-D array. areaDetector: dimension[0] is the width (x),
    dimension[1] the height (y)."""
    val = st["value"][0]
    flat = next((np.asarray(val[k]) for k in _NTNDA_KEYS if k in val), None)
    if flat is None:
        raise RuntimeError("unsupported NTNDArray data type")
    dims = st["dimension"]
    return flat.reshape(int(dims[1]["size"]), int(dims[0]["size"]))


# ── Worker ───────────────────────────────────────────────────────────────

class _SeriesWorker(QtCore.QThread):
    """Runs one series; see the module docstring for the file layout."""
    log      = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)      # images done, total
    done     = QtCore.pyqtSignal(str)           # file path

    def __init__(self, cfg: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = False

    def stop(self):
        self._stop = True

    # ── EPICS ──────────────────────────────────────────────────────────

    def _put(self, pv, val, wait=True, timeout=30.0):
        """caput like XANES 2D does it. pyepics returns None when the PV
        can't be reached; a put-completion timeout is reported by the
        caller from the readback, not here."""
        if caput(pv, val, wait=wait, timeout=timeout) is None:
            raise RuntimeError(f"cannot reach {pv}")

    def _rbv(self, pv) -> float:
        v = caget(pv + ".RBV", timeout=2.0, use_monitor=False)
        return float("nan") if v is None else float(v)

    def _move_to(self, which: str, target):
        """target = (x, z, rot); None entries are not moved. Every step is
        logged before it happens and bounded in time."""
        c = self.cfg
        tol = c["tolerance"]
        for pv, t in zip((c["pvs"]["topx_pv"], c["pvs"]["topz_pv"], c["pvs"]["rot_pv"]), target):
            if t is None or self._stop:
                continue
            # "In position" = the motor record's own retry deadband, if larger.
            rdbd = caget(pv + ".RDBD", timeout=2.0, use_monitor=False)
            tol = max(c["tolerance"], abs(float(rdbd)) if rdbd is not None else 0.0)
            here = self._rbv(pv)
            if abs(here - t) <= tol:
                self.log.emit(f"  {pv} already at {here:.4f} ({which})")
                continue
            self.log.emit(f"  move {pv} {here:.4f} → {t:.4f} ({which})")
            t0 = time.monotonic()
            self._put(pv, float(t), wait=True, timeout=60.0)   # XANES 2D uses 60 s
            if time.monotonic() - t0 > 59:
                self.log.emit(f"  ⚠ {pv}: no move-complete after 60 s — checking readback")
            deadline = time.monotonic() + 30.0
            while abs(self._rbv(pv) - t) > tol:
                if self._stop:
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{pv} did not reach {t:.4f} (at {self._rbv(pv):.4f}, "
                                       f"tolerance {tol}) — {which} position")
                time.sleep(0.1)
        time.sleep(c["settle_s"])

    def _shutter(self, open_: bool):
        pv = self.cfg["pvs"].get("fast_shutter_pv", "").strip()
        if pv and self.cfg["use_fast_shutter"]:
            self.log.emit(f"  shutter {'open' if open_ else 'close'} ({pv})")
            caput(pv, 1 if open_ else 0, wait=False)          # as XANES 2D

    def _b_closed(self):
        st = self.cfg["pvs"].get("b_shutter_status_pv", "").strip()
        if not st:
            return None
        v = caget(st, timeout=2.0, use_monitor=False)
        return None if v is None else bool(int(v))       # 1 = closed

    def _b_shutter(self, open_: bool):
        """Open/close the B-station shutter and wait for its status. A failed
        open raises (images would be dark); a failed close only warns."""
        p = self.cfg["pvs"]
        pv = p.get("b_shutter_open_pv" if open_ else "b_shutter_close_pv", "").strip()
        if not pv or not self.cfg["use_b_shutter"]:
            return
        word = "open" if open_ else "closed"
        if self._b_closed() is (not open_):
            return
        self.log.emit(f"  B shutter {'opening' if open_ else 'closing'} ({pv})")
        caput(pv, 1, wait=False)
        if not p.get("b_shutter_status_pv", "").strip():
            time.sleep(3.0)
            return
        deadline = time.monotonic() + B_SHUTTER_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._b_closed() is (not open_):
                self.log.emit(f"  B shutter {word}")
                return
            if self._stop:
                return
            time.sleep(0.2)
        msg = f"B shutter not {word} after {B_SHUTTER_TIMEOUT_S:.0f}s"
        if open_:
            raise RuntimeError(msg + " — check the PSS / hutch search")
        self.log.emit("  ⚠ " + msg)

    def _wait_camera_idle(self, timeout: float):
        """Acquire must be back to 0 before the next trigger: the frame reaches
        the PVA stream slightly BEFORE the driver finishes, and a trigger sent
        in that gap is ignored by the camera."""
        acq = self.cfg["pvs"]["cam_acquire_pv"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            v = caget(acq, timeout=2.0, use_monitor=False)
            if v is not None and int(v) == 0:
                return
            if self._stop:
                raise InterruptedError
            time.sleep(0.02)
        raise RuntimeError(f"camera still acquiring after {timeout:.0f}s ({acq})")

    def _snap(self, ch) -> np.ndarray:
        """One frame, the way XANES 2D takes it (proven on this camera):
        trigger Acquire, wait exposure + 0.2 s, take the current image. The
        frame uniqueId is NOT used — on this PVA stream it doesn't reliably
        advance. Consecutive frames at one position also need the camera to
        be finished (Acquire back to 0) before reading / re-triggering,
        otherwise the next trigger lands while it's busy and is ignored."""
        p, exp = self.cfg["pvs"], self.cfg["exposure_s"]
        acq = p["cam_acquire_pv"]
        self._wait_camera_idle(timeout=exp + 15)
        caput(acq, 1, wait=False)
        t0 = time.monotonic()
        while time.monotonic() - t0 < exp + 0.2:
            if self._stop:
                raise InterruptedError
            time.sleep(0.02)
        self._wait_camera_idle(timeout=exp + 15)        # frame delivered
        return _decode(ch.get(""))

    # ── main ───────────────────────────────────────────────────────────

    def run(self):
        c, p = self.cfg, self.cfg["pvs"]
        path = c["path"]
        cam_pvs = [p["cam_image_mode_pv"], p["cam_num_images_pv"],
                   p["cam_acquire_time_pv"], p["cam_acquire_pv"]]
        cam_before = {}
        shutter_pv = p.get("fast_shutter_pv", "").strip() if c["use_fast_shutter"] else ""
        shutter_before = None
        b_closed_before = None
        f = None
        try:
            self.log.emit(f"Camera: stop, Single mode, {c['exposure_s']} s exposure")
            ch = pva.Channel(p["detector_pv"])
            cam_before = {pv: caget(pv, timeout=2.0, use_monitor=False) for pv in cam_pvs}
            if shutter_pv:
                shutter_before = caget(shutter_pv, timeout=2.0, use_monitor=False)
            b_closed_before = self._b_closed() if c["use_b_shutter"] else None
            if cam_before[p["cam_acquire_pv"]]:
                self._put(p["cam_acquire_pv"], 0)
                time.sleep(0.3)
            self._put(p["cam_image_mode_pv"], 0)          # Single
            self._put(p["cam_num_images_pv"], 1)
            self._put(p["cam_acquire_time_pv"], c["exposure_s"])

            N, X, F = c["repeats"], c["images"], c["references"]
            total = N * (X + F)
            n_done = 0
            f = self._open_file(path)
            ts = f["measurement/timeseries"]
            self.log.emit(f"Writing {path}")

            for k in range(1, N + 1):
                if self._stop:
                    break
                t_start = time.monotonic()
                self.log.emit(f"══ repeat {k}/{N} ══")
                self._b_shutter(True)
                self._shutter(True)

                self._move_to("sample", c["sample"])
                ts["sample_rbv"].resize((k, 3))
                ts["sample_rbv"][k - 1] = [self._rbv(p[q]) for q in ("topx_pv", "topz_pv", "rot_pv")]
                for i in range(X):
                    self.log.emit(f"  sample image {i + 1}/{X}")
                    self._take(f, ch, "data", k)
                    n_done += 1
                    self.progress.emit(n_done, total)

                if F:
                    self._move_to("reference", c["reference"])
                    ts["reference_rbv"].resize((k, 3))
                    ts["reference_rbv"][k - 1] = [self._rbv(p[q]) for q in ("topx_pv", "topz_pv", "rot_pv")]
                    for i in range(F):
                        self.log.emit(f"  reference image {i + 1}/{F}")
                        self._take(f, ch, "data_white", k)
                        n_done += 1
                        self.progress.emit(n_done, total)
                f.flush()

                if k < N and not self._stop:
                    self._shutter(False)
                    t_next = t_start + c["interval_s"]
                    left = t_next - time.monotonic()
                    # Same rule as XANES 2D: interval >= 1 min → close B.
                    if c["interval_s"] >= B_SHUTTER_MIN_WAIT_S and c["use_b_shutter"]:
                        if left >= B_SHUTTER_MIN_LEFT_S:
                            self._b_shutter(False)
                            left = t_next - time.monotonic()
                        else:
                            self.log.emit(f"  B shutter left open: only {left:.0f}s to wait")
                    if left <= 0:
                        self.log.emit("  repeat took longer than the interval — next starts now")
                    else:
                        at = time.strftime("%H:%M:%S", time.localtime(time.time() + left))
                        self.log.emit(f"  waiting {left / 60:.1f} min — repeat {k + 1} at {at}")
                        while not self._stop and time.monotonic() < t_next:
                            time.sleep(0.2)
            if self._stop:
                self.log.emit("Stopped by user — file keeps everything taken so far.")
            else:
                self.log.emit("Series complete.")
        except InterruptedError:
            self.log.emit("Stopped by user — file keeps everything taken so far.")
        except Exception as e:
            self.log.emit(f"[ERROR] {type(e).__name__}: {e}")
        finally:
            if f is not None:
                f["measurement/timeseries"].attrs["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                f.close()
            self._restore_camera(cam_before)
            if shutter_pv and shutter_before is not None:
                caput(shutter_pv, shutter_before, wait=True, timeout=5.0)
                self.log.emit(f"Shutter back to {'open' if shutter_before else 'closed'}.")
            if b_closed_before is not None:
                try:
                    self._stop = False            # let the restore wait for status
                    self._b_shutter(not b_closed_before)
                except Exception as e:
                    self.log.emit(f"[WARN] B shutter restore: {e}")
            self.done.emit(path)

    MAX_FAILS_IN_A_ROW = 5

    def _take(self, f, ch, name, k):
        """Acquire + append one image. A lost frame is logged and skipped
        (its repeat/time rows simply aren't written); only several failures
        in a row end the series."""
        try:
            self._append(f, name, self._snap(ch), k)
            self._fails = 0
        except RuntimeError as e:
            self._fails = getattr(self, "_fails", 0) + 1
            self.log.emit(f"  ✗ image lost: {e}")
            if self._fails >= self.MAX_FAILS_IN_A_ROW:
                raise RuntimeError(f"{self._fails} images lost in a row — stopping") from e

    def _restore_camera(self, before):
        p = self.cfg["pvs"]
        if not before:
            return
        try:
            for pv in (p["cam_image_mode_pv"], p["cam_num_images_pv"], p["cam_acquire_time_pv"]):
                if before.get(pv) is not None:
                    caput(pv, before[pv], wait=True, timeout=5.0)
            if before.get(p["cam_acquire_pv"]):
                caput(p["cam_acquire_pv"], 1, wait=False)
            self.log.emit("Camera settings restored.")
        except Exception as e:
            self.log.emit(f"[WARN] camera restore: {e}")

    # ── HDF5 ───────────────────────────────────────────────────────────

    def _open_file(self, path):
        c, p = self.cfg, self.cfg["pvs"]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        f = h5py.File(path, "w")
        f.create_group("exchange")
        ts = f.create_group("measurement/timeseries")
        for name in ("data_repeat", "white_repeat"):
            ts.create_dataset(name, (0,), maxshape=(None,), dtype="i4")
        for name in ("data_time", "white_time"):
            ts.create_dataset(name, (0,), maxshape=(None,), dtype="f8")
        for name in ("sample_rbv", "reference_rbv"):
            ts.create_dataset(name, (0, 3), maxshape=(None, 3), dtype="f8")
        ts.attrs.update({
            "images_per_repeat": c["images"], "references_per_repeat": c["references"],
            "repeats": c["repeats"], "interval_s": c["interval_s"],
            "exposure_s": c["exposure_s"], "columns_rbv": "X, Z, rotation",
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        pos = f.create_group("measurement/positions")
        nan = lambda v: np.nan if v is None else float(v)
        pos.create_dataset("sample_target", data=[nan(v) for v in c["sample"]])
        pos.create_dataset("reference_target", data=[nan(v) for v in c["reference"]])
        pos.attrs.update({"columns": "X, Z, rotation (NaN = not moved)",
                          "x_pv": p["topx_pv"], "z_pv": p["topz_pv"], "rot_pv": p["rot_pv"],
                          "detector_pv": p["detector_pv"]})
        return f

    def _append(self, f, name, img, k):
        ex = f["exchange"]
        if name not in ex:
            ex.create_dataset(name, (0,) + img.shape, maxshape=(None,) + img.shape,
                              dtype=img.dtype, chunks=(1,) + img.shape)
        ds = ex[name]
        if ds.shape[1:] != img.shape:
            raise RuntimeError(f"frame size changed {ds.shape[1:]} → {img.shape}")
        n = ds.shape[0]
        ds.resize(n + 1, axis=0)
        ds[n] = img
        pre = "data" if name == "data" else "white"
        ts = f["measurement/timeseries"]
        for col, v in ((f"{pre}_repeat", k), (f"{pre}_time", time.time())):
            ts[col].resize((n + 1,))
            ts[col][n] = v


# ── Dialog ───────────────────────────────────────────────────────────────

class TimeSeries2DDialog(QtWidgets.QDialog):
    BUTTON_TEXT  = "2D Time Series"
    GROUP        = "Scans"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("2D Time Series — bl32ID")
        self.resize(640, 720)
        self._worker: Optional[_SeriesWorker] = None
        self._build_ui()
        self._restore()
        if not load_settings(self.__class__.__name__):
            self._load_from_xanes2d()          # first use: start from XANES 2D

    # ── UI ──────────────────────────────────────────────────────────────

    def _dspin(self, lo, hi, dec, val=0.0, suffix=""):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi); s.setDecimals(dec); s.setValue(val)
        if suffix:
            s.setSuffix(suffix)
        return s

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        v.addWidget(tabs)

        # ── Series tab ─────────────────────────────────────────────────
        w = QtWidgets.QWidget(); tv = QtWidgets.QVBoxLayout(w)

        ser = QtWidgets.QGroupBox("Series")
        f = QtWidgets.QFormLayout(ser)
        self.images = QtWidgets.QSpinBox(); self.images.setRange(1, 100000); self.images.setValue(10)
        self.refs = QtWidgets.QSpinBox(); self.refs.setRange(0, 100000); self.refs.setValue(10)
        self.every = self._dspin(0, 100000, 2, 10.0, " min")
        self.repeats = QtWidgets.QSpinBox(); self.repeats.setRange(1, 100000); self.repeats.setValue(6)
        self.exposure = self._dspin(0.0001, 600, 4, 0.1, " s")
        f.addRow("Images per repeat:", self.images)
        f.addRow("Reference images per repeat:", self.refs)
        f.addRow("Every (start to start):", self.every)
        f.addRow("Repeats:", self.repeats)
        f.addRow("Exposure:", self.exposure)
        self.use_fast = QtWidgets.QCheckBox("Use fast shutter (closed between repeats)")
        self.use_b = QtWidgets.QCheckBox("Use B-station shutter (closed between repeats "
                                         "when the interval is ≥ 1 min)")
        for cb in (self.use_fast, self.use_b):
            cb.setChecked(True)
            f.addRow("", cb)
        self.estimate = QtWidgets.QLabel("")
        f.addRow("", self.estimate)
        for s in (self.images, self.refs, self.every, self.repeats, self.exposure):
            s.valueChanged.connect(self._update_estimate)
        tv.addWidget(ser)

        pos = QtWidgets.QGroupBox("Positions")
        g = QtWidgets.QGridLayout(pos)
        for c, t in enumerate(("", "X [mm]", "Z [mm]", "Rotation [deg]")):
            g.addWidget(QtWidgets.QLabel(f"<b>{t}</b>"), 0, c)
        self.sx, self.sz, self.srot = (self._dspin(-1000, 1000, 4) for _ in range(3))
        self.rx, self.rz, self.rrot = (self._dspin(-1000, 1000, 4) for _ in range(3))
        self.move_rot = QtWidgets.QCheckBox("move rotation")
        for r, (lbl, ws) in enumerate((("Sample", (self.sx, self.sz, self.srot)),
                                       ("Reference", (self.rx, self.rz, self.rrot))), 1):
            g.addWidget(QtWidgets.QLabel(lbl), r, 0)
            for c, wid in enumerate(ws, 1):
                g.addWidget(wid, r, c)
        self.move_rot.toggled.connect(lambda on: (self.srot.setEnabled(on), self.rrot.setEnabled(on)))
        g.addWidget(self.move_rot, 3, 3)
        load = QtWidgets.QPushButton("Load from XANES 2D")
        load.setToolTip("Positions, motor/camera PVs, exposure and shutter from the "
                        "XANES 2D plugin's saved settings")
        load.clicked.connect(self._load_from_xanes2d)
        here_s = QtWidgets.QPushButton("Sample = current")
        here_s.clicked.connect(lambda: self._set_current(self.sx, self.sz, self.srot))
        here_r = QtWidgets.QPushButton("Reference = current")
        here_r.clicked.connect(lambda: self._set_current(self.rx, self.rz, self.rrot))
        g.addWidget(load, 3, 0, 1, 1)
        g.addWidget(here_s, 4, 1); g.addWidget(here_r, 4, 2)
        self.src = QtWidgets.QLabel("")
        self.src.setWordWrap(True)
        g.addWidget(self.src, 5, 0, 1, 4)
        tv.addWidget(pos)

        out = QtWidgets.QGroupBox("Output (one HDF5 file)")
        oh = QtWidgets.QHBoxLayout(out)
        self.path = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("…"); browse.setMaximumWidth(30)
        browse.clicked.connect(self._browse)
        oh.addWidget(self.path); oh.addWidget(browse)
        tv.addWidget(out)
        tv.addStretch()
        tabs.addTab(w, "Series")

        # ── PVs tab ────────────────────────────────────────────────────
        pw = QtWidgets.QWidget(); pf = QtWidgets.QFormLayout(pw)
        self.pv_edits = {}
        for key, label in PV_LABELS:
            e = QtWidgets.QLineEdit()
            self.pv_edits[key] = e
            pf.addRow(label + ":", e)
        self.tolerance = self._dspin(0.00001, 1, 5, 0.001)
        self.settle = self._dspin(0, 60, 2, 0.5, " s")
        pf.addRow("Position tolerance:", self.tolerance)
        pf.addRow("Settle after move:", self.settle)
        tabs.addTab(pw, "PVs")

        # ── run row + log ──────────────────────────────────────────────
        row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QtWidgets.QPushButton("Stop"); self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.progress = QtWidgets.QProgressBar()
        row.addWidget(self.start_btn); row.addWidget(self.stop_btn); row.addWidget(self.progress, 1)
        v.addLayout(row)
        self.log_text = QtWidgets.QPlainTextEdit(); self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)
        v.addWidget(self.log_text, 1)

    # ── helpers ─────────────────────────────────────────────────────────

    def _log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.log_text.appendPlainText(line)
        # Also next to the data, so the log survives a pystream restart.
        if getattr(self, "_logfile", None):
            try:
                with open(self._logfile, "a") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def _update_estimate(self):
        n, every = self.repeats.value(), self.every.value()
        per = (self.images.value() + self.refs.value()) * self.exposure.value()
        tot = n * (self.images.value() + self.refs.value())
        self.estimate.setText(
            f"{tot} images; ≈{per / 60:.1f} min of exposure per repeat; "
            f"series ≈{(n - 1) * every:.0f} min + last repeat")

    def _browse(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save series as", self.path.text() or os.path.expanduser("~"),
            "HDF5 (*.h5 *.hdf5)")
        if p:
            self.path.setText(p if p.endswith((".h5", ".hdf5")) else p + ".h5")

    def _load_from_xanes2d(self):
        d = _read_json(XANES2D_SETTINGS)
        if not d:
            self.src.setText(f"No XANES 2D settings at {XANES2D_SETTINGS} — "
                             "open XANES 2D and press Save Settings, or type the values.")
            for k, e in self.pv_edits.items():
                if not e.text():
                    e.setText(DEFAULT_PVS[k])
            return
        pvs, sc = d.get("pvs", {}), d.get("scan", {})
        for k, e in self.pv_edits.items():
            e.setText(str(pvs.get(k) or DEFAULT_PVS[k]))
        num = lambda k, w: w.setValue(float(sc[k])) if str(sc.get(k, "")).strip() else None
        for k, w in (("topx_data", self.sx), ("topz_data", self.sz), ("rot_data", self.srot),
                     ("topx_ref", self.rx), ("topz_ref", self.rz), ("rot_ref", self.rrot),
                     ("exposure", self.exposure)):
            try:
                num(k, w)
            except ValueError:
                pass
        self.move_rot.setChecked(bool(str(sc.get("rot_data", "")).strip()
                                      or str(sc.get("rot_ref", "")).strip()))
        if not self.path.text() and sc.get("save_dir"):
            self.path.setText(os.path.join(sc["save_dir"],
                                           f"timeseries_{time.strftime('%Y%m%d_%H%M')}.h5"))
        self.src.setText(f"Loaded from XANES 2D (saved {_age(XANES2D_SETTINGS)}).")
        self._log("Loaded positions, PVs and exposure from XANES 2D.")

    def _set_current(self, wx, wz, wrot):
        try:
            for w, key in ((wx, "topx_pv"), (wz, "topz_pv"), (wrot, "rot_pv")):
                v = caget(self.pv_edits[key].text().strip() + ".RBV", timeout=2.0,
                          use_monitor=False)
                if v is None:
                    raise RuntimeError(f"cannot read {self.pv_edits[key].text()}")
                w.setValue(float(v))
        except Exception as e:
            self._log(f"[ERROR] {e}")

    def _cfg(self) -> Dict[str, Any]:
        rot = self.move_rot.isChecked()
        return {
            "pvs": {k: e.text().strip() for k, e in self.pv_edits.items()},
            "images": self.images.value(), "references": self.refs.value(),
            "repeats": self.repeats.value(), "interval_s": self.every.value() * 60.0,
            "exposure_s": self.exposure.value(),
            "sample": (self.sx.value(), self.sz.value(), self.srot.value() if rot else None),
            "reference": (self.rx.value(), self.rz.value(), self.rrot.value() if rot else None),
            "tolerance": self.tolerance.value(), "settle_s": self.settle.value(),
            "path": self.path.text().strip(),
            "use_fast_shutter": self.use_fast.isChecked(),
            "use_b_shutter": self.use_b.isChecked(),
        }

    # ── run ─────────────────────────────────────────────────────────────

    def _start(self):
        c = self._cfg()
        probs = []
        if not (HAS_EPICS and HAS_PVA and HAS_H5PY):
            probs.append("needs pyepics, pvaccess and h5py")
        if not c["path"]:
            probs.append("choose the output file")
        missing = [lbl for k, lbl in PV_LABELS if k not in OPTIONAL_PVS and not c["pvs"][k]]
        if missing:
            probs.append("missing PVs: " + ", ".join(missing))
        if probs:
            QtWidgets.QMessageBox.warning(self, "Cannot start", "\n".join(probs))
            return
        self._save()
        # Never overwrite: write to the next free <name>_NNN.h5.
        c["path"] = next_indexed_path(c["path"])
        self._logfile = os.path.splitext(c["path"])[0] + ".log"
        self._log("=" * 50)
        self._log(f"{c['repeats']} × ({c['images']} images + {c['references']} references) "
                  f"every {c['interval_s'] / 60:g} min → {c['path']}")
        self._worker = _SeriesWorker(c)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(lambda d, t: (self.progress.setMaximum(t),
                                                    self.progress.setValue(d)))
        self._worker.done.connect(self._finished)
        self.progress.setValue(0)
        self.start_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._log("Stop requested…")
            self._worker.stop()

    def _finished(self, path):
        self._log(f"Done: {path}")
        self._logfile = None
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)

    # ── persistence ─────────────────────────────────────────────────────

    def _save(self):
        c = self._cfg()
        save_settings(self.__class__.__name__, {
            "pvs": c["pvs"], "images": c["images"], "references": c["references"],
            "repeats": c["repeats"], "every_min": self.every.value(),
            "exposure_s": c["exposure_s"], "move_rot": self.move_rot.isChecked(),
            "sample": [self.sx.value(), self.sz.value(), self.srot.value()],
            "reference": [self.rx.value(), self.rz.value(), self.rrot.value()],
            "tolerance": c["tolerance"], "settle_s": c["settle_s"], "path": c["path"],
            "use_fast_shutter": c["use_fast_shutter"], "use_b_shutter": c["use_b_shutter"],
        })

    def _restore(self):
        s = load_settings(self.__class__.__name__)
        for k, e in self.pv_edits.items():
            e.setText(s.get("pvs", {}).get(k, DEFAULT_PVS[k]))
        self.images.setValue(int(s.get("images", 10)))
        self.refs.setValue(int(s.get("references", 10)))
        self.repeats.setValue(int(s.get("repeats", 6)))
        self.every.setValue(float(s.get("every_min", 10.0)))
        self.exposure.setValue(float(s.get("exposure_s", 0.1)))
        for ws, k in (((self.sx, self.sz, self.srot), "sample"),
                      ((self.rx, self.rz, self.rrot), "reference")):
            for w, val in zip(ws, s.get(k, [0.0, 0.0, 0.0])):
                w.setValue(float(val))
        self.move_rot.setChecked(bool(s.get("move_rot", False)))
        self.srot.setEnabled(self.move_rot.isChecked()); self.rrot.setEnabled(self.move_rot.isChecked())
        self.tolerance.setValue(float(s.get("tolerance", 0.001)))
        self.settle.setValue(float(s.get("settle_s", 0.5)))
        self.path.setText(s.get("path", ""))
        self.use_fast.setChecked(bool(s.get("use_fast_shutter", True)))
        self.use_b.setChecked(bool(s.get("use_b_shutter", True)))
        self._update_estimate()

    def closeEvent(self, e):
        if self._worker and self._worker.isRunning():
            if QtWidgets.QMessageBox.question(
                    self, "Series running", "Stop the series and close?") \
                    != QtWidgets.QMessageBox.Yes:
                e.ignore()
                return
            self._worker.stop()
            if not self._worker.wait(10000):
                # Still inside a move/acquisition: destroying a running
                # QThread would take pystream down — hide instead.
                self._log("Still finishing the current step; window hidden.")
                e.ignore()
                self.hide()
                return
        try:
            self._save()
        except Exception:
            pass
        super().closeEvent(e)
