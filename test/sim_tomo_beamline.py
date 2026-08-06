#!/usr/bin/env python3
"""
Synthetic bl32ID beamline simulator for testing pystream plugins.

Two modes:

1) STREAM  (default) — soft-IOC + live PVA image publisher.
   - EPICS soft-IOC motors:
       32idbTXM:ens:c1:m1    (rotation, deg)
       32idbTXM:mcs:c1:m2    (topx,     mm)
       32idbTXM:mcs:c1:m1    (topz,     mm)
   - PVA channel: 32idbSP1:Pva1:Image  (NTNDArray, uint16)
   - Each published frame is a parallel-beam projection of a small 3D
     phantom (background stub + several particles) at the current
     motor RBVs. Poisson shot noise + Gaussian read noise + dark
     offset + a scatter of hot pixels are added for realism.
   - The rotation axis in image pixels is deliberately offset from
     image-center by COR_COL_OFFSET_PX so `CoR` / `AlignPart` plugins
     have a real number to converge on.

     $ python sim_tomo_beamline.py
     # then in pystream: connect the detector PV, use the toolbar

2) WRITE-H5  — writes a static synthetic HDF5 file for testing the
   HDF5 Viewer plugin. DXchange-compatible layout: /exchange/data,
   /exchange/data_white, /exchange/data_dark, /exchange/theta.

     $ python sim_tomo_beamline.py --write-h5 /tmp/sim_tomo.h5 --num-projections 90

Realism knobs (module constants at the top): FLUX, READ_NOISE,
DARK_OFFSET, N_HOT_PIXELS, COR_COL_OFFSET_PX.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from typing import List, Optional, Tuple

import numpy as np

# --- Sibling-import the NTNDArray helper from generate_test_images ----
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from generate_test_images import AdImageUtility
except ImportError as _ex:
    AdImageUtility = None  # type: ignore
    _AD_IMPORT_ERR = _ex

try:
    import pvaccess as pva
    _HAS_PVAPY = True
except Exception:
    _HAS_PVAPY = False

try:
    from pcaspy import Driver, SimpleServer
    _HAS_PCASPY = True
except Exception:
    Driver = object  # type: ignore
    SimpleServer = None  # type: ignore
    _HAS_PCASPY = False


# ── Terminal color helper ─────────────────────────────────────────────
# Silence colors when NO_COLOR is set (see https://no-color.org/) or
# when stdout isn't a tty (pipes / logs). Otherwise apply light styling
# so startup output is scannable rather than one wall of green text.

def _color_enabled() -> bool:
    if os.environ.get('NO_COLOR'):
        return False
    # Some multiplexers / IDEs report non-tty even for interactive
    # sessions. Users can override with --color=always (below).
    return sys.stdout.isatty() and os.environ.get('TERM', '') != 'dumb'


# Mutable so --color=always/never can override the auto-detected default
# BEFORE the first print. `_c()` reads this every call so late toggles
# work too.
_C_ON = _color_enabled()


def _set_color(mode: str) -> None:
    """mode: 'auto' | 'always' | 'never'."""
    global _C_ON
    if mode == 'always':
        _C_ON = True
    elif mode == 'never':
        _C_ON = False
    else:
        _C_ON = _color_enabled()


def _c(code: str, s: str) -> str:
    # Read the module-level toggle each call so --color=always works
    # even if applied after the helpers were first bound.
    return f"\033[{code}m{s}\033[0m" if _C_ON else s


def _bold(s: str) -> str:   return _c('1',    s)
def _dim(s: str) -> str:    return _c('2',    s)
def _red(s: str) -> str:    return _c('31',   s)
def _green(s: str) -> str:  return _c('32',   s)
def _yellow(s: str) -> str: return _c('33',   s)
def _blue(s: str) -> str:   return _c('34',   s)
def _magenta(s: str) -> str:return _c('35',   s)
def _cyan(s: str) -> str:   return _c('36',   s)


def _hdr(tag: str, msg: str) -> str:
    return f"{_bold(_cyan('['+tag+']'))} {msg}"


def _warn(msg: str) -> str:
    return f"{_bold(_yellow('[warn]'))} {msg}"


def _err(msg: str) -> str:
    return f"{_bold(_red('[fatal]'))} {msg}"


def _ok(msg: str) -> str:
    return f"{_bold(_green('[ok]'))} {msg}"


# ── Physical / simulator setup ────────────────────────────────────────

# Detector geometry
IMAGE_W = 1024
IMAGE_H = 1024
MM_PX   = 0.000766      # 0.766 µm/px (matches 32-ID TXM autocenter defaults)

# True CoR column offset from image center (px). Nonzero so the plugins
# have something to detect. Positive = right of center.
COR_COL_OFFSET_PX = 25.0

# Detector counts model.
FLUX           = 8000.0    # photons/pixel through empty beam
READ_NOISE     = 25.0      # Gaussian σ (counts)
DARK_OFFSET    = 100.0     # constant baseline (counts)
N_HOT_PIXELS   = 30        # random pixels stuck at ~saturation
ABSORPTION_SCL = 1.0       # multiplier on the phantom's absorption

# Phantom: list of (x_mm, y_mm, z_mm, radius_mm, absorption).
# Sample frame: z is vertical (rotation axis direction), x is horizontal
# perpendicular to the beam, y is along the beam.
# Rotation happens around z. Positive rotation angle = right-handed
# rotation around +z.
DEFAULT_PHANTOM: List[Tuple[float, float, float, float, float]] = [
    # Background sample stub — big, low-density (like a mounted rod).
    ( 0.000,  0.000,  0.000, 0.180, 0.20),
    # Discrete particles at various off-CoR positions the user can click.
    ( 0.055,  0.020,  0.050, 0.010, 1.60),
    (-0.040, -0.030, -0.020, 0.008, 1.90),
    ( 0.025, -0.060,  0.010, 0.014, 1.10),
    ( 0.075,  0.045, -0.045, 0.007, 2.10),
    (-0.010,  0.010, -0.060, 0.006, 1.80),
]

# PV names — hardcoded to match the bl32ID plugins.
ROT_PV  = '32idbTXM:ens:c1:m1'
TOPZ_PV = '32idbTXM:mcs:c1:m1'
TOPX_PV = '32idbTXM:mcs:c1:m2'
DETECTOR_PVA = '32idbSP1:Pva1:Image'


# ── Rendering ─────────────────────────────────────────────────────────

def _make_hot_pixel_mask(W: int, H: int, n: int,
                         seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    mask = np.zeros((H, W), dtype=bool)
    if n > 0:
        xs = rng.integers(0, W, n)
        ys = rng.integers(0, H, n)
        mask[ys, xs] = True
    return mask


def _make_flat_field(W: int, H: int, seed: int = 7) -> np.ndarray:
    """Slow-varying flat field for realism — a bright center that
    tapers off toward the edges (a la Gaussian beam profile), plus a
    little multiplicative structure."""
    rng = np.random.default_rng(seed=seed)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2.0, H / 2.0
    r2 = (x - cx) ** 2 + (y - cy) ** 2
    sigma = 0.8 * min(W, H) / 2.0
    ff = np.exp(-0.5 * r2 / (sigma ** 2))
    # Multiplicative low-freq noise.
    coarse = rng.normal(0.0, 0.05, (H // 32, W // 32)).astype(np.float32)
    coarse = np.repeat(np.repeat(coarse, 32, axis=0), 32, axis=1)[:H, :W]
    return np.clip(ff + coarse, 0.1, 1.5)


def render_projection(theta_deg: float, topx_mm: float, topz_mm: float,
                      spheres, *,
                      W: int = IMAGE_W, H: int = IMAGE_H,
                      mm_px: float = MM_PX,
                      cor_col_offset_px: float = COR_COL_OFFSET_PX,
                      flux: float = FLUX,
                      absorption_scale: float = ABSORPTION_SCL,
                      read_noise: float = READ_NOISE,
                      dark_offset: float = DARK_OFFSET,
                      hot_pixel_mask: Optional[np.ndarray] = None,
                      flat_field: Optional[np.ndarray] = None,
                      rng: Optional[np.random.Generator] = None,
                      dark_only: bool = False) -> np.ndarray:
    """Parallel-beam projection of `spheres` at (theta, topx, topz),
    plus Poisson + read + dark noise. Returns uint16 counts.

    `dark_only=True` skips the whole rendering path — useful for dark
    frames (shutter-closed reference)."""
    if rng is None:
        rng = np.random.default_rng()

    if dark_only:
        counts = rng.normal(dark_offset, max(read_noise, 1.0),
                            (H, W)).astype(np.float32)
        if hot_pixel_mask is not None:
            counts[hot_pixel_mask] = 65500.0
        return np.clip(counts, 0, 65535).astype(np.uint16)

    theta = np.deg2rad(theta_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    default_cor_col    = W / 2.0 + cor_col_offset_px
    default_center_row = H / 2.0

    # Accumulated absorption per pixel.
    absorb = np.zeros((H, W), dtype=np.float32)
    col_idx = np.arange(W, dtype=np.float32)
    row_idx = np.arange(H, dtype=np.float32)
    cols, rows = np.meshgrid(col_idx, row_idx)

    for x0, y0, z0, r, absorption in spheres:
        # Projected center after rotation and topx/topz shift.
        # Convention: positive topx moves the sample stage right, which
        # moves the rotation axis (and every feature) LEFT in the image
        # by topx_mm/mm_px. This matches AutoCenter/ParticleAlign's
        # mm_px = -0.000766 sign so the plugins converge, not diverge.
        cx = default_cor_col + (x0 * cos_t - y0 * sin_t - topx_mm) / mm_px
        cy = default_center_row + (z0 - topz_mm) / mm_px
        r_px = r / mm_px
        d2 = (cols - cx) ** 2 + (rows - cy) ** 2
        r2 = r_px * r_px
        mask = d2 < r2
        if mask.any():
            # Chord length through a solid sphere at pixel (col, row).
            absorb[mask] += absorption * 2.0 * np.sqrt(r2 - d2[mask])

    # Beer-Lambert transmitted intensity.
    if flat_field is not None:
        intensity = flat_field * flux * np.exp(-absorb * absorption_scale)
    else:
        intensity = flux * np.exp(-absorb * absorption_scale)

    # Poisson shot noise.
    counts = rng.poisson(np.clip(intensity, 0, 1e9)).astype(np.float32)
    # Gaussian read noise + dark offset.
    counts += rng.normal(0.0, read_noise, counts.shape).astype(np.float32)
    counts += dark_offset
    # Hot pixels stuck near saturation.
    if hot_pixel_mask is not None:
        counts[hot_pixel_mask] = 65500.0
    return np.clip(counts, 0, 65535).astype(np.uint16)


# ── Motor soft-IOC (pcaspy) ───────────────────────────────────────────

# Full PV list — base name, plus .VAL and .RBV for each motor.
_MOTOR_BASES = (ROT_PV, TOPZ_PV, TOPX_PV)


def _motor_pv_db() -> dict:
    db = {}
    for name in _MOTOR_BASES:
        base = {'type': 'float', 'value': 0.0, 'prec': 4}
        db[name]           = dict(base)
        db[name + '.VAL']  = dict(base)
        db[name + '.RBV']  = dict(base)
    return db


class _MotorDriver(Driver):
    """Fake motor driver: every caput echoes to the base, .VAL, and .RBV
    of the same motor. No ramping — the plugins use `caput -c`, which
    returns as soon as we ack the write, so ramping just complicates
    timing without helping the tests."""

    def write(self, reason, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        # Figure out the base PV name and mirror the write to all three
        # forms so any read style (.VAL, .RBV, or bare) returns the
        # same value.
        if reason.endswith('.RBV') or reason.endswith('.VAL'):
            base = reason[:-4]
        else:
            base = reason
        if base in _MOTOR_BASES:
            for suf in ('', '.VAL', '.RBV'):
                self.setParam(base + suf, v)
        else:
            self.setParam(reason, v)
        self.updatePVs()
        return True


class MotorIOC:
    """Owns the pcaspy server + driver in a background thread."""

    def __init__(self):
        if not _HAS_PCASPY:
            raise RuntimeError("pcaspy is not installed")
        self._server = SimpleServer()
        # Empty prefix — our PV names are fully qualified.
        self._server.createPV('', _motor_pv_db())
        self._driver = _MotorDriver()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name='sim-motor-ioc', daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self, pv: str) -> float:
        try:
            return float(self._driver.getParam(pv + '.RBV'))
        except Exception:
            return 0.0

    def _loop(self):
        while not self._stop.is_set():
            self._server.process(0.05)


# ── Image publisher (pvapy) ───────────────────────────────────────────

class ImagePublisher:
    """Renders + publishes NTNDArray at the requested FPS."""

    def __init__(self, pv: str, W: int, H: int,
                 spheres, motor_ioc: MotorIOC,
                 flux: float = FLUX,
                 read_noise: float = READ_NOISE,
                 dark_offset: float = DARK_OFFSET,
                 hot_n: int = N_HOT_PIXELS,
                 add_flat_field: bool = True,
                 seed: int = 0):
        if not _HAS_PVAPY:
            raise RuntimeError("pvaccess (pvapy) is not installed")
        if AdImageUtility is None:
            raise RuntimeError(
                f"Could not import AdImageUtility from generate_test_images: "
                f"{_AD_IMPORT_ERR}")
        self.pv = pv
        self.W, self.H = W, H
        self.spheres = spheres
        self.motor_ioc = motor_ioc
        self.flux = flux
        self.read_noise = read_noise
        self.dark_offset = dark_offset
        self.hot_pixel_mask = _make_hot_pixel_mask(W, H, hot_n)
        self.flat_field = _make_flat_field(W, H) if add_flat_field else None
        self._rng = np.random.default_rng(seed=seed)

        dummy = np.zeros((H, W), dtype=np.uint16)
        self._nt = AdImageUtility.generateNtNdArray2D(0, dummy)
        self._server = pva.PvaServer()
        self._server.addRecord(pv, self._nt)

        self._uid = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name='sim-image-pub', daemon=True)
        self._fps = 10.0

    def start(self, fps: float = 10.0):
        self._fps = max(0.1, float(fps))
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        interval = 1.0 / self._fps
        next_t = time.time()
        while not self._stop.is_set():
            theta = self.motor_ioc.get(ROT_PV)
            topz  = self.motor_ioc.get(TOPZ_PV)
            topx  = self.motor_ioc.get(TOPX_PV)
            img = render_projection(
                theta, topx, topz, self.spheres,
                W=self.W, H=self.H,
                flux=self.flux, read_noise=self.read_noise,
                dark_offset=self.dark_offset,
                hot_pixel_mask=self.hot_pixel_mask,
                flat_field=self.flat_field,
                rng=self._rng)
            self._uid += 1
            AdImageUtility.replaceNtNdArrayImage2D(self._nt, self._uid, img)
            self._server.update(self._nt)

            next_t += interval
            sleep = next_t - time.time()
            if sleep > 0:
                time.sleep(sleep)
            else:
                # We fell behind — resync so we don't spiral.
                next_t = time.time()


# ── HDF5 writer (for HDF5 Viewer testing) ─────────────────────────────

def write_synthetic_h5(path: str, n_proj: int, n_flats: int, n_darks: int,
                       W: int, H: int, spheres,
                       theta_start: float = 0.0, theta_stop: float = 180.0,
                       progress_every: int = 20, seed: int = 0):
    """DXchange-compatible HDF5: /exchange/{data, data_white, data_dark,
    theta}. Frames are the same synthetic projections the streamer
    generates, so the two paths give consistent data."""
    try:
        import h5py
    except ImportError:
        print(_err("h5py is not installed — `pip install h5py`."),
              file=sys.stderr)
        sys.exit(1)

    rng = np.random.default_rng(seed=seed)
    hot_mask = _make_hot_pixel_mask(W, H, N_HOT_PIXELS)
    flat_field = _make_flat_field(W, H)

    thetas = np.linspace(theta_start, theta_stop, n_proj, endpoint=False,
                         dtype=np.float32)
    print(_hdr('h5', f"Writing {_bold(str(n_proj))} projections + "
                     f"{_bold(str(n_flats))} flats + "
                     f"{_bold(str(n_darks))} darks  "
                     f"({W}×{H})  → {_magenta(path)}"))
    with h5py.File(path, 'w') as f:
        exch = f.create_group('exchange')
        # Datasets — one at a time to keep memory low.
        data_ds  = exch.create_dataset('data',       shape=(n_proj, H, W),
                                       dtype='u2', chunks=(1, H, W))
        white_ds = exch.create_dataset('data_white', shape=(n_flats, H, W),
                                       dtype='u2', chunks=(1, H, W))
        dark_ds  = exch.create_dataset('data_dark',  shape=(n_darks, H, W),
                                       dtype='u2', chunks=(1, H, W))
        exch.create_dataset('theta', data=thetas)

        # Projections.
        for i, theta in enumerate(thetas):
            data_ds[i] = render_projection(
                theta, 0.0, 0.0, spheres,
                W=W, H=H, hot_pixel_mask=hot_mask,
                flat_field=flat_field, rng=rng)
            if i % progress_every == 0:
                print(_dim(f"  proj {i:4d}/{n_proj}"))
        # Flats — empty phantom, same optics.
        for i in range(n_flats):
            white_ds[i] = render_projection(
                0.0, 0.0, 0.0, [],
                W=W, H=H, hot_pixel_mask=hot_mask,
                flat_field=flat_field, rng=rng)
        # Darks — shutter-closed noise only.
        for i in range(n_darks):
            dark_ds[i] = render_projection(
                0.0, 0.0, 0.0, [],
                W=W, H=H, hot_pixel_mask=hot_mask,
                rng=rng, dark_only=True)

        # A minimal `measurement/instrument` snapshot so tools that
        # look for it (e.g. tomoscan-compatible viewers) don't error.
        instr = f.create_group('measurement/instrument')
        det = instr.create_group('detection_system/detector')
        det.create_dataset('pixel_size',        data=np.float32(MM_PX))
        det.create_dataset('actual_pixel_size', data=np.float32(MM_PX))
        det.create_dataset('exposure_time',     data=np.float32(0.1))
    print(_ok(f"Wrote {_magenta(path)}"))


# ── main ──────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(
        prog='sim_tomo_beamline',
        description=("Synthetic bl32ID beamline. Streams NTNDArray + "
                     "soft-IOC motors by default; --write-h5 dumps a "
                     "static HDF5 file instead."))
    p.add_argument('--fps', type=float, default=10.0,
                   help='Frames per second in stream mode (default: 10).')
    p.add_argument('--width', type=int, default=IMAGE_W)
    p.add_argument('--height', type=int, default=IMAGE_H)
    p.add_argument('--pv', default=DETECTOR_PVA,
                   help=f'Detector PVA channel (default: {DETECTOR_PVA}).')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--no-flat-field', action='store_true',
                   help='Disable the multiplicative beam profile.')
    p.add_argument('--write-h5', metavar='PATH', default=None,
                   help='Instead of streaming, write a synthetic HDF5 file.')
    p.add_argument('--num-projections', type=int, default=180,
                   help='Number of projections (H5 mode; default 180).')
    p.add_argument('--num-flats', type=int, default=10)
    p.add_argument('--num-darks', type=int, default=10)
    p.add_argument('--color', choices=('auto', 'always', 'never'),
                   default='auto',
                   help=("Terminal color output. `auto` respects NO_COLOR "
                         "and skips when stdout is not a tty; `always` "
                         "forces color even when piped; `never` disables."))
    args = p.parse_args(argv)
    _set_color(args.color)

    if args.write_h5:
        write_synthetic_h5(
            args.write_h5, args.num_projections,
            args.num_flats, args.num_darks,
            args.width, args.height, DEFAULT_PHANTOM,
            seed=args.seed)
        return 0

    # Stream mode.
    if not _HAS_PCASPY:
        print(_err("pcaspy is not installed — `pip install pcaspy`."),
              file=sys.stderr)
        return 1
    if not _HAS_PVAPY:
        print(_err("pvaccess (pvapy) is not installed — `pip install pvapy`."),
              file=sys.stderr)
        return 1

    motor_ioc = MotorIOC()
    motor_ioc.start()
    print(_hdr('ioc', _green('motor IOC up')))
    for pv in _MOTOR_BASES:
        print(f"  {_cyan(pv):<32} {_dim('(+ .VAL and .RBV)')}")

    publisher = ImagePublisher(
        args.pv, args.width, args.height, DEFAULT_PHANTOM, motor_ioc,
        add_flat_field=not args.no_flat_field, seed=args.seed)
    publisher.start(fps=args.fps)
    print(_hdr('pva',
        f"publishing NTNDArray on {_cyan(args.pv)}   "
        f"({_bold(f'{args.width}×{args.height}')} @ "
        f"{_bold(f'{args.fps:g} fps')})"))
    print(_hdr('sim',
        f"true CoR column = {_bold(f'{args.width/2 + COR_COL_OFFSET_PX:.1f}')} "
        f"({_yellow(f'offset {COR_COL_OFFSET_PX:+.1f} px')} from center)"))
    print(_hdr('sim',
        f"phantom = {_bold(str(len(DEFAULT_PHANTOM)))} spheres. "
        f"drive via {_cyan('caput')} on the motor PVs above."))
    print(_dim("Ctrl-C to stop."))

    stop_event = threading.Event()

    def _shutdown(*_):
        print()  # newline after ^C
        print(_hdr('sim', _yellow('shutting down…')))
        publisher.stop()
        motor_ioc.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    stop_event.wait()
    return 0


if __name__ == '__main__':
    sys.exit(main())
