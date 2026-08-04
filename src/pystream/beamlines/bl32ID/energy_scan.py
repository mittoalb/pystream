"""
Energy-scan calibration / XANES 2D script for bl32ID TXM.

For each energy in [E_start, E_end, DE]:
  1. Set mono energy (with optional mono offset applied to true energy).
  2. Adjust ZP motor to the experimental focal position using the finite-
     conjugate formula s = (L - sqrt(L^2 - 4Lf))/2 + eps, with
     L = camera_distance + f(E).
  3. Move sample to DATA position (topx, topz [, rot]) and acquire an image.
  4. Move sample to REFERENCE position (topx_ref, topz_ref, rot_ref) and
     acquire an image.
  5. Log energy, ZP position, and file names to CSV.

Intended uses:
  - Zone-plate focus-vs-energy calibration by tracking a resolution pattern
    across the plane perpendicular to beam propagation.
  - XANES 2D imaging: same loop, treat each (data, ref) pair as the
    sample/flat for that energy step.

Configuration: pass a YAML (or JSON) file containing the fields of
`ScanConfig` below.

Usage:
    python energy_scan.py --config scan.yaml
    python energy_scan.py --config scan.yaml --dry-run

Requires `caget` and `caput` on PATH (EPICS base).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple

import h5py
import numpy as np


HC_EV_NM = 1239.84198  # eV·nm

# ── physics helpers (matches optics_calc.py) ─────────────────────────────

def zp_focal_length_mm(energy_eV: float, diameter_um: float, drn_nm: float,
                       mono_offset_eV: float = 0.0) -> Optional[float]:
    """Thin-lens ZP focal length: f = D·Δrn / λ, λ = hc/(E − mono_offset)."""
    e_true = energy_eV - mono_offset_eV
    if e_true <= 0:
        return None
    wavelength_nm = HC_EV_NM / e_true
    return (diameter_um * 1000.0 * drn_nm / wavelength_nm) * 1e-6


def zp_motor_position_mm(energy_eV: float, L_mm: float, diameter_um: float,
                         drn_nm: float, mono_offset_eV: float = 0.0,
                         eps_mm: float = 0.0) -> Optional[float]:
    """ZP motor position for focus on sample at distance L from detector."""
    f = zp_focal_length_mm(energy_eV, diameter_um, drn_nm, mono_offset_eV)
    if f is None or L_mm <= 0:
        return None
    disc = L_mm * L_mm - 4.0 * L_mm * f
    if disc < 0:
        return None
    return (L_mm - disc ** 0.5) / 2.0 + eps_mm


# ── EPICS I/O via caget/caput subprocess ─────────────────────────────────

class CAError(RuntimeError):
    pass


def caget(pv: str, timeout: float = 5.0) -> str:
    r = subprocess.run(['caget', '-t', pv],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise CAError(f"caget {pv} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def caget_float(pv: str, timeout: float = 5.0) -> float:
    return float(caget(pv, timeout))


def caput(pv: str, value, timeout: float = 60.0, wait: bool = True) -> None:
    cmd = ['caput']
    if wait:
        cmd.append('-c')
    cmd += [pv, str(value)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise CAError(f"caput {pv} {value!r} failed: {r.stderr.strip()}")


def caput_string(pv: str, value: str, timeout: float = 5.0) -> None:
    """Write a string to a char-waveform PV (AreaDetector FilePath/Name)."""
    r = subprocess.run(['caput', '-S', pv, value],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise CAError(f"caput -S {pv} {value!r} failed: {r.stderr.strip()}")


# ── configuration ─────────────────────────────────────────────────────────

@dataclass
class ScanConfig:
    # Energy range (eV)
    e_start_eV: float
    e_end_eV: float
    de_eV: float
    mono_offset_eV: float = 30.0

    # Sample positions (mm, deg)
    topx_data_mm: float = 0.0
    topz_data_mm: float = 0.0
    rot_data_deg: Optional[float] = None  # None = leave rotation untouched
    topx_ref_mm: float = 0.0
    topz_ref_mm: float = 0.0
    rot_ref_deg: Optional[float] = None   # None = leave rotation untouched

    # Zone plate parameters
    zp_diameter_um: float = 300.0
    zp_drn_nm: float = 30.0           # effective drn (from calibration)
    zp_eps_mm: float = 0.0            # residual motor-zero offset

    # Geometry
    camera_distance_mm: float = 3500.0  # ZP-to-detector; L = camera + f(E)

    # PVs — EDIT for your beamline
    energy_pv: str = "32ida:BraggEAO"
    energy_wait_pv: Optional[str] = None   # if mono has a "done moving" PV
    zp_motor_pv: str = "32id:m1"
    topx_pv: str = "32id:m2"
    topz_pv: str = "32id:m3"
    rot_pv: str = "32id:m4"

    # AreaDetector + file plugin (HDF5 scratch files to be merged)
    cam_prefix: str = "32idbSP1:cam1"
    file_plugin_prefix: str = "32idbSP1:HDF1"
    ad_hdf5_image_path: str = "/entry/data/data"  # dataset inside each AD file

    # Acquisition
    exposure_s: float = 1.0
    num_images: int = 1
    trigger_mode: str = "Internal"

    # Output
    save_dir: str = "./calib_scan"
    master_h5_name: str = "scan.h5"
    scratch_subdir: str = "_scratch"
    delete_scratch_after_copy: bool = True
    hdf5_compression: str = "gzip"    # "gzip", "lzf", or "" for none
    hdf5_compression_opts: int = 3

    # Settle times (s)
    motor_settle_s: float = 0.5
    post_energy_settle_s: float = 2.0
    acquire_poll_s: float = 0.1

    # Options
    take_reference: bool = True
    return_to_data_position_after_ref: bool = True


def energy_list(start: float, end: float, step: float) -> List[float]:
    if step <= 0:
        raise ValueError("de_eV must be > 0")
    energies: List[float] = []
    e = start
    # inclusive of end up to floating tolerance
    while e <= end + 1e-6:
        energies.append(round(e, 4))
        e += step
    return energies


def load_config(path: str) -> ScanConfig:
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() in ('.yaml', '.yml'):
        import yaml  # lazy import; only needed for YAML configs
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    return ScanConfig(**raw)


# ── motion + acquisition ─────────────────────────────────────────────────

def move_motor(pv: str, target: float, settle_s: float) -> None:
    caput(pv, target, wait=True)
    if settle_s > 0:
        time.sleep(settle_s)


def set_energy(cfg: ScanConfig, energy_eV: float) -> None:
    caput(cfg.energy_pv, energy_eV, wait=True, timeout=120)
    if cfg.energy_wait_pv:
        # Optional: poll a "moving" PV if the mono has one
        for _ in range(600):
            try:
                v = caget_float(cfg.energy_wait_pv)
                if abs(v) < 0.5:  # 0 = done
                    break
            except CAError:
                break
            time.sleep(0.2)
    if cfg.post_energy_settle_s > 0:
        time.sleep(cfg.post_energy_settle_s)


def set_zp_focus(cfg: ScanConfig, energy_eV: float) -> float:
    f = zp_focal_length_mm(energy_eV, cfg.zp_diameter_um, cfg.zp_drn_nm,
                           cfg.mono_offset_eV)
    if f is None:
        raise ValueError(f"Invalid focal length at E={energy_eV} eV")
    L_mm = cfg.camera_distance_mm + f
    s = zp_motor_position_mm(energy_eV, L_mm, cfg.zp_diameter_um, cfg.zp_drn_nm,
                             cfg.mono_offset_eV, cfg.zp_eps_mm)
    if s is None:
        raise ValueError(f"No finite-conjugate solution at E={energy_eV} eV")
    move_motor(cfg.zp_motor_pv, s, cfg.motor_settle_s)
    return s


def configure_file_save(cfg: ScanConfig, file_dir: Path, file_stem: str) -> None:
    """Point AD's HDF1 plugin at a scratch file (one per acquisition)."""
    file_dir.mkdir(parents=True, exist_ok=True)
    prefix = cfg.file_plugin_prefix
    caput_string(f"{prefix}:FilePath", str(file_dir) + os.sep)
    caput_string(f"{prefix}:FileName", file_stem)
    caput(f"{prefix}:AutoSave", 1, wait=True)
    caput(f"{prefix}:AutoIncrement", 1, wait=True)
    # Single = one file per acquisition
    caput(f"{prefix}:FileWriteMode", 0, wait=True)
    caput(f"{prefix}:EnableCallbacks", 1, wait=True)


def acquire_one(cfg: ScanConfig) -> Path:
    """Trigger one acquisition; return the path of the file AD wrote."""
    caput(f"{cfg.cam_prefix}:AcquireTime", cfg.exposure_s, wait=True)
    caput(f"{cfg.cam_prefix}:NumImages", cfg.num_images, wait=True)
    caput(f"{cfg.cam_prefix}:ImageMode", 0 if cfg.num_images == 1 else 1, wait=True)
    try:
        caput_string(f"{cfg.cam_prefix}:TriggerMode", cfg.trigger_mode)
    except CAError:
        pass

    caput(f"{cfg.cam_prefix}:Acquire", 1, wait=False)

    busy_pv = f"{cfg.cam_prefix}:AcquireBusy"
    t0 = time.time()
    timeout = max(30.0, cfg.exposure_s * cfg.num_images * 3.0 + 10.0)
    while True:
        try:
            busy = caget_float(busy_pv)
        except CAError:
            busy = 0.0
        if busy < 0.5:
            break
        if time.time() - t0 > timeout:
            raise TimeoutError(f"Acquisition did not finish within {timeout:.0f} s")
        time.sleep(cfg.acquire_poll_s)

    # Give the file plugin a beat to flush before we read it.
    time.sleep(0.2)
    full = caget(f"{cfg.file_plugin_prefix}:FullFileName_RBV")
    return Path(full)


def read_ad_hdf5_frame(ad_file: Path, dataset_path: str) -> np.ndarray:
    """Read a single frame from an AreaDetector-written HDF5 file."""
    with h5py.File(ad_file, 'r') as f:
        arr = f[dataset_path][...]
    # AD writes (N, H, W) even for single frames
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    return np.asarray(arr)


# ── master HDF5 writer: /exchange/data and /exchange/data_flat ──────────

class MasterH5:
    """Single master HDF5 with growable data / flat stacks and full metadata.

    Layout:
      /exchange/
        data              (N, H, W)   — sample frames
        data_flat         (N, H, W)   — reference frames
        energy            (N,)  [eV]
        zp_position_mm    (N,)  [mm]
      /measurement/instrument/<group>       — static attrs set at scan start
      /measurement/per_step/<field>         — growable readback datasets
    """

    PER_STEP_FIELDS = [
        ("timestamp_epoch", "s (epoch)"),
        ("energy_rbv_eV",   "eV"),
        ("zp_rbv_mm",       "mm"),
        ("topx_data_rbv",   "mm"),
        ("topz_data_rbv",   "mm"),
        ("rot_data_rbv",    "deg"),
        ("topx_ref_rbv",    "mm"),
        ("topz_ref_rbv",    "mm"),
        ("rot_ref_rbv",     "deg"),
        ("step_time_s",     "s"),
    ]

    def __init__(self, path: Path, cfg: ScanConfig):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = h5py.File(self.path, 'w')
        self.f.attrs['created'] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.f.attrs['format'] = "bl32ID energy_scan v1"
        self.f.attrs['scan_config'] = json.dumps(asdict(cfg), indent=2, default=str)

        self._compress_kwargs = {}
        if cfg.hdf5_compression:
            self._compress_kwargs['compression'] = cfg.hdf5_compression
            if cfg.hdf5_compression == 'gzip':
                self._compress_kwargs['compression_opts'] = cfg.hdf5_compression_opts

        self.exchange = self.f.create_group('exchange')
        self._data_ds = None
        self._flat_ds = None
        self._energy_ds = self.exchange.create_dataset(
            'energy', shape=(0,), maxshape=(None,), dtype='f8')
        self._energy_ds.attrs['units'] = 'eV'
        self._zp_ds = self.exchange.create_dataset(
            'zp_position_mm', shape=(0,), maxshape=(None,), dtype='f8')
        self._zp_ds.attrs['units'] = 'mm'

        self.measurement = self.f.create_group('measurement')
        self.instrument = self.measurement.create_group('instrument')
        self.per_step = self.measurement.create_group('per_step')
        self._step_ds = {}
        for name, units in self.PER_STEP_FIELDS:
            ds = self.per_step.create_dataset(
                name, shape=(0,), maxshape=(None,), dtype='f8')
            ds.attrs['units'] = units
            self._step_ds[name] = ds

    def write_instrument_snapshot(self, snapshot: dict) -> None:
        """snapshot = {group_name: {attr_name: value, ...}, ...}"""
        for group_name, attrs in snapshot.items():
            grp = self.instrument.require_group(group_name)
            for k, v in attrs.items():
                if v is None:
                    continue
                try:
                    grp.attrs[k] = v
                except TypeError:
                    grp.attrs[k] = str(v)

    def _ensure_stack(self, name: str, sample: np.ndarray) -> h5py.Dataset:
        if name in self.exchange:
            return self.exchange[name]
        h, w = sample.shape[-2:]
        ds = self.exchange.create_dataset(
            name,
            shape=(0, h, w),
            maxshape=(None, h, w),
            chunks=(1, h, w),
            dtype=sample.dtype,
            **self._compress_kwargs,
        )
        return ds

    def append_data(self, arr: np.ndarray) -> None:
        if self._data_ds is None:
            self._data_ds = self._ensure_stack('data', arr)
        n = self._data_ds.shape[0]
        self._data_ds.resize(n + 1, axis=0)
        self._data_ds[n] = arr

    def append_flat(self, arr: np.ndarray) -> None:
        if self._flat_ds is None:
            self._flat_ds = self._ensure_stack('data_flat', arr)
        n = self._flat_ds.shape[0]
        self._flat_ds.resize(n + 1, axis=0)
        self._flat_ds[n] = arr

    def append_meta(self, energy_eV: float, zp_position_mm: float) -> None:
        n = self._energy_ds.shape[0]
        self._energy_ds.resize(n + 1, axis=0)
        self._energy_ds[n] = energy_eV
        n = self._zp_ds.shape[0]
        self._zp_ds.resize(n + 1, axis=0)
        self._zp_ds[n] = zp_position_mm

    def append_step_readbacks(self, readbacks: dict) -> None:
        for name, _ in self.PER_STEP_FIELDS:
            ds = self._step_ds[name]
            n = ds.shape[0]
            ds.resize(n + 1, axis=0)
            val = readbacks.get(name)
            try:
                ds[n] = float(val) if val is not None else float('nan')
            except (TypeError, ValueError):
                ds[n] = float('nan')

    def set_end_time(self) -> None:
        self.f.attrs['finished'] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def flush(self) -> None:
        self.f.flush()

    def close(self) -> None:
        try:
            self.f.flush()
        finally:
            self.f.close()


# ── main scan loop ───────────────────────────────────────────────────────

_stop_requested = False


def _sigint_handler(signum, frame):
    global _stop_requested
    _stop_requested = True
    print("\n[!] Ctrl-C received — finishing current step then stopping.", flush=True)


def move_to_data_position(cfg: ScanConfig) -> None:
    if cfg.rot_data_deg is not None:
        move_motor(cfg.rot_pv, cfg.rot_data_deg, cfg.motor_settle_s)
    move_motor(cfg.topx_pv, cfg.topx_data_mm, cfg.motor_settle_s)
    move_motor(cfg.topz_pv, cfg.topz_data_mm, cfg.motor_settle_s)


def move_to_ref_position(cfg: ScanConfig) -> None:
    move_motor(cfg.topx_pv, cfg.topx_ref_mm, cfg.motor_settle_s)
    move_motor(cfg.topz_pv, cfg.topz_ref_mm, cfg.motor_settle_s)
    if cfg.rot_ref_deg is not None:
        move_motor(cfg.rot_pv, cfg.rot_ref_deg, cfg.motor_settle_s)


def _acquire_and_read(cfg: ScanConfig, scratch_dir: Path,
                      stem: str) -> Tuple[np.ndarray, Path]:
    """Trigger acquisition via AD HDF1 plugin, read the frame from disk."""
    configure_file_save(cfg, scratch_dir, stem)
    ad_file = acquire_one(cfg)
    arr = read_ad_hdf5_frame(ad_file, cfg.ad_hdf5_image_path)
    return arr, ad_file


def _try_caget_float(pv: str) -> Optional[float]:
    try:
        return caget_float(pv, timeout=2.0)
    except Exception:
        return None


def _try_caget(pv: str) -> Optional[str]:
    try:
        return caget(pv, timeout=2.0)
    except Exception:
        return None


def _motor_rbv(motor_pv: str) -> Optional[float]:
    if not motor_pv:
        return None
    v = _try_caget_float(f"{motor_pv}.RBV")
    if v is None:
        v = _try_caget_float(motor_pv)
    return v


def _collect_instrument_snapshot(cfg: ScanConfig, frame_shape) -> dict:
    """Capture all static instrument/geometry info for /measurement/instrument."""
    cam = cfg.cam_prefix
    optics_prefix = "32id:TXMOptics"
    H, W = int(frame_shape[-2]), int(frame_shape[-1])

    detector = {
        "exposure_time_s": float(cfg.exposure_s),
        "num_images_per_point": int(cfg.num_images),
        "trigger_mode": cfg.trigger_mode,
        "manufacturer": _try_caget(f"{cam}:Manufacturer_RBV"),
        "model": _try_caget(f"{cam}:Model_RBV"),
        "data_type": _try_caget(f"{cam}:DataType_RBV"),
        "image_height_px": H,
        "image_width_px": W,
        "size_x_rbv": _try_caget_float(f"{cam}:SizeX_RBV"),
        "size_y_rbv": _try_caget_float(f"{cam}:SizeY_RBV"),
        "binx": _try_caget_float(f"{cam}:BinX"),
        "biny": _try_caget_float(f"{cam}:BinY"),
        "min_x": _try_caget_float(f"{cam}:MinX"),
        "min_y": _try_caget_float(f"{cam}:MinY"),
        "temperature_c": _try_caget_float(f"{cam}:Temperature_RBV"),
        "detector_pv_prefix": cam,
        "file_plugin_prefix": cfg.file_plugin_prefix,
    }
    optics = {
        "zp_diameter_um": cfg.zp_diameter_um,
        "zp_drn_nm": cfg.zp_drn_nm,
        "zp_eps_mm": cfg.zp_eps_mm,
        "mono_offset_eV": cfg.mono_offset_eV,
        "camera_distance_mm": cfg.camera_distance_mm,
        "zp_motor_pv": cfg.zp_motor_pv,
        "image_pixel_size_nm": _try_caget_float(f"{optics_prefix}:ImagePixelSize"),
        "crop_left": _try_caget_float(f"{optics_prefix}:CropLeft"),
        "crop_right": _try_caget_float(f"{optics_prefix}:CropRight"),
        "crop_top": _try_caget_float(f"{optics_prefix}:CropTop"),
        "crop_bottom": _try_caget_float(f"{optics_prefix}:CropBottom"),
    }
    mono = {
        "energy_pv": cfg.energy_pv,
        "energy_wait_pv": cfg.energy_wait_pv,
        "post_energy_settle_s": cfg.post_energy_settle_s,
    }
    sample = {
        "topx_pv": cfg.topx_pv,
        "topz_pv": cfg.topz_pv,
        "rot_pv": cfg.rot_pv,
        "motor_settle_s": cfg.motor_settle_s,
        "topx_data_mm": cfg.topx_data_mm,
        "topz_data_mm": cfg.topz_data_mm,
        "rot_data_deg": cfg.rot_data_deg,
        "topx_ref_mm": cfg.topx_ref_mm,
        "topz_ref_mm": cfg.topz_ref_mm,
        "rot_ref_deg": cfg.rot_ref_deg,
        "topx_initial_rbv": _motor_rbv(cfg.topx_pv),
        "topz_initial_rbv": _motor_rbv(cfg.topz_pv),
        "rot_initial_rbv": _motor_rbv(cfg.rot_pv),
    }
    return {
        "detector": detector,
        "zone_plate_and_optics": optics,
        "monochromator": mono,
        "sample_stage": sample,
    }


def run_scan(cfg: ScanConfig) -> None:
    signal.signal(signal.SIGINT, _sigint_handler)

    energies = energy_list(cfg.e_start_eV, cfg.e_end_eV, cfg.de_eV)
    root = Path(cfg.save_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch_dir = root / cfg.scratch_subdir
    scratch_dir.mkdir(parents=True, exist_ok=True)

    master_path = root / cfg.master_h5_name
    master = MasterH5(master_path, cfg)

    log_path = root / "scan_log.csv"
    new_log = not log_path.exists()
    log_file = open(log_path, "a", newline="")
    logger = csv.writer(log_file)
    if new_log:
        logger.writerow(["timestamp_iso", "index", "energy_eV", "zp_position_mm",
                         "data_ad_file", "flat_ad_file"])

    print(f"Scanning {len(energies)} energies: {energies[0]} → {energies[-1]} eV "
          f"(step {cfg.de_eV} eV)")
    print(f"Output master file: {master_path}")

    instrument_snapshot_written = False
    try:
        for i, e in enumerate(energies, start=1):
            if _stop_requested:
                print("Stopping on user request.")
                break

            t_start = time.time()
            print(f"[{i}/{len(energies)}] E = {e:.2f} eV", flush=True)

            set_energy(cfg, e)
            energy_rbv = _try_caget_float(cfg.energy_pv)
            zp_pos = set_zp_focus(cfg, e)
            zp_rbv = _motor_rbv(cfg.zp_motor_pv) or zp_pos
            print(f"    ZP motor → {zp_pos:.4f} mm")

            # DATA
            move_to_data_position(cfg)
            data_topx = _motor_rbv(cfg.topx_pv)
            data_topz = _motor_rbv(cfg.topz_pv)
            data_rot = _motor_rbv(cfg.rot_pv)
            data_arr, data_file = _acquire_and_read(cfg, scratch_dir, "data")
            master.append_data(data_arr)
            print(f"    /exchange/data[{master._data_ds.shape[0]-1}] "
                  f"shape={data_arr.shape} dtype={data_arr.dtype}")

            if not instrument_snapshot_written:
                master.write_instrument_snapshot(
                    _collect_instrument_snapshot(cfg, data_arr.shape))
                instrument_snapshot_written = True

            # REF
            flat_file_name = ""
            ref_topx = ref_topz = ref_rot = None
            if cfg.take_reference:
                move_to_ref_position(cfg)
                ref_topx = _motor_rbv(cfg.topx_pv)
                ref_topz = _motor_rbv(cfg.topz_pv)
                ref_rot = _motor_rbv(cfg.rot_pv)
                flat_arr, flat_file = _acquire_and_read(cfg, scratch_dir, "flat")
                master.append_flat(flat_arr)
                print(f"    /exchange/data_flat[{master._flat_ds.shape[0]-1}] "
                      f"shape={flat_arr.shape} dtype={flat_arr.dtype}")
                flat_file_name = str(flat_file)
                if cfg.return_to_data_position_after_ref:
                    move_to_data_position(cfg)
                if cfg.delete_scratch_after_copy:
                    try:
                        flat_file.unlink()
                    except OSError:
                        pass

            master.append_meta(e, zp_pos)
            master.append_step_readbacks({
                "timestamp_epoch": time.time(),
                "energy_rbv_eV": energy_rbv,
                "zp_rbv_mm": zp_rbv,
                "topx_data_rbv": data_topx,
                "topz_data_rbv": data_topz,
                "rot_data_rbv": data_rot,
                "topx_ref_rbv": ref_topx,
                "topz_ref_rbv": ref_topz,
                "rot_ref_rbv": ref_rot,
                "step_time_s": time.time() - t_start,
            })
            master.flush()

            if cfg.delete_scratch_after_copy:
                try:
                    data_file.unlink()
                except OSError:
                    pass

            logger.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                i, f"{e:.4f}", f"{zp_pos:.6f}",
                str(data_file), flat_file_name,
            ])
            log_file.flush()
            print(f"    step time: {time.time() - t_start:.1f} s", flush=True)
    finally:
        master.set_end_time()
        master.close()
        log_file.close()
        if cfg.delete_scratch_after_copy:
            try:
                scratch_dir.rmdir()
            except OSError:
                pass  # not empty — keep any residual files for debugging
        print(f"Log written to {log_path}")
        print(f"Master HDF5: {master_path}")


def print_dry_run(cfg: ScanConfig) -> None:
    energies = energy_list(cfg.e_start_eV, cfg.e_end_eV, cfg.de_eV)
    print(f"DRY RUN — {len(energies)} energy points")
    print(f"  range: {cfg.e_start_eV} → {cfg.e_end_eV} eV, step {cfg.de_eV} eV")
    print(f"  mono offset: {cfg.mono_offset_eV} eV")
    print(f"  ZP: D={cfg.zp_diameter_um} µm, Δrn_eff={cfg.zp_drn_nm} nm, "
          f"eps={cfg.zp_eps_mm} mm")
    print(f"  camera distance: {cfg.camera_distance_mm} mm")
    print(f"  data  pos: topx={cfg.topx_data_mm}, topz={cfg.topz_data_mm}, "
          f"rot={cfg.rot_data_deg}")
    print(f"  ref   pos: topx={cfg.topx_ref_mm}, topz={cfg.topz_ref_mm}, "
          f"rot={cfg.rot_ref_deg}")
    print(f"  take reference: {cfg.take_reference}")
    print(f"  output root: {cfg.save_dir}")
    print()
    print(f"{'idx':>4} {'E [eV]':>10} {'f [mm]':>10} {'L [mm]':>10} {'ZP pos [mm]':>12}")
    for i, e in enumerate(energies, start=1):
        f = zp_focal_length_mm(e, cfg.zp_diameter_um, cfg.zp_drn_nm,
                               cfg.mono_offset_eV)
        if f is None:
            print(f"{i:>4} {e:>10.2f}  <invalid>")
            continue
        L = cfg.camera_distance_mm + f
        s = zp_motor_position_mm(e, L, cfg.zp_diameter_um, cfg.zp_drn_nm,
                                 cfg.mono_offset_eV, cfg.zp_eps_mm)
        s_txt = f"{s:.4f}" if s is not None else "  N/A"
        print(f"{i:>4} {e:>10.2f} {f:>10.3f} {L:>10.3f} {s_txt:>12}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--config', required=True, help="YAML or JSON config path")
    ap.add_argument('--dry-run', action='store_true',
                    help="Print the plan with computed ZP positions and exit")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)

    if args.dry_run:
        print_dry_run(cfg)
        return 0

    run_scan(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
