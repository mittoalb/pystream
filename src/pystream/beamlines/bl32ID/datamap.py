"""
DataMap plugin for bl32ID — a mosaic of X-Y positions, and at each one any
combination of:

  * Image      — one frame at the position + one flat at the Ref position,
                 saved to <output_dir>/datamap_pNNN_<ts>.h5
  * 2D XANES   — the XANES 2D plugin's scan, run at this position
  * Tomo       — one TomoScan scan
  * 3D XANES   — the XANES plugin's energy scan (a tomography per energy)

At each position the selected actions run in that order.

Scan parameters are NOT set here. They come from the plugin that owns
them, so DataMap always runs what those plugins would run:

  * 2D XANES  ← ~/.xanes_gui_2d_settings.json, written by the XANES 2D GUI's
                Save Settings (energies, exposure, Ref position, PVs) and
                the ZP calibration from bl_gui. The DATA position is
                replaced by the current map position.
  * Tomo      ← the TomoScan IOC's own PVs (set them in bl_gui → TomoScan);
                run with the standard `tomoscan single` CLI in the tomoscan
                conda env (same host/env settings as the XANES plugin).
  * 3D XANES  ← energies from 32id:TXMOptics:XanesStart/End/Step (what the
                XANES GUI primes), launch settings from
                ~/.xanes_gui_settings.json.

TomoScan moves the sample back to SampleInX/SampleInY after flat fields,
so before a Tomo or 3D XANES DataMap sets those to the current map
position and restores them afterwards. Otherwise every position would be
scanned at the same place.

Tab 2 ("PVs") holds the X/Y motor PVs and the detector/TomoScan names.
Settings persist to ~/.pystream/bl32ID_settings.json under "DataMapDialog".
"""

import json
import os
import re
import signal
import socket
import subprocess
import time
import logging
from typing import Optional, List, Dict, Any

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .plugin_settings import load_settings, save_settings
from ...scan_status import ScanStatus

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


# ── Defaults ─────────────────────────────────────────────────────────────

ACTIONS = [            # (key, column title) — also the run order per position
    ("image",   "Image"),
    ("xanes2d", "2D XANES"),
    ("tomo",    "Tomo"),
    ("xanes3d", "3D XANES"),
]
ACTION_TITLE = dict(ACTIONS)

DEFAULT_PVS = {
    "x_name": "TopX",  "x_pv": "32idbTXM:mcs:c1:m2",
    "y_name": "TopZ",  "y_pv": "32idbTXM:mcs:c1:m1",
    "motor_tol_mm":    0.001,
    "settle_s":        0.1,
    "detector_pva":    "32idbSP1:Pva1:Image",
    "camera_prefix":   "32idbSP1:cam1:",
    "tomoscan_prefix": "32id:TomoScan:",
    "tomo_timeout_s":  6 * 3600,
}
DEFAULT_IMAGE = {
    "exposure_s":  0.1,
    "output_dir":  "/tmp",
    "ref_x_pv":    "32idbTXM:mcs:c1:m2",
    "ref_z_pv":    "32idbTXM:mcs:c1:m1",
    "ref_rot_pv":  "32idbTXM:ens:c1:m1",
    "ref_x_mm":    0.0,
    "ref_z_mm":    0.0,
    "ref_rot_deg": 0.0,
}

XANES2D_SETTINGS = os.path.expanduser("~/.xanes_gui_2d_settings.json")
XANES3D_SETTINGS = os.path.expanduser("~/.xanes_gui_settings.json")
XANES3D_ENERGY_PVS = ("32id:TXMOptics:XanesStart",
                      "32id:TXMOptics:XanesEnd",
                      "32id:TXMOptics:XanesStep")
# Same launch defaults as xanes_gui (headless.DEFAULTS / gui.DEFAULTS).
XANES3D_LAUNCH_DEFAULTS = {
    "remote_user": "usertxm",
    "remote_host": "gauss",
    "conda_env":   "tomoscan",
    "work_dir":    "/home/beams/USERTXM/epics/synApps/support/tomoscan/iocBoot/iocTomoScan_32ID/",
    "conda_path":  "/home/beams/USERTXM/conda/anaconda",
    "script_name": "/home/beams/USERTXM/Software/xanes_gui/xanes_energy.py",
}


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ── Scan-parameter sources ───────────────────────────────────────────────

def _read_json(path: str) -> dict:
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _age(path: str) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return "?"


def _energies_eV(start, end, step) -> List[float]:
    """Same rule as the XANES 2D GUI (gui_2d._energies_eV)."""
    s, e, d = float(start), float(end), float(step)
    if d <= 0:
        return []
    out, x = [], s
    while x <= e + 1e-6:
        out.append(round(x, 4))
        x += d
    return out


def xanes2d_config(tag: str, data_x: float, data_z: float):
    """(pvs, scan, params) for the XANES 2D ScanWorker, built from the 2D
    GUI's saved settings exactly like its Start button does
    (gui_2d._gather_config), with the DATA position set to (data_x,
    data_z) and the master file named after the map position."""
    from xanes_gui import gui_2d
    d = _read_json(XANES2D_SETTINGS)
    if not d:
        raise RuntimeError(f"no XANES 2D settings at {XANES2D_SETTINGS} — "
                           "open XANES 2D, set the scan, press Save Settings")
    pvs = dict(gui_2d.DEFAULTS)
    pvs.update({k: v for k, v in d.get("pvs", {}).items() if v not in (None, "")})
    pvs = {k: (v.strip() if isinstance(v, str) else v) for k, v in pvs.items()}
    pvs["energy_tol"] = float(pvs.get("energy_tol") or gui_2d.DEFAULTS["energy_tol"])

    sc = d.get("scan", {})
    opt = lambda k: (float(sc[k]) if str(sc.get(k, "")).strip() else None)
    energies = _energies_eV(sc["e_start"], sc["e_end"], sc["e_step"])
    if not energies:
        raise RuntimeError("XANES 2D settings give no energies")
    cal = gui_2d.load_bl_gui_zp_cal_points()
    if not cal:
        raise RuntimeError("no ZP calibration in bl_gui (need ≥2 points) — "
                           "XANES 2D cannot follow focus")
    scan = {
        "energies_eV":  energies,
        "exposure_s":   float(sc["exposure"]),
        "topx_data_mm": float(data_x),
        "topz_data_mm": float(data_z),
        "rot_data_deg": opt("rot_data"),
        "topx_ref_mm":  float(sc["topx_ref"]),
        "topz_ref_mm":  float(sc["topz_ref"]),
        "rot_ref_deg":  opt("rot_ref"),
    }
    stem, ext = os.path.splitext(sc.get("master_name") or "xanes2d_scan.h5")
    params = {
        "zp_cal_points":        cal,
        "zp_cal_source":        gui_2d.BL_GUI_CAL_FILE,
        "motor_settle_s":       float(sc.get("motor_settle") or 0.5),
        "post_energy_settle_s": float(sc.get("post_energy_settle") or 0.0),
        "ref_every_n":          max(1, int(float(sc.get("ref_every") or 1))),
        "master_path": os.path.join(sc.get("save_dir") or "/tmp",
                                    f"{stem}_{tag}{ext or '.h5'}"),
        "qgmax_every_n":   int(float(sc.get("qgmax_every") or 0)),
        "qgmax_pv":        sc.get("qgmax_pv", ""),
        "qgmax_timeout_s": float(sc.get("qgmax_timeout") or 300.0),
        "repeat_count":      1,
        "repeat_interval_s": 0.0,
        # the shutter choices made in the XANES 2D GUI
        "use_fast_shutter": bool(sc.get("use_fast_shutter", True)),
        "use_b_shutter":    bool(sc.get("use_b_shutter", True)),
    }
    return pvs, scan, params


def xanes2d_summary() -> str:
    d = _read_json(XANES2D_SETTINGS)
    if not d:
        return "not configured — open XANES 2D and press Save Settings"
    sc = d.get("scan", {})
    try:
        en = _energies_eV(sc["e_start"], sc["e_end"], sc["e_step"])
        return (f"{len(en)} energies {sc['e_start']}–{sc['e_end']} eV "
                f"(step {sc['e_step']}), exposure {sc.get('exposure')} s, "
                f"Ref X={sc.get('topx_ref')} Z={sc.get('topz_ref')}  "
                f"[saved {_age(XANES2D_SETTINGS)}]")
    except (KeyError, ValueError) as e:
        return f"settings incomplete ({e})"


def _caget_str(pv: str):
    if not HAS_EPICS:
        return None
    return caget(pv, as_string=True, timeout=1.0, use_monitor=False)


def _fresh(pv: str, timeout: float = 2.0):
    """caget that asks the IOC, not pyepics' monitor cache — the cache can
    still hold the value from before a put we just made."""
    return caget(pv, timeout=timeout, use_monitor=False)


def tomo_summary(prefix: str) -> str:
    if not HAS_EPICS:
        return "pyepics not installed"
    num = {k: _fresh(prefix + k, timeout=1.0) for k in
           ("NumAngles", "ExposureTime", "RotationStart", "RotationStep")}
    txt = {k: _caget_str(prefix + k) for k in ("FlatFieldMode", "FileName")}
    if all(v is None for v in num.values()):
        return f"TomoScan IOC {prefix} not reachable"
    return (f"{num['NumAngles']} angles from {num['RotationStart']:g}° step "
            f"{num['RotationStep']:g}°, exposure {num['ExposureTime']:g} s, "
            f"flats {txt['FlatFieldMode']}, file '{txt['FileName']}'; "
            f"runs `tomoscan single` (conda env {xanes3d_launch_config()['conda_env']})")


def xanes3d_launch_config() -> dict:
    cfg = dict(XANES3D_LAUNCH_DEFAULTS)
    cfg.update({k: v for k, v in _read_json(XANES3D_SETTINGS).items()
                if k in XANES3D_LAUNCH_DEFAULTS and v})
    return cfg


def conda_command(cfg: dict, program: str, local_hint: str = "") -> List[str]:
    """Run `program` in the tomoscan conda env, locally if this machine can
    (same host, or the env / script is on the shared filesystem), else over
    ssh — the way the XANES GUI launches its scripts."""
    host = socket.gethostname()
    is_local = (host == cfg["remote_host"] or host.split(".")[0] == cfg["remote_host"]
                or cfg["remote_host"] in ("localhost", "127.0.0.1", "")
                or (local_hint and os.path.exists(local_hint)))
    inner = (f"cd {cfg['work_dir']} && "
             f"source {cfg['conda_path']}/etc/profile.d/conda.sh && "
             f"conda activate {cfg['conda_env']} && {program}")
    if is_local:
        return ["bash", "-l", "-c", inner]
    return ["ssh", "-t", f"{cfg['remote_user']}@{cfg['remote_host']}",
            f'bash -l -c "{inner}"']


def xanes3d_command(cfg: dict) -> List[str]:
    """Same command the XANES GUI's Start runs (gui.StartScriptWorker /
    headless.build_3d_launch_command)."""
    return conda_command(cfg, f"python {cfg['script_name']}", cfg["script_name"])


def tomo_command(cfg: dict, prefix: str) -> List[str]:
    """`tomoscan single` — the standard TomoScan CLI. It checks that the
    server is running and idle, runs one scan and waits for it."""
    return conda_command(cfg, f"tomoscan single --tomoscan-prefix {prefix}",
                         f"{cfg['conda_path']}/envs/{cfg['conda_env']}")


def xanes3d_summary() -> str:
    s, e, st = (_caget_str(pv) for pv in XANES3D_ENERGY_PVS)
    cfg = xanes3d_launch_config()
    if s is None:
        en = "energies: TXMOptics IOC not reachable"
    else:
        try:
            n = int((float(e) * 1000 - float(s) * 1000) / float(st)) + 1
            en = f"{n} energies {s}–{e} keV (step {st} eV)"
        except (TypeError, ValueError, ZeroDivisionError):
            en = f"energies {s}–{e} keV step {st}"
        en += ", tomography per energy uses the TomoScan settings"
    return f"{en}; runs {os.path.basename(cfg['script_name'])} on {cfg['remote_host']}"


# ── Collapsible section helper ───────────────────────────────────────────

class _CollapsibleSection(QtWidgets.QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.RightArrow)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._on_toggled)
        self.content = QtWidgets.QFrame()
        self.content.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.content_layout = QtWidgets.QFormLayout(self.content)
        self.content.setVisible(False)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.toggle)
        lay.addWidget(self.content)

    def _on_toggled(self, checked: bool):
        self.toggle.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
        self.content.setVisible(checked)


# ── Worker ───────────────────────────────────────────────────────────────

class _DataMapWorker(QtCore.QThread):
    """Runs the plan: [(row_idx, x, y, [action, ...]), ...]."""

    log      = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)   # positions done, total
    current  = QtCore.pyqtSignal(int)        # table row being worked on
    done     = QtCore.pyqtSignal()
    error    = QtCore.pyqtSignal(str)

    def __init__(self, plan, pvs, image, repeats=1, interval_s=0.0, parent=None):
        super().__init__(parent)
        self.plan, self.pvs, self.image = plan, pvs, image
        self.repeats = max(1, int(repeats))
        self.interval_s = max(0.0, float(interval_s))
        self._rep_tag = ""            # "r02_" while repeating; goes in file names
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None   # tomo caput / 3D script
        self._proc_is_tomo = False
        self._x2d_worker = None
        self._status: Optional[ScanStatus] = None

    def stop(self):
        """Called from the GUI thread. Ends the running action, then the
        plan stops at the next check."""
        self._stop = True
        if self._x2d_worker is not None:
            self._x2d_worker._stop = True
        p = self._proc
        if p is not None and p.poll() is None:
            if self._proc_is_tomo:
                subprocess.run(["caput", self.pvs["tomoscan_prefix"] + "AbortScan", "1"],
                               capture_output=True, timeout=5)
                self.log.emit("    abort sent to TomoScan")
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except OSError:
                pass

    # ── EPICS helpers ───────────────────────────────────────────────────

    def _put(self, pv, val, wait=True, timeout=120.0):
        if not caput(pv, val, wait=wait, timeout=timeout):
            raise RuntimeError(f"caput {pv}={val} failed")

    def _move(self, pv, target) -> bool:
        """Move a motor and confirm with .RBV. False if it did not get there."""
        self.log.emit(f"    move {pv} → {target:.4f}")
        try:
            self._put(pv, float(target), wait=True, timeout=300.0)
        except RuntimeError as e:
            self.log.emit(f"    ✗ {e}")
            return False
        # A motor record completes the put when the move is done; still
        # poll the readback briefly in case the encoder lags.
        deadline, rbv = time.monotonic() + 10.0, None
        while True:
            rbv = _fresh(pv + ".RBV")
            if rbv is not None and abs(float(rbv) - float(target)) <= self.pvs["motor_tol_mm"]:
                time.sleep(self.pvs["settle_s"])
                return True
            if time.monotonic() > deadline or self._stop:
                self.log.emit(f"    ✗ {pv} at {rbv}, wanted {target:.4f}")
                return False
            time.sleep(0.1)

    def _run_proc(self, cmd, is_tomo=False, keep=False):
        """Run a command, streaming its output to the log. `is_tomo` makes
        Stop also send TomoScan AbortScan. With `keep`, returns
        (rc, lines) instead of rc."""
        self._proc_is_tomo = is_tomo
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      bufsize=1, start_new_session=True)
        lines = []
        try:
            for line in self._proc.stdout:
                line = _ANSI.sub("", line).rstrip()     # tomoscan logs in colour
                if not line:
                    continue
                lines.append(line)
                self.log.emit("    " + line)
            rc = self._proc.wait()
            return (rc, lines) if keep else rc
        finally:
            self._proc = None

    # ── TomoScan sample-in pinning ─────────────────────────────────────

    def _pin_sample_in(self) -> Dict[str, Any]:
        """Set TomoScan SampleInX/Y to where its sample motors are now, so
        the scan returns here after flats. Returns the old values."""
        pre = self.pvs["tomoscan_prefix"]
        old = {}
        for axis in ("X", "Y"):
            motor = _caget_str(f"{pre}Sample{axis}PVName")
            if not motor:
                self.log.emit(f"    [WARN] {pre}Sample{axis}PVName unreadable; "
                              f"SampleIn{axis} left as is")
                continue
            here = _fresh(motor.strip() + ".RBV")
            prev = _fresh(f"{pre}SampleIn{axis}")
            if here is None or prev is None:
                self.log.emit(f"    [WARN] cannot read {motor}/SampleIn{axis}")
                continue
            old[f"{pre}SampleIn{axis}"] = prev
            self._put(f"{pre}SampleIn{axis}", float(here), timeout=5)
            self.log.emit(f"    SampleIn{axis} = {float(here):.4f} (was {float(prev):.4f})")
        return old

    def _restore(self, old: Dict[str, Any]):
        for pv, v in old.items():
            try:
                self._put(pv, v, timeout=5)
            except RuntimeError as e:
                self.log.emit(f"    [WARN] restore {e}")

    # ── Actions ────────────────────────────────────────────────────────

    def _snap(self):
        if not HAS_PVA:
            raise RuntimeError("pvaccess not installed")
        cam = self.pvs["camera_prefix"]
        exp = float(self.image["exposure_s"])
        self._put(f"{cam}AcquireTime", exp, wait=True, timeout=5)
        self._put(f"{cam}ImageMode", 0, wait=True, timeout=5)      # Single
        self._put(f"{cam}Acquire", 1, wait=True, timeout=exp * 3 + 10)
        st = pva.Channel(self.pvs["detector_pva"]).get("")
        val = st["value"][0]
        flat = np.asarray(next(iter(val.values())))
        dims = st["dimension"]
        return flat.reshape(int(dims[1]["size"]), int(dims[0]["size"]))

    def _do_image(self, n, x, y):
        sample = self._snap()
        im = self.image
        refs = [(im["ref_x_pv"], im["ref_x_mm"]), (im["ref_z_pv"], im["ref_z_mm"]),
                (im["ref_rot_pv"], im["ref_rot_deg"])]
        refs = [(pv, v) for pv, v in refs if pv]
        back = [(pv, _fresh(pv + ".RBV")) for pv, _ in refs]
        try:
            for pv, v in refs:
                if not self._move(pv, v):
                    raise RuntimeError(f"flat position not reached ({pv})")
            flat = self._snap()
        finally:
            for pv, v in reversed(back):
                if v is not None:
                    self._move(pv, v)
        out = im["output_dir"]
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"datamap_p{n:03d}_{time.strftime('%Y%m%d_%H%M%S')}.h5")
        with h5py.File(path, "w") as f:
            ex = f.create_group("exchange")
            ex.create_dataset("data", data=sample[np.newaxis])
            ex.create_dataset("data_flat", data=flat[np.newaxis])
            meta = f.create_group("measurement/instrument/datamap")
            meta.attrs["position"] = n
            for name, pv, v in ((self.pvs['x_name'], self.pvs['x_pv'], x),
                                (self.pvs['y_name'], self.pvs['y_pv'], y)):
                v = _fresh(pv + ".RBV") if v is None else v
                if v is not None:
                    meta.attrs[f"{name}_mm"] = float(v)
        self.log.emit(f"    saved {path}")

    def _do_xanes2d(self, n, x, y):
        from xanes_gui import gui_2d
        d = _read_json(XANES2D_SETTINGS).get("pvs", {})
        topx = d.get("topx_pv") or gui_2d.DEFAULTS["topx_pv"]
        topz = d.get("topz_pv") or gui_2d.DEFAULTS["topz_pv"]
        # DATA position = wherever XANES 2D's own sample motors are now,
        # i.e. at this map position. Its Ref position stays as saved.
        dx, dz = _fresh(topx + ".RBV"), _fresh(topz + ".RBV")
        if dx is None or dz is None:
            raise RuntimeError(f"cannot read XANES 2D sample motors {topx}/{topz}")
        pvs, scan, params = xanes2d_config(f"{self._rep_tag}p{n:03d}", dx, dz)
        self.log.emit(f"    {len(scan['energies_eV'])} energies, data at "
                      f"{topx}={dx:.4f} {topz}={dz:.4f} → {params['master_path']}")
        w = gui_2d.ScanWorker(pvs, scan, params)
        result = {"path": None, "error": None}
        direct = QtCore.Qt.DirectConnection
        w.log.connect(lambda m: self.log.emit("    " + m), direct)
        w.error.connect(lambda m: result.__setitem__("error", m), direct)
        w.done.connect(lambda p: result.__setitem__("path", p), direct)
        self._x2d_worker = w
        try:
            w.run()            # inline in this thread, no second QThread
        finally:
            self._x2d_worker = None
        if result["error"]:
            raise RuntimeError(result["error"])

    def _do_tomo(self, n, x, y):
        old = self._pin_sample_in()
        try:
            cmd = tomo_command(xanes3d_launch_config(), self.pvs["tomoscan_prefix"])
            self.log.emit(f"    {cmd[-1] if cmd[0] == 'ssh' else cmd[-1].split('&& ')[-1]}")
            rc, out = self._run_proc(cmd, is_tomo=True, keep=True)
            if self._stop:
                return
            # `tomoscan single` exits 0 even when it refuses to scan.
            # (its message really says "is not runnig")
            refused = [l for l in out if any(k in l.lower() for k in
                       ("is busy", "is not runn", "cannot connect", "not found"))]
            if rc != 0 or refused:
                raise RuntimeError(refused[0].strip() if refused
                                   else f"tomoscan exit code {rc}")
            if not any("scan end" in l.lower() for l in out):
                raise RuntimeError("tomoscan finished without 'scan end' — check the log above")
        finally:
            self._restore(old)

    def _do_xanes3d(self, n, x, y):
        old = self._pin_sample_in()
        try:
            cmd = xanes3d_command(xanes3d_launch_config())
            self.log.emit(f"    {' '.join(cmd)}")
            rc = self._run_proc(cmd)
            if rc != 0 and not self._stop:
                raise RuntimeError(f"3D XANES script exit code {rc}")
        finally:
            self._restore(old)

    # ── Main loop ───────────────────────────────────────────────────────

    def run(self):
        # Published to the shared scan registry (Agents panel, Slack bot).
        actions = sorted({ACTION_TITLE[a] for _r, _x, _y, acts in self.plan for a in acts})
        total = len(self.plan) * self.repeats
        self._status = status = ScanStatus(
            "DataMap", total=total, mode=", ".join(actions),
            positions=len(self.plan), repeats=self.repeats,
            interval_s=self.interval_s)
        outcome = None            # set on every exit path; None = crashed
        try:
            if HAS_EPICS:
                epics.ca.use_initial_context()
            failures = 0
            for k in range(1, self.repeats + 1):
                if self._stop:
                    break
                t0 = time.monotonic()
                if self.repeats > 1:
                    self._rep_tag = f"r{k:02d}_"
                    self.log.emit(f"══ repeat {k}/{self.repeats} ══")
                failures += self._run_plan(k)
                if k < self.repeats and not self._stop:
                    self._wait_until(t0 + self.interval_s, k + 1)
            if self._stop:
                self.log.emit("Stopped by user.")
                outcome = ("aborted", "stopped by user")
            elif failures:
                self.log.emit(f"Finished with {failures} failure(s) — see above.")
                outcome = ("finish", f"finished with {failures} failure(s)")
            else:
                outcome = ("finish", f"{total} position(s) done")
            self.done.emit()
        except Exception as e:
            outcome = ("error", f"{type(e).__name__}: {e}")
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            kind, text = outcome or ("error", "worker exited unexpectedly")
            getattr(status, kind)(text)

    def _wait_until(self, t_next: float, k_next: int):
        """Interval is start-to-start: wait out what is left of it."""
        left = t_next - time.monotonic()
        if left <= 0:
            self.log.emit(f"  repeat took longer than the interval — "
                          f"starting repeat {k_next} now")
            return
        at = time.strftime("%H:%M:%S", time.localtime(time.time() + left))
        self.log.emit(f"  waiting {left / 60:.1f} min — repeat {k_next} at {at}")
        if self._status is not None:
            self._status.activity(f"waiting — repeat {k_next}/{self.repeats} at {at}")
        while not self._stop and time.monotonic() < t_next:
            time.sleep(min(0.5, max(0.0, t_next - time.monotonic())))

    def _run_plan(self, k: int) -> int:
        failures = 0
        per = len(self.plan)
        total = per * self.repeats
        for i, (row, x, y, actions) in enumerate(self.plan, start=1):
            if self._stop:
                break
            n = row + 1
            done_before = (k - 1) * per
            self.current.emit(row)
            names = ", ".join(ACTION_TITLE[a] for a in actions)
            fmt = lambda v: "stay" if v is None else f"{v:.4f}"
            self.log.emit(f"[{i}/{per}] position #{n}  "
                          f"{self.pvs['x_name']}={fmt(x)} {self.pvs['y_name']}={fmt(y)}  "
                          f"→ {names}")
            if not ((x is None or self._move(self.pvs["x_pv"], x))
                    and (y is None or self._move(self.pvs["y_pv"], y))):
                self.log.emit(f"    ✗ position #{n} skipped: motors did not get there")
                failures += 1
                self.progress.emit(done_before + i, total)
                if self._status is not None:
                    self._status.step(done_before + i, total, f"position {i}/{per} (#{n}) skipped")
                continue
            for a in actions:
                if self._stop:
                    break
                self.log.emit(f"  ▶ {ACTION_TITLE[a]}")
                if self._status is not None:
                    rtag = f"repeat {k}/{self.repeats}, " if self.repeats > 1 else ""
                    self._status.activity(f"{rtag}position {i}/{per} (#{n}): {ACTION_TITLE[a]}")
                try:
                    getattr(self, f"_do_{a}")(n, x, y)
                    if not self._stop:
                        self.log.emit(f"  ✓ {ACTION_TITLE[a]} done")
                except Exception as e:
                    failures += 1
                    self.log.emit(f"  ✗ {ACTION_TITLE[a]} failed: {e}")
            self.progress.emit(done_before + i, total)
            if self._status is not None:
                self._status.step(done_before + i, total, f"position {i}/{per} (#{n}) done")
        return failures


# ── Dialog ───────────────────────────────────────────────────────────────

COL_N, COL_X, COL_Y = 0, 1, 2
COL_ACT0 = 3


class DataMapDialog(QtWidgets.QDialog):
    """Tab 1: mosaic grid + per-position actions. Tab 2: PVs."""

    BUTTON_TEXT  = "DataMap"
    GROUP        = "Scans"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("DataMap — bl32ID")
        self.resize(1000, 820)
        self._worker: Optional[_DataMapWorker] = None
        self._loading = False
        self._build_ui()
        self._restore_settings()
        self._refresh_sources()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_map_tab(), "Map")
        tabs.addTab(self._build_pv_tab(), "PVs")
        v.addWidget(tabs, 3)

        run_row = QtWidgets.QHBoxLayout()
        self.run_all_btn = QtWidgets.QPushButton("Run All")
        self.run_all_btn.clicked.connect(lambda: self._start(selected_only=False))
        self.run_sel_btn = QtWidgets.QPushButton("Run Selected")
        self.run_sel_btn.clicked.connect(lambda: self._start(selected_only=True))
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        self.progress = QtWidgets.QProgressBar()
        self.summary_lbl = QtWidgets.QLabel("")
        # Repeat the whole run N times; interval counted start to start.
        self.repeat_n = QtWidgets.QSpinBox()
        self.repeat_n.setRange(1, 10000)
        self.repeat_n.setPrefix("Repeat ")
        self.repeat_n.setSuffix(" ×")
        self.repeat_every = self._dspin(0, 100000, 1, 0.0, " min")
        self.repeat_every.setPrefix("every ")
        self.repeat_every.setToolTip(
            "Time from the start of one repeat to the start of the next. "
            "If a repeat takes longer, the next starts right away.")
        self.repeat_n.valueChanged.connect(
            lambda n: self.repeat_every.setEnabled(n > 1))
        self.repeat_every.setEnabled(False)
        for w in (self.run_all_btn, self.run_sel_btn, self.stop_btn,
                  self.repeat_n, self.repeat_every):
            run_row.addWidget(w)
        run_row.addWidget(self.progress, 1)
        run_row.addWidget(self.summary_lbl)
        v.addLayout(run_row)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)
        v.addWidget(self.log_text, 2)

    def _dspin(self, lo, hi, dec, val=0.0, suffix=""):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi); s.setDecimals(dec); s.setValue(val)
        if suffix:
            s.setSuffix(suffix)
        return s

    def _build_map_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        # ── Mosaic grid ────────────────────────────────────────────────
        grid_box = QtWidgets.QGroupBox("Mosaic grid")
        g = QtWidgets.QGridLayout(grid_box)
        for c, t in enumerate(("", "Start [mm]", "Step [mm]", "Points")):
            g.addWidget(QtWidgets.QLabel(f"<b>{t}</b>"), 0, c)
        self.x_lbl, self.y_lbl = QtWidgets.QLabel("X"), QtWidgets.QLabel("Y")
        self.x_start = self._dspin(-1000, 1000, 4)
        self.x_step = self._dspin(-100, 100, 4, 0.5)
        self.x_n = QtWidgets.QSpinBox(); self.x_n.setRange(1, 500); self.x_n.setValue(3)
        self.y_start = self._dspin(-1000, 1000, 4)
        self.y_step = self._dspin(-100, 100, 4, 0.5)
        self.y_n = QtWidgets.QSpinBox(); self.y_n.setRange(1, 500); self.y_n.setValue(3)
        for r, row in enumerate(((self.x_lbl, self.x_start, self.x_step, self.x_n),
                                 (self.y_lbl, self.y_start, self.y_step, self.y_n)), 1):
            for c, wid in enumerate(row):
                g.addWidget(wid, r, c)
        self.from_here_btn = QtWidgets.QPushButton("Start = current position")
        self.from_here_btn.clicked.connect(self._start_from_current)
        self.gen_btn = QtWidgets.QPushButton("Generate grid")
        self.gen_btn.setToolTip("Replace the table with this grid (serpentine order)")
        self.gen_btn.clicked.connect(self._generate_grid)
        g.addWidget(self.from_here_btn, 1, 4)
        g.addWidget(self.gen_btn, 2, 4)
        v.addWidget(grid_box)

        # ── Positions table ────────────────────────────────────────────
        pos_box = QtWidgets.QGroupBox(
            "Positions (click a column title to toggle it for the selected / all rows)")
        pv = QtWidgets.QVBoxLayout(pos_box)
        self.table = QtWidgets.QTableWidget(0, COL_ACT0 + len(ACTIONS))
        self.table.setHorizontalHeaderLabels(
            ["#", "X [mm]", "Y [mm]"] + [t for _, t in ACTIONS])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_N, QtWidgets.QHeaderView.ResizeToContents)
        hh.sectionClicked.connect(self._on_header_clicked)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(lambda _i: self._update_summary())
        pv.addWidget(self.table, 1)
        btns = QtWidgets.QHBoxLayout()
        for text, slot in (("+ Current position", self._add_current),
                           ("+ Row (stay here)", lambda: self._add_row(None, None)),
                           ("Remove selected", self._remove_selected),
                           ("Clear", self._clear)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        pv.addLayout(btns)
        v.addWidget(pos_box, 1)

        # ── Where the scan parameters come from ────────────────────────
        src_box = QtWidgets.QGroupBox("Scan parameters (from the owning plugins)")
        f = QtWidgets.QFormLayout(src_box)
        self.src_lbl = {}
        for key, title in ACTIONS[1:]:
            lbl = QtWidgets.QLabel("…")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.src_lbl[key] = lbl
            f.addRow(f"{title}:", lbl)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_sources)
        f.addRow("", refresh)
        v.addWidget(src_box)

        # ── Image settings (DataMap's own) ─────────────────────────────
        sec = _CollapsibleSection("Image settings (exposure, flat position, output)")
        self.exposure = self._dspin(0.001, 60, 3, 0.1, " s")
        self.output_dir = QtWidgets.QLineEdit()
        self.ref_x_pv, self.ref_z_pv, self.ref_rot_pv = (QtWidgets.QLineEdit() for _ in range(3))
        self.ref_x_mm = self._dspin(-100, 100, 4)
        self.ref_z_mm = self._dspin(-100, 100, 4)
        self.ref_rot = self._dspin(-360, 360, 3)
        for label, wid in (("Exposure:", self.exposure), ("Output directory:", self.output_dir),
                           ("Flat: X motor PV", self.ref_x_pv), ("Flat: X [mm]", self.ref_x_mm),
                           ("Flat: Z motor PV", self.ref_z_pv), ("Flat: Z [mm]", self.ref_z_mm),
                           ("Flat: rotation PV", self.ref_rot_pv), ("Flat: rotation [deg]", self.ref_rot)):
            sec.content_layout.addRow(label, wid)
        v.addWidget(sec)
        return w

    def _build_pv_tab(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.x_name, self.x_pv = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.y_name, self.y_pv = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.x_name.textChanged.connect(self._update_axis_names)
        self.y_name.textChanged.connect(self._update_axis_names)
        self.motor_tol = self._dspin(0.00001, 1, 5, 0.001, " mm")
        self.settle = self._dspin(0, 30, 2, 0.1, " s")
        self.detector_pva = QtWidgets.QLineEdit()
        self.camera_prefix = QtWidgets.QLineEdit()
        self.tomo_prefix = QtWidgets.QLineEdit()
        self.tomo_timeout = QtWidgets.QSpinBox()
        self.tomo_timeout.setRange(60, 7 * 24 * 3600); self.tomo_timeout.setSuffix(" s")
        f.addRow(QtWidgets.QLabel("<b>Map motors</b>"))
        f.addRow("X name:", self.x_name); f.addRow("X motor PV:", self.x_pv)
        f.addRow("Y name:", self.y_name); f.addRow("Y motor PV:", self.y_pv)
        f.addRow("Position tolerance:", self.motor_tol)
        f.addRow("Settle after move:", self.settle)
        f.addRow(QtWidgets.QLabel("<b>Detector (Image action)</b>"))
        f.addRow("Detector PVA channel:", self.detector_pva)
        f.addRow("Camera prefix:", self.camera_prefix)
        f.addRow(QtWidgets.QLabel("<b>TomoScan (Tomo / 3D XANES)</b>"))
        f.addRow("TomoScan prefix:", self.tomo_prefix)
        f.addRow("Scan timeout:", self.tomo_timeout)
        note = QtWidgets.QLabel(
            "2D XANES and 3D XANES PVs are the ones saved in their own plugins.")
        note.setWordWrap(True)
        f.addRow(note)
        return w

    # ── Table model ─────────────────────────────────────────────────────

    def _add_row(self, x: Optional[float], y: Optional[float], actions=()):
        """x/y None = empty cell = that axis is not moved."""
        self._loading = True
        try:
            r = self.table.rowCount()
            self.table.insertRow(r)
            num = QtWidgets.QTableWidgetItem()
            num.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.table.setItem(r, COL_N, num)
            self.table.setItem(r, COL_X, QtWidgets.QTableWidgetItem(
                "" if x is None else f"{x:.4f}"))
            self.table.setItem(r, COL_Y, QtWidgets.QTableWidgetItem(
                "" if y is None else f"{y:.4f}"))
            for i, (key, _t) in enumerate(ACTIONS):
                it = QtWidgets.QTableWidgetItem()
                it.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                            | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if key in actions else QtCore.Qt.Unchecked)
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(r, COL_ACT0 + i, it)
        finally:
            self._loading = False
        self._renumber()

    def _renumber(self):
        self._loading = True
        for r in range(self.table.rowCount()):
            self.table.item(r, COL_N).setText(str(r + 1))
        self._loading = False
        self._update_summary()

    def _rows(self) -> List[Dict[str, Any]]:
        out = []
        for r in range(self.table.rowCount()):
            def num(c):
                """None for an empty cell (= don't move), "bad" for junk."""
                txt = (self.table.item(r, c).text() if self.table.item(r, c) else "").strip()
                if not txt:
                    return None
                try:
                    return float(txt)
                except ValueError:
                    return "bad"
            acts = [key for i, (key, _t) in enumerate(ACTIONS)
                    if self.table.item(r, COL_ACT0 + i).checkState() == QtCore.Qt.Checked]
            out.append({"x": num(COL_X), "y": num(COL_Y), "actions": acts})
        return out

    def _selected_rows(self) -> List[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _on_header_clicked(self, col: int):
        if col < COL_ACT0:
            return
        rows = self._selected_rows() or list(range(self.table.rowCount()))
        if not rows:
            return
        items = [self.table.item(r, col) for r in rows]
        new = (QtCore.Qt.Unchecked if all(i.checkState() == QtCore.Qt.Checked for i in items)
               else QtCore.Qt.Checked)
        for i in items:
            i.setCheckState(new)

    def _update_summary(self):
        if self._loading:
            return
        rows = self._rows()
        counts = {k: sum(k in r["actions"] for r in rows) for k, _ in ACTIONS}
        busy = sum(bool(r["actions"]) for r in rows)
        parts = [f"{ACTION_TITLE[k]} {n}" for k, n in counts.items() if n]
        self.summary_lbl.setText(f"{busy}/{len(rows)} positions"
                                 + (": " + ", ".join(parts) if parts else ""))

    def _update_axis_names(self):
        xn, yn = self.x_name.text() or "X", self.y_name.text() or "Y"
        self.x_lbl.setText(xn); self.y_lbl.setText(yn)
        self.table.setHorizontalHeaderItem(COL_X, QtWidgets.QTableWidgetItem(f"{xn} [mm]"))
        self.table.setHorizontalHeaderItem(COL_Y, QtWidgets.QTableWidgetItem(f"{yn} [mm]"))

    # ── Buttons ─────────────────────────────────────────────────────────

    def _generate_grid(self):
        if self.table.rowCount() and QtWidgets.QMessageBox.question(
                self, "Replace positions",
                f"Replace the {self.table.rowCount()} positions in the table?") \
                != QtWidgets.QMessageBox.Yes:
            return
        self.table.setRowCount(0)
        xs = [self.x_start.value() + i * self.x_step.value() for i in range(self.x_n.value())]
        ys = [self.y_start.value() + j * self.y_step.value() for j in range(self.y_n.value())]
        # Serpentine: every other row runs backwards, so the stage never
        # flies back across the whole map between rows.
        for j, y in enumerate(ys):
            for x in (xs if j % 2 == 0 else reversed(xs)):
                self._add_row(x, y)
        self._log(f"Grid: {len(xs)}×{len(ys)} = {len(xs) * len(ys)} positions")

    def _read_xy(self):
        if not HAS_EPICS:
            raise RuntimeError("pyepics not installed")
        x = _fresh(self.x_pv.text().strip() + ".RBV")
        y = _fresh(self.y_pv.text().strip() + ".RBV")
        if x is None or y is None:
            raise RuntimeError(f"cannot read {self.x_pv.text()} / {self.y_pv.text()}")
        return float(x), float(y)

    def _start_from_current(self):
        try:
            x, y = self._read_xy()
        except RuntimeError as e:
            self._log(f"[ERROR] {e}")
            return
        self.x_start.setValue(x); self.y_start.setValue(y)

    def _add_current(self):
        try:
            self._add_row(*self._read_xy())
        except RuntimeError as e:
            self._log(f"[ERROR] {e}")

    def _remove_selected(self):
        for r in reversed(self._selected_rows()):
            self.table.removeRow(r)
        self._renumber()

    def _clear(self):
        self.table.setRowCount(0)
        self._update_summary()

    def _refresh_sources(self):
        for key, fn in (("xanes2d", xanes2d_summary),
                        ("tomo", lambda: tomo_summary(self.tomo_prefix.text().strip())),
                        ("xanes3d", xanes3d_summary)):
            try:
                self.src_lbl[key].setText(fn())
            except Exception as e:
                self.src_lbl[key].setText(f"unavailable: {e}")

    def _log(self, msg):
        self.log_text.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    # ── Run ─────────────────────────────────────────────────────────────

    def _pvs(self) -> Dict[str, Any]:
        return {
            "x_name": self.x_name.text().strip() or "X", "x_pv": self.x_pv.text().strip(),
            "y_name": self.y_name.text().strip() or "Y", "y_pv": self.y_pv.text().strip(),
            "motor_tol_mm": self.motor_tol.value(), "settle_s": self.settle.value(),
            "detector_pva": self.detector_pva.text().strip(),
            "camera_prefix": self.camera_prefix.text().strip(),
            "tomoscan_prefix": self.tomo_prefix.text().strip(),
            "tomo_timeout_s": self.tomo_timeout.value(),
        }

    def _image(self) -> Dict[str, Any]:
        return {
            "exposure_s": self.exposure.value(), "output_dir": self.output_dir.text().strip(),
            "ref_x_pv": self.ref_x_pv.text().strip(), "ref_x_mm": self.ref_x_mm.value(),
            "ref_z_pv": self.ref_z_pv.text().strip(), "ref_z_mm": self.ref_z_mm.value(),
            "ref_rot_pv": self.ref_rot_pv.text().strip(), "ref_rot_deg": self.ref_rot.value(),
        }

    def _preflight(self, plan) -> List[str]:
        """Problems that would make a run fail — checked before moving."""
        p, probs = self._pvs(), []
        if not HAS_EPICS:
            probs.append("pyepics not installed")
        if any(x is not None for _r, x, _y, _a in plan) and not p["x_pv"]:
            probs.append("set the X motor PV (PVs tab), or leave X empty to stay")
        if any(y is not None for _r, _x, y, _a in plan) and not p["y_pv"]:
            probs.append("set the Y motor PV (PVs tab), or leave Y empty to stay")
        used = {a for *_, acts in plan for a in acts}
        if "image" in used and not (HAS_PVA and HAS_H5PY):
            probs.append("Image needs pvaccess and h5py")
        if "xanes2d" in used:
            try:
                xanes2d_config("check", 0.0, 0.0)
            except Exception as e:
                probs.append(f"2D XANES: {e}")
        return probs

    def _start(self, selected_only: bool):
        if self._worker and self._worker.isRunning():
            return
        rows = self._rows()
        idx = self._selected_rows() if selected_only else range(len(rows))
        plan, bad = [], []
        for r in idx:
            row = rows[r]
            if not row["actions"]:
                continue
            if "bad" in (row["x"], row["y"]):
                bad.append(str(r + 1))
                continue
            plan.append((r, row["x"], row["y"], row["actions"]))
        if bad:
            QtWidgets.QMessageBox.warning(self, "Bad positions",
                                          "Rows with invalid X/Y: " + ", ".join(bad))
            return
        if not plan:
            QtWidgets.QMessageBox.information(
                self, "Nothing to do",
                "Tick at least one action (Image / 2D XANES / Tomo / 3D XANES) "
                "on the positions to run.")
            return
        probs = self._preflight(plan)
        if probs:
            QtWidgets.QMessageBox.warning(self, "Cannot start", "\n".join(probs))
            return
        n_act = sum(len(a) for *_, a in plan)
        self._save_settings()
        self._refresh_sources()
        self._log("=" * 60)
        reps, every = self.repeat_n.value(), self.repeat_every.value()
        self._log(f"DataMap: {len(plan)} positions, {n_act} actions"
                  + (f", repeated {reps}× every {every:g} min" if reps > 1 else ""))
        self._worker = _DataMapWorker(plan, self._pvs(), self._image(),
                                      repeats=reps, interval_s=every * 60.0)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(lambda d, t: (self.progress.setMaximum(t),
                                                    self.progress.setValue(d)))
        self._worker.current.connect(self.table.selectRow)
        self._worker.done.connect(self._finish)
        self._worker.error.connect(lambda m: (self._log(f"[ERROR] {m}"), self._finish()))
        self.progress.setValue(0)
        self._set_running(True)
        self._worker.start()

    def _on_stop(self):
        if self._worker and self._worker.isRunning():
            self._log("Stop requested — ending the current action…")
            self._worker.stop()

    def _finish(self):
        self._log("DataMap finished.")
        self._set_running(False)

    def _set_running(self, on: bool):
        self.run_all_btn.setEnabled(not on)
        self.run_sel_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        self.gen_btn.setEnabled(not on)

    # ── Persistence ─────────────────────────────────────────────────────

    def _restore_settings(self):
        s = load_settings(self.__class__.__name__)
        p, im = dict(DEFAULT_PVS), dict(DEFAULT_IMAGE)
        if "pvs" not in s:
            # Settings from the earlier DataMap (motor list + "acquisition").
            for axis, m in zip(("x", "y"), s.get("motors") or []):
                p[f"{axis}_name"], p[f"{axis}_pv"] = m.get("name", axis.upper()), m.get("pv", "")
            acq = s.get("acquisition", {})
            p.update({k: v for k, v in acq.items() if k in ("detector_pva", "camera_prefix")})
            im.update({k: v for k, v in acq.items() if k in im})
        p.update(s.get("pvs", {}))
        im.update(s.get("image", {}))

        self.x_name.setText(p["x_name"]); self.x_pv.setText(p["x_pv"])
        self.y_name.setText(p["y_name"]); self.y_pv.setText(p["y_pv"])
        self.motor_tol.setValue(float(p["motor_tol_mm"])); self.settle.setValue(float(p["settle_s"]))
        self.detector_pva.setText(p["detector_pva"]); self.camera_prefix.setText(p["camera_prefix"])
        self.tomo_prefix.setText(p["tomoscan_prefix"]); self.tomo_timeout.setValue(int(p["tomo_timeout_s"]))
        self.exposure.setValue(float(im["exposure_s"])); self.output_dir.setText(im["output_dir"])
        self.ref_x_pv.setText(im["ref_x_pv"]); self.ref_x_mm.setValue(float(im["ref_x_mm"]))
        self.ref_z_pv.setText(im["ref_z_pv"]); self.ref_z_mm.setValue(float(im["ref_z_mm"]))
        self.ref_rot_pv.setText(im["ref_rot_pv"]); self.ref_rot.setValue(float(im["ref_rot_deg"]))

        rp = s.get("repeat", {})
        self.repeat_n.setValue(int(rp.get("n", 1)))
        self.repeat_every.setValue(float(rp.get("every_min", 0.0)))

        gr = s.get("grid", {})
        for wid, k in ((self.x_start, "x_start"), (self.x_step, "x_step"),
                       (self.y_start, "y_start"), (self.y_step, "y_step")):
            if k in gr:
                wid.setValue(float(gr[k]))
        if "x_n" in gr: self.x_n.setValue(int(gr["x_n"]))
        if "y_n" in gr: self.y_n.setValue(int(gr["y_n"]))

        for row in s.get("map", []):
            try:
                fx = lambda v: None if v is None else float(v)
                self._add_row(fx(row.get("x")), fx(row.get("y")), row.get("actions", []))
            except (KeyError, TypeError, ValueError):
                pass
        self._update_axis_names()

    def _save_settings(self):
        save_settings(self.__class__.__name__, {
            "pvs":   self._pvs(),
            "image": self._image(),
            "grid":  {"x_start": self.x_start.value(), "x_step": self.x_step.value(),
                      "x_n": self.x_n.value(), "y_start": self.y_start.value(),
                      "y_step": self.y_step.value(), "y_n": self.y_n.value()},
            "map":   [r for r in self._rows() if "bad" not in (r["x"], r["y"])],
            "repeat": {"n": self.repeat_n.value(), "every_min": self.repeat_every.value()},
        })

    def closeEvent(self, e):
        if self._worker and self._worker.isRunning():
            if QtWidgets.QMessageBox.question(
                    self, "DataMap running",
                    "A map is running. Stop it and close?") != QtWidgets.QMessageBox.Yes:
                e.ignore()
                return
            self._worker.stop()
            self._worker.wait(5000)
        try:
            self._save_settings()
        except Exception:
            pass
        super().closeEvent(e)
