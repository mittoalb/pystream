"""
Particle → Center-of-Rotation Alignment Plugin for bl32ID

User clicks on a particle in the live pystream viewer. The plugin then:

  1. Segments the blob containing the click → centroid (cx0, cy0).
  2. Rotates the sample by 180°, re-segments the same particle at the
     mirrored position → (cx180, _).
  3. CoR column = (cx0 + cx180) / 2  — measured on the fly.
  4. Rotates back to the starting angle.
  5. Iterates: grab → segment → move topx / topz until the particle
     sits on (CoR column, image vertical center) within tolerance.

Motor safety: the rotation motor is guaranteed to return to θ₀ via a
`finally` block (even on abort or exception). topx / topz stay wherever
the last iteration left them — that's the whole point of the tool.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Optional

import numpy as np
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal

try:
    from scipy.ndimage import label as _ndimage_label
    _HAS_SCIPY = True
except Exception:
    _ndimage_label = None
    _HAS_SCIPY = False


# ── Hardcoded constants — edit here to retune ─────────────────────────
_ROT_PV     = "32idbTXM:ens:c1:m1"   # rotation motor
_TOPX_PV    = "32idbTXM:mcs:c1:m2"   # sample horizontal
_TOPZ_PV    = "32idbTXM:mcs:c1:m1"   # sample vertical
_MM_PX_X    = -0.000766              # mm per image pixel (sign = beam convention)
_MM_PX_Z    = -0.000766
_DELTA_DEG  = 180.0                  # rotation between the two CoR measurements
_SETTLE_S   = 1.0                    # sample settle after any motor move
_AVERAGE_N  = 3                      # frames averaged per grab
_TOL_PX     = 1.0                    # convergence tolerance in pixels
_MAX_ITER   = 6                      # max alignment iterations
_WIN_PX     = 200                    # segmentation window half-size
_SOFT_MIN_DEG = -180.0
_SOFT_MAX_DEG = 540.0


# ── Segmentation helpers (pure) ───────────────────────────────────────

def _otsu(img: np.ndarray) -> float:
    """Otsu's threshold — same implementation shape as autocenter's."""
    flat = img.astype(np.float64).ravel()
    if flat.size == 0:
        return 0.0
    hist, edges = np.histogram(flat, bins=256)
    mids = (edges[:-1] + edges[1:]) / 2.0
    total = flat.size
    sum_all = float((mids * hist).sum())
    sum_b = 0.0
    w_b = 0
    max_var = -1.0
    thresh = float(mids[0])
    for i in range(256):
        w_b += int(hist[i])
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += float(mids[i] * hist[i])
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > max_var:
            max_var = var
            thresh = float(mids[i])
    return thresh


def _crop_window(img: np.ndarray, cx: float, cy: float, half: int):
    """Return (subimage, x0, y0) — offsets are the crop origin so callers
    can convert local centroids back to full-image coords."""
    H, W = img.shape[:2]
    x0 = int(max(0, round(cx) - half))
    y0 = int(max(0, round(cy) - half))
    x1 = int(min(W, round(cx) + half))
    y1 = int(min(H, round(cy) + half))
    return img[y0:y1, x0:x1], x0, y0


def _segment_from_seed(img: np.ndarray, seed_x: float, seed_y: float,
                       sign: int, window_px: int = _WIN_PX,
                       nearest: bool = False):
    """Return (centroid_x, centroid_y, size_px, mask_area_bbox) or None.

    - `sign = +1`  → bright blob (peaks above Otsu of `+img`).
    - `sign = -1`  → dark blob (peaks above Otsu of `-img`).
    - `nearest = False` → pick the connected component that CONTAINS the
                          seed pixel (best when the user just clicked).
    - `nearest = True`  → pick the component whose centroid is CLOSEST to
                          the seed (best after a rotation or motor move,
                          when the blob has shifted).
    """
    if not _HAS_SCIPY:
        return None
    sub, x0, y0 = _crop_window(img, seed_x, seed_y, window_px)
    if sub.size == 0:
        return None
    signed = sign * sub.astype(np.float64)
    thresh = _otsu(signed)
    mask = signed > thresh
    if not mask.any():
        return None

    labeled, n = _ndimage_label(mask)
    if n == 0:
        return None

    # Local seed inside the cropped window.
    lx = int(round(seed_x - x0))
    ly = int(round(seed_y - y0))
    lx = max(0, min(sub.shape[1] - 1, lx))
    ly = max(0, min(sub.shape[0] - 1, ly))

    if nearest:
        chosen = _pick_nearest_cc(labeled, n, lx, ly)
    else:
        chosen = int(labeled[ly, lx])
        if chosen == 0:
            # Click landed on background — fall back to the biggest blob.
            chosen = _pick_largest_cc(labeled, n)

    if chosen == 0:
        return None
    pts = np.where(labeled == chosen)
    if pts[0].size < 5:
        return None
    cy_local = float(np.mean(pts[0]))
    cx_local = float(np.mean(pts[1]))
    return (cx_local + x0, cy_local + y0, int(pts[0].size))


def _pick_largest_cc(labeled: np.ndarray, n: int) -> int:
    best_lbl, best_size = 0, 0
    for lbl in range(1, n + 1):
        sz = int((labeled == lbl).sum())
        if sz > best_size:
            best_size = sz
            best_lbl = lbl
    return best_lbl


def _pick_nearest_cc(labeled: np.ndarray, n: int,
                     seed_x: int, seed_y: int) -> int:
    best_lbl, best_d2 = 0, float('inf')
    for lbl in range(1, n + 1):
        pts = np.where(labeled == lbl)
        if pts[0].size < 5:
            continue
        cy = float(np.mean(pts[0]))
        cx = float(np.mean(pts[1]))
        d2 = (cx - seed_x) ** 2 + (cy - seed_y) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_lbl = lbl
    return best_lbl


# ── Worker thread ─────────────────────────────────────────────────────

class _AlignWorker(QtCore.QThread):
    """Runs the CoR-find + iterative-align sequence off the GUI thread."""

    log = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, click_x: float, click_y: float, sign: int,
                 grab_fn):
        super().__init__()
        self.click_x = float(click_x)
        self.click_y = float(click_y)
        self.sign = int(sign)
        self._grab_fn = grab_fn
        self._abort = False

    def request_abort(self):
        self._abort = True

    # ── caget / caput (same shell idiom as autocenter/cor) ────────
    def _caget_float(self, pv: str) -> Optional[float]:
        try:
            r = subprocess.run(['caget', '-t', pv],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return float(r.stdout.strip())
        except Exception as ex:
            self.log.emit(f"caget {pv} failed: {ex}")
        return None

    def _caput_wait(self, pv: str, val: float) -> bool:
        try:
            r = subprocess.run(['caput', '-c', pv, str(val)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                self.log.emit(f"caput {pv} = {val:g} failed: "
                              f"{r.stderr.strip() or r.stdout.strip()}")
                return False
            return True
        except Exception as ex:
            self.log.emit(f"caput {pv} = {val:g} raised: {ex}")
            return False

    def _grab_averaged(self, n: int, timeout_s: float = 5.0) -> Optional[np.ndarray]:
        """Grab n distinct live frames and average. Same idiom as cor.py."""
        frames = []
        deadline = time.time() + timeout_s + 0.1 * n
        prev = None
        while len(frames) < n and time.time() < deadline:
            if self._abort:
                return None
            img = self._grab_fn()
            if img is None:
                time.sleep(0.05)
                continue
            if prev is not None and img is prev:
                time.sleep(0.05)
                continue
            frames.append(img.astype(np.float64, copy=True))
            prev = img
            time.sleep(0.05)
        if not frames:
            return None
        return np.mean(np.stack(frames, axis=0), axis=0)

    def _sleep_polled(self, seconds: float):
        t_end = time.time() + seconds
        while time.time() < t_end:
            if self._abort:
                return
            time.sleep(0.05)

    # ── Main sequence ─────────────────────────────────────────────
    def run(self):
        try:
            if not _HAS_SCIPY:
                self.failed.emit("scipy is not installed — cannot segment. "
                                 "`pip install scipy`.")
                return

            theta0 = self._caget_float(f"{_ROT_PV}.RBV")
            if theta0 is None:
                self.failed.emit(f"Could not read {_ROT_PV}.RBV")
                return
            self.log.emit(f"θ₀ = {theta0:.4f}°")

            theta_end = theta0 + _DELTA_DEG
            if not (_SOFT_MIN_DEG <= theta_end <= _SOFT_MAX_DEG):
                self.failed.emit(
                    f"Target angle {theta_end:.3f}° outside soft range "
                    f"[{_SOFT_MIN_DEG}, {_SOFT_MAX_DEG}] — refusing.")
                return

            # ── Step 1: segment at θ₀ from the click ──────────────
            img0 = self._grab_averaged(_AVERAGE_N)
            if img0 is None:
                self.failed.emit("No live frame at θ₀.")
                return
            H, W = img0.shape[:2]
            seg = _segment_from_seed(img0, self.click_x, self.click_y,
                                     self.sign, nearest=False)
            if seg is None:
                self.failed.emit("Could not segment a blob at the click point.")
                return
            cx0, cy0, sz0 = seg
            self.log.emit(f"Segment @ θ₀: centroid=({cx0:.1f}, {cy0:.1f})  "
                          f"[{sz0} px]")

            moved_forward = False
            try:
                # ── Step 2: rotate + settle + segment at θ₀+180 ───
                self.log.emit(f"Rotate to {theta_end:.4f}° …")
                if not self._caput_wait(_ROT_PV, theta_end):
                    self.failed.emit("Rotation to θ₀+Δ failed.")
                    return
                moved_forward = True
                self._sleep_polled(_SETTLE_S)
                if self._abort:
                    self.failed.emit("Aborted after +Δ rotation.")
                    return

                img180 = self._grab_averaged(_AVERAGE_N)
                if img180 is None:
                    self.failed.emit("No live frame at θ₀+Δ.")
                    return
                # We don't yet know the mirrored X position — search
                # nearest CC to (cx0, cy0), which for a not-too-far-from
                # CoR particle is close to the truth. Fallback to
                # largest blob if that misses.
                seg = _segment_from_seed(img180, cx0, cy0,
                                         self.sign, nearest=True)
                if seg is None:
                    self.failed.emit(
                        "Could not segment the particle at θ₀+Δ. "
                        "The particle may have rotated out of view — "
                        "aborting BEFORE moving topx/topz.")
                    return
                cx180, cy180, sz180 = seg
                self.log.emit(f"Segment @ θ₀+Δ: centroid=({cx180:.1f}, "
                              f"{cy180:.1f})  [{sz180} px]")

                # ── Step 3: compute CoR column ────────────────────
                c_rot = (cx0 + cx180) / 2.0
                self.log.emit(f"CoR column = {c_rot:.2f}")

                # ── Step 4: rotate back to θ₀ ─────────────────────
                self.log.emit(f"Rotate back to {theta0:.4f}°")
                if not self._caput_wait(_ROT_PV, theta0):
                    self.log.emit("WARNING: return-to-start rotation failed.")
                    # continue anyway — alignment can still be attempted
                self._sleep_polled(_SETTLE_S)

                # ── Step 5: iterate topx/topz until converged ─────
                target_y = (H - 1) / 2.0
                iters_used = 0
                total_dx_mm = 0.0
                total_dz_mm = 0.0
                last_dx = last_dy = None
                # Track the expected centroid across iterations — after
                # each move it stays put in image coords ideally.
                exp_x, exp_y = c_rot, target_y
                # But we start from the current position:
                seed_x, seed_y = cx0, cy0
                for k in range(1, _MAX_ITER + 1):
                    if self._abort:
                        self.failed.emit("Aborted during alignment loop.")
                        return
                    img = self._grab_averaged(_AVERAGE_N)
                    if img is None:
                        self.failed.emit(f"Iter {k}: no live frame.")
                        return
                    seg = _segment_from_seed(img, seed_x, seed_y,
                                             self.sign, nearest=True)
                    if seg is None:
                        self.failed.emit(
                            f"Iter {k}: lost the particle. Aborting; "
                            "the sample may have moved too far.")
                        return
                    cx, cy, sz = seg
                    dx_px = c_rot - cx
                    dy_px = target_y - cy
                    last_dx, last_dy = dx_px, dy_px
                    iters_used = k

                    if abs(dx_px) < _TOL_PX and abs(dy_px) < _TOL_PX:
                        self.log.emit(
                            f"Iter {k}: Δx={dx_px:+.2f} px  "
                            f"Δy={dy_px:+.2f} px  → converged.")
                        break

                    # Convert pixel offsets to motor moves.
                    dx_mm = dx_px * _MM_PX_X
                    dz_mm = dy_px * _MM_PX_Z
                    self.log.emit(
                        f"Iter {k}: Δx={dx_px:+.2f} px  Δy={dy_px:+.2f} px  "
                        f"→ topx += {dx_mm:+.5f} mm, topz += {dz_mm:+.5f} mm")

                    # Absolute move: read current RBV, add delta.
                    for pv, delta_mm in ((_TOPX_PV, dx_mm), (_TOPZ_PV, dz_mm)):
                        cur = self._caget_float(f"{pv}.RBV")
                        if cur is None:
                            self.failed.emit(f"Iter {k}: {pv}.RBV read failed.")
                            return
                        if not self._caput_wait(pv, cur + delta_mm):
                            self.failed.emit(
                                f"Iter {k}: {pv} move failed.")
                            return
                    total_dx_mm += dx_mm
                    total_dz_mm += dz_mm
                    self._sleep_polled(_SETTLE_S)
                    # Next iteration re-seeds from the target — the
                    # particle should be closer to it now.
                    seed_x, seed_y = c_rot, target_y

                self.done.emit({
                    "cor_col":          float(c_rot),
                    "final_dx_px":      float(last_dx if last_dx is not None else 0),
                    "final_dy_px":      float(last_dy if last_dy is not None else 0),
                    "iters_used":       int(iters_used),
                    "total_topx_mm":    float(total_dx_mm),
                    "total_topz_mm":    float(total_dz_mm),
                    "image_size":       (int(W), int(H)),
                })

            finally:
                # Safety: put the rotation motor back if we ever moved
                # it forward, regardless of success or abort.
                if moved_forward:
                    cur = self._caget_float(f"{_ROT_PV}.RBV")
                    if cur is not None and abs(cur - theta0) > 0.001:
                        self.log.emit(f"Safety: returning rotation to "
                                      f"{theta0:.4f}° (currently {cur:.4f}°)")
                        self._caput_wait(_ROT_PV, theta0)
        except Exception as ex:
            self.failed.emit(f"Unexpected error: {ex}")


# ── Click-catcher (event filter on pystream's viewer scene) ──────────

class _ClickCatcher(QtCore.QObject):
    """Grabs the next left-click on the pystream viewer's scene and
    reports it in IMAGE-PIXEL coords. Auto-removes itself after one
    successful click OR when disable() is called."""

    picked = pyqtSignal(float, float)   # (image_x, image_y)
    canceled = pyqtSignal()

    def __init__(self, image_view, parent=None):
        super().__init__(parent)
        self.image_view = image_view
        self._active = False

    def enable(self):
        if self._active:
            return
        self._active = True
        self.image_view.ui.graphicsView.viewport().installEventFilter(self)
        self.image_view.ui.graphicsView.viewport().setCursor(QtCore.Qt.CrossCursor)

    def disable(self, emit_cancel: bool = False):
        if not self._active:
            return
        self._active = False
        try:
            self.image_view.ui.graphicsView.viewport().removeEventFilter(self)
            self.image_view.ui.graphicsView.viewport().setCursor(QtCore.Qt.ArrowCursor)
        except Exception:
            pass
        if emit_cancel:
            self.canceled.emit()

    def eventFilter(self, _obj, event):
        if not self._active:
            return False
        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            vp_pos = event.pos()
            img_item = self.image_view.getImageItem()
            if img_item is None:
                self.disable(emit_cancel=True)
                return True
            scene_pt = self.image_view.ui.graphicsView.mapToScene(vp_pos)
            img_pt = img_item.mapFromScene(scene_pt)
            self.disable()
            self.picked.emit(float(img_pt.x()), float(img_pt.y()))
            return True
        return False


# ── Dialog ────────────────────────────────────────────────────────────

class ParticleAlignDialog(QtWidgets.QDialog):
    """Click a particle → auto-align it on the rotation axis."""

    BUTTON_TEXT  = "AlignPart"
    GROUP        = "Alignment"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("Align Particle on CoR — bl32ID")
        self.resize(520, 620)

        self._worker: Optional[_AlignWorker] = None
        self._click_catcher: Optional[_ClickCatcher] = None
        self._marker = None

        # Picked-particle state (in image-pixel coords).
        self._pick_x: Optional[float] = None
        self._pick_y: Optional[float] = None
        self._centroid_x: Optional[float] = None
        self._centroid_y: Optional[float] = None
        self._sign: int = 0

        self._build_ui()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("Align Particle on Rotation Axis")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        lay.addWidget(title)

        desc = QtWidgets.QLabel(
            "Click <b>Pick Particle</b>, then click the particle in the "
            "pystream viewer. Then click <b>Run</b> — the plugin measures "
            "the rotation axis by rotating ±180°, then iteratively moves "
            "topx/topz to bring your particle onto the axis at the "
            "vertical center of the frame."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; padding-bottom: 6px;")
        lay.addWidget(desc)

        # ── Pick particle ─────────────────────────────────────────
        pick_row = QtWidgets.QHBoxLayout()
        self.pick_btn = QtWidgets.QPushButton("Pick Particle")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setStyleSheet(
            "padding: 8px 16px; font-weight: bold;")
        self.pick_btn.toggled.connect(self._on_pick_toggled)
        pick_row.addWidget(self.pick_btn)
        self.pick_label = QtWidgets.QLabel("no particle picked")
        self.pick_label.setStyleSheet(
            "font-family: monospace; color: #ccc; padding-left: 12px;")
        pick_row.addWidget(self.pick_label, stretch=1)
        lay.addLayout(pick_row)

        # ── Run / Abort ───────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setStyleSheet(
            "background-color: #2b8; color: black; font-weight: bold; "
            "padding: 10px 20px; font-size: 12pt;")
        self.run_btn.clicked.connect(self._on_run)
        self.run_btn.setEnabled(False)
        btn_row.addWidget(self.run_btn)
        self.abort_btn = QtWidgets.QPushButton("Abort")
        self.abort_btn.setStyleSheet(
            "background-color: #d33; color: white; font-weight: bold; "
            "padding: 10px 20px;")
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self._on_abort)
        btn_row.addWidget(self.abort_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # ── Result ────────────────────────────────────────────────
        result_group = QtWidgets.QGroupBox("Result")
        rf = QtWidgets.QFormLayout()
        self.lbl_cor = QtWidgets.QLabel("—")
        self.lbl_res_dx = QtWidgets.QLabel("—")
        self.lbl_res_dy = QtWidgets.QLabel("—")
        self.lbl_iters = QtWidgets.QLabel("—")
        self.lbl_topx_moved = QtWidgets.QLabel("—")
        self.lbl_topz_moved = QtWidgets.QLabel("—")
        for lbl in (self.lbl_cor, self.lbl_res_dx, self.lbl_res_dy,
                    self.lbl_iters, self.lbl_topx_moved, self.lbl_topz_moved):
            lbl.setStyleSheet("font-family: monospace;")
        rf.addRow("CoR column (px):", self.lbl_cor)
        rf.addRow("Final Δx (px):", self.lbl_res_dx)
        rf.addRow("Final Δy (px):", self.lbl_res_dy)
        rf.addRow("Iterations used:", self.lbl_iters)
        rf.addRow("topx moved (mm):", self.lbl_topx_moved)
        rf.addRow("topz moved (mm):", self.lbl_topz_moved)
        result_group.setLayout(rf)
        lay.addWidget(result_group)

        # ── Log ───────────────────────────────────────────────────
        log_group = QtWidgets.QGroupBox("Log")
        lv = QtWidgets.QVBoxLayout()
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 9pt;")
        lv.addWidget(self.log_text)
        log_group.setLayout(lv)
        lay.addWidget(log_group)

    # ── Frame source (pystream live viewer) ───────────────────────
    def _parent_image_view(self):
        p = self.parent()
        if p is None or not hasattr(p, 'image_view'):
            return None
        return p.image_view

    def _grab_current_frame(self) -> Optional[np.ndarray]:
        iv = self._parent_image_view()
        if iv is None:
            return None
        try:
            item = iv.getImageItem()
        except Exception:
            return None
        if item is None or item.image is None:
            return None
        return item.image

    # ── Pick-particle handling ────────────────────────────────────
    def _on_pick_toggled(self, checked: bool):
        iv = self._parent_image_view()
        if iv is None:
            self.pick_btn.setChecked(False)
            self._log("No pystream viewer available.")
            return

        if checked:
            self._click_catcher = _ClickCatcher(iv, parent=self)
            self._click_catcher.picked.connect(self._on_picked)
            self._click_catcher.canceled.connect(self._on_pick_canceled)
            self._click_catcher.enable()
            self._log("Click on the particle in the pystream viewer …")
        else:
            if self._click_catcher is not None:
                self._click_catcher.disable(emit_cancel=True)

    def _on_pick_canceled(self):
        self._log("Pick canceled.")

    def _on_picked(self, x: float, y: float):
        self.pick_btn.setChecked(False)
        self._click_catcher = None

        img = self._grab_current_frame()
        if img is None:
            self._log("No live frame yet — start pystream streaming first.")
            return
        H, W = img.shape[:2]
        # Guard: click outside the image.
        if not (0 <= x < W and 0 <= y < H):
            self._log(f"Click at ({x:.1f}, {y:.1f}) is outside the "
                      f"image (W={W}, H={H}).")
            return

        # Infer contrast sign — bright blob if click is above local median.
        cx_i, cy_i = int(x), int(y)
        r = _WIN_PX // 2
        window = img[max(0, cy_i - r):cy_i + r,
                     max(0, cx_i - r):cx_i + r]
        med = float(np.median(window)) if window.size else float(np.median(img))
        pix = float(img[cy_i, cx_i])
        self._sign = 1 if pix >= med else -1
        sign_txt = "bright" if self._sign > 0 else "dark"

        if not _HAS_SCIPY:
            self._log("scipy missing — cannot segment. `pip install scipy`.")
            return

        seg = _segment_from_seed(img, x, y, self._sign, nearest=False)
        if seg is None:
            self._log(f"Segmentation failed at click ({x:.1f}, {y:.1f}) "
                      f"[{sign_txt}]. Try a different spot.")
            return

        cx, cy, sz = seg
        self._pick_x, self._pick_y = x, y
        self._centroid_x, self._centroid_y = cx, cy

        self.pick_label.setText(
            f"pick=({x:.1f}, {y:.1f})  centroid=({cx:.1f}, {cy:.1f})  "
            f"[{sign_txt}, {sz} px]")
        self._log(f"Picked {sign_txt} blob: pick=({x:.1f}, {y:.1f})  "
                  f"centroid=({cx:.1f}, {cy:.1f})  [{sz} px]")

        self._place_marker(cx, cy)
        self.run_btn.setEnabled(True)

    def _place_marker(self, x: float, y: float):
        """Drop a small crosshair on the image at (x, y). Parented to
        the ImageItem so it pans/zooms with the image."""
        self._remove_marker()
        iv = self._parent_image_view()
        if iv is None:
            return
        img_item = iv.getImageItem()
        if img_item is None:
            return
        s = 8.0
        pen = QtCore.Qt.magenta
        from PyQt5 import QtGui  # local import
        pen_obj = QtGui.QPen(QtGui.QColor("magenta"))
        pen_obj.setWidth(2)
        pen_obj.setCosmetic(True)
        marker = QtWidgets.QGraphicsItemGroup()
        h_line = QtWidgets.QGraphicsLineItem(x - s, y, x + s, y)
        v_line = QtWidgets.QGraphicsLineItem(x, y - s, x, y + s)
        for ln in (h_line, v_line):
            ln.setPen(pen_obj)
            marker.addToGroup(ln)
        marker.setZValue(1500)
        marker.setParentItem(img_item)
        marker.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self._marker = marker

    def _remove_marker(self):
        if self._marker is None:
            return
        try:
            self._marker.setParentItem(None)
            sc = self._marker.scene()
            if sc is not None:
                sc.removeItem(self._marker)
        except Exception:
            pass
        self._marker = None

    # ── Run / Abort ───────────────────────────────────────────────
    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._pick_x is None:
            self._log("Pick a particle first.")
            return
        if self._grab_current_frame() is None:
            self._log("No live frame — start pystream streaming first.")
            return

        self._clear_result()
        self._log(f"── Run: align particle at ({self._centroid_x:.1f}, "
                  f"{self._centroid_y:.1f}) onto CoR ──")

        self._worker = _AlignWorker(
            click_x=self._pick_x,
            click_y=self._pick_y,
            sign=self._sign,
            grab_fn=self._grab_current_frame,
        )
        self._worker.log.connect(self._log)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self.run_btn.setEnabled(False)
        self.pick_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._worker.start()

    def _on_abort(self):
        if self._worker is not None and self._worker.isRunning():
            self._log("Abort requested …")
            self._worker.request_abort()

    def _on_done(self, r: dict):
        self.lbl_cor.setText(f"{r['cor_col']:.2f}")
        self.lbl_res_dx.setText(f"{r['final_dx_px']:+.2f}")
        self.lbl_res_dy.setText(f"{r['final_dy_px']:+.2f}")
        self.lbl_iters.setText(str(r['iters_used']))
        self.lbl_topx_moved.setText(f"{r['total_topx_mm']:+.5f}")
        self.lbl_topz_moved.setText(f"{r['total_topz_mm']:+.5f}")
        self._log(f"Done in {r['iters_used']} iteration(s). "
                  f"CoR={r['cor_col']:.2f} px, "
                  f"final Δ=({r['final_dx_px']:+.2f}, {r['final_dy_px']:+.2f}) px.")

    def _on_failed(self, msg: str):
        self._log(f"FAILED: {msg}")

    def _on_worker_finished(self):
        self.run_btn.setEnabled(self._pick_x is not None)
        self.pick_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        self._worker = None

    # ── Helpers ───────────────────────────────────────────────────
    def _clear_result(self):
        for lbl in (self.lbl_cor, self.lbl_res_dx, self.lbl_res_dy,
                    self.lbl_iters, self.lbl_topx_moved, self.lbl_topz_moved):
            lbl.setText("—")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")

    def closeEvent(self, event):
        if self._click_catcher is not None:
            self._click_catcher.disable(emit_cancel=False)
        self._remove_marker()
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_abort()
            self._worker.wait(3000)
        super().closeEvent(event)
