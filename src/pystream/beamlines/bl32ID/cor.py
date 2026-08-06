"""
Center-of-Rotation Plugin for bl32ID

Textbook 0°/180° cross-correlation to find the horizontal rotation-axis
position for a tomo scan. Workflow:

  1. Read current rotation angle θ₀.
  2. Grab (and average) N live frames from the pystream viewer.
  3. caput the rotation motor to θ₀ + Δ (default Δ = 180°). `caput -c`
     blocks until the motor is done.
  4. Wait `settle_s`, grab and average N more frames.
  5. Optional: caput back to θ₀ (default ON).
  6. Mirror the 180° image horizontally, cross-correlate the two
     images' horizontal projections, sub-pixel-refine the peak.
  7. Report CoR pixel position and offset-from-image-center.

The frame source is pystream's live viewer — we do NOT open a separate
PVA subscription. Start the stream in pystream before running.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Optional

import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import pyqtSignal


# Hardcoded defaults — this plugin is Run-and-go. Edit these constants
# if the beamline's rotation motor or timing changes.
_ROT_PV          = "32idbTXM:ens:c1:m1"   # 32-ID TXM rotation motor
_DELTA_DEG       = 180.0                  # angular separation between the two grabs
_SETTLE_S        = 1.0                    # sample settle after the motor move
_AVERAGE_N       = 3                      # frames averaged per angle to kill noise
_RETURN_TO_START = True                   # motor goes back to θ₀ when done

# Permissive tomo soft-limit range on the composed target angle.
_SOFT_MIN_DEG = -180.0
_SOFT_MAX_DEG = 540.0


# ── Worker ──────────────────────────────────────────────────────────────

class _CoRWorker(QtCore.QThread):
    """Runs the CoR sequence off the GUI thread. All motor moves and
    frame grabs happen here; the dialog just listens to signals."""

    log = pyqtSignal(str)
    done = pyqtSignal(dict)   # {shift_px, cor_px, cor_offset_px, confidence, width}
    failed = pyqtSignal(str)

    def __init__(self, rot_pv: str, delta_deg: float,
                 settle_s: float, average_n: int, return_to_start: bool,
                 grab_fn):
        """`grab_fn` is a zero-arg callable returning the current live
        frame as an ndarray (or None if none available). Injected so the
        worker doesn't reach into Qt widgets from a non-GUI thread."""
        super().__init__()
        self.rot_pv = rot_pv
        self.delta_deg = delta_deg
        self.settle_s = settle_s
        self.average_n = max(1, int(average_n))
        self.return_to_start = return_to_start
        self._grab_fn = grab_fn
        self._abort = False

    def request_abort(self):
        self._abort = True

    # ── caput / caget shell wrappers (same idiom as autocenter/qgmax) ──
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
        """Grab `n` distinct live frames and average them. Distinctness
        is best-effort: we sleep a small fraction between grabs so
        pystream has a chance to publish a new frame."""
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
            # Deduplicate: if the pixel data is the same object as the
            # previous grab, wait for the next frame.
            if prev is not None and img is prev:
                time.sleep(0.05)
                continue
            frames.append(img.astype(np.float64, copy=True))
            prev = img
            time.sleep(0.05)
        if not frames:
            return None
        return np.mean(np.stack(frames, axis=0), axis=0)

    # ── Main sequence ─────────────────────────────────────────────────
    def run(self):
        try:
            theta0 = self._caget_float(f"{self.rot_pv}.RBV")
            if theta0 is None:
                self.failed.emit(f"Could not read {self.rot_pv}.RBV — check PV.")
                return
            self.log.emit(f"Start angle θ₀ = {theta0:.4f}°")

            theta_end = theta0 + self.delta_deg
            if not (_SOFT_MIN_DEG <= theta_end <= _SOFT_MAX_DEG):
                self.failed.emit(
                    f"Target angle {theta_end:.3f}° outside soft range "
                    f"[{_SOFT_MIN_DEG}, {_SOFT_MAX_DEG}] — refusing to move.")
                return

            # Grab @ start
            self.log.emit(f"Grabbing {self.average_n} frame(s) @ θ = {theta0:.4f}°")
            img0 = self._grab_averaged(self.average_n)
            if img0 is None:
                self.failed.emit("No live frame available — start pystream streaming first.")
                return
            if self._abort:
                self.failed.emit("Aborted before move.")
                return

            # Move to θ + Δ
            self.log.emit(f"Moving rotation motor to {theta_end:.4f}° …")
            moved_forward = False
            try:
                if not self._caput_wait(self.rot_pv, theta_end):
                    self.failed.emit("Motor move to +Δ failed.")
                    return
                moved_forward = True

                self.log.emit(f"Settling {self.settle_s:g} s")
                # Poll `_abort` during settle so Abort feels responsive.
                t_end = time.time() + self.settle_s
                while time.time() < t_end:
                    if self._abort:
                        break
                    time.sleep(0.05)
                if self._abort:
                    self.failed.emit("Aborted during settle.")
                    return

                self.log.emit(f"Grabbing {self.average_n} frame(s) @ θ = {theta_end:.4f}°")
                img180 = self._grab_averaged(self.average_n)
                if img180 is None:
                    self.failed.emit("No live frame after move — is the detector still streaming?")
                    return

                # Compute CoR
                result = _compute_cor(img0, img180)
                self.log.emit(
                    f"Shift = {result['shift_px']:+.3f} px   "
                    f"CoR = {result['cor_px']:.3f} px   "
                    f"(offset {result['cor_offset_px']:+.3f} from center)   "
                    f"conf {result['confidence']:.2f}"
                )
                self.done.emit(result)

            finally:
                # Motor safety: always try to return-to-start if the user
                # asked for it, even on abort or algorithm failure.
                if self.return_to_start and moved_forward:
                    self.log.emit(f"Returning motor to {theta0:.4f}°")
                    ok = self._caput_wait(self.rot_pv, theta0)
                    if not ok:
                        self.log.emit(
                            "WARNING: Return-to-start caput failed. "
                            "Check the motor position manually.")
        except Exception as ex:
            self.failed.emit(f"Unexpected error: {ex}")


# ── Algorithm ───────────────────────────────────────────────────────────

def _compute_cor(img0: np.ndarray, img180: np.ndarray) -> dict:
    """Cross-correlate img0 with the horizontally-mirrored img180 and
    return CoR / shift / offset / confidence. Both images must have the
    same shape."""
    if img0.shape != img180.shape:
        raise ValueError(
            f"Shape mismatch: {img0.shape} vs {img180.shape}. Detector "
            "geometry must not change between the two grabs.")
    H, W = img0.shape[:2]
    flipped = img180[:, ::-1]

    # Collapse to 1D horizontal profiles (sum along rows).
    p0 = np.asarray(img0, dtype=np.float64).sum(axis=0)
    p1 = np.asarray(flipped, dtype=np.float64).sum(axis=0)
    p0 = (p0 - p0.mean()) / (p0.std() + 1e-8)
    p1 = (p1 - p1.mean()) / (p1.std() + 1e-8)

    corr = np.correlate(p0, p1, mode='full')
    peak_idx = int(np.argmax(corr))

    # Parabolic sub-pixel refinement — same idiom as
    # rotationaxis.py:_compute_shift.
    shift_refined = float(peak_idx - (W - 1))
    if 0 < peak_idx < len(corr) - 1:
        y1, y2, y3 = corr[peak_idx - 1], corr[peak_idx], corr[peak_idx + 1]
        denom = 2.0 * (y1 - 2.0 * y2 + y3)
        if abs(denom) > 1e-10:
            shift_refined += (y1 - y3) / denom

    # CoR in pixel coordinates. Derivation is in the plan file:
    # after horizontal mirror, shift = (W-1) - 2·c ⇒ c = ((W-1) - shift)/2.
    cor_px = ((W - 1) - shift_refined) / 2.0
    cor_offset_px = cor_px - (W - 1) / 2.0

    # Confidence: peak height vs the 98th-percentile of the correlation
    # (a sharp peak against a low-noise floor scores high).
    sorted_corr = np.sort(corr)
    ref = sorted_corr[max(0, len(sorted_corr) - max(1, int(0.02 * len(sorted_corr))))]
    confidence = float(corr[peak_idx] / (abs(ref) + 1e-8))

    return {
        "shift_px":       float(shift_refined),
        "cor_px":         float(cor_px),
        "cor_offset_px":  float(cor_offset_px),
        "confidence":     confidence,
        "width":          int(W),
        "height":         int(H),
    }


# ── Dialog ──────────────────────────────────────────────────────────────

class CenterOfRotationDialog(QtWidgets.QDialog):
    """0°/180° cross-correlation CoR finder."""

    BUTTON_TEXT  = "CoR"
    GROUP        = "Alignment"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("Center of Rotation — bl32ID")
        self.resize(480, 460)

        self._worker: Optional[_CoRWorker] = None

        self._build_ui()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("Center of Rotation")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        lay.addWidget(title)

        desc = QtWidgets.QLabel(
            f"Grabs a frame, rotates by {_DELTA_DEG:g}°, grabs another, "
            f"and cross-correlates to find the rotation axis. Motor "
            f"returns to the starting angle when done. "
            f"Start the pystream stream first so live frames are flowing."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; padding-bottom: 6px;")
        lay.addWidget(desc)

        # ── Run / Abort ───────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setStyleSheet(
            "background-color: #2b8; color: black; font-weight: bold; "
            "padding: 10px 20px; font-size: 12pt;")
        self.run_btn.clicked.connect(self._on_run)
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
        self.lbl_shift = QtWidgets.QLabel("—")
        self.lbl_cor = QtWidgets.QLabel("—")
        self.lbl_offset = QtWidgets.QLabel("—")
        self.lbl_conf = QtWidgets.QLabel("—")
        self.lbl_size = QtWidgets.QLabel("—")
        for lbl in (self.lbl_shift, self.lbl_cor, self.lbl_offset,
                    self.lbl_conf, self.lbl_size):
            lbl.setStyleSheet("font-family: monospace;")
        rf.addRow("Shift (px):", self.lbl_shift)
        rf.addRow("CoR (px from left):", self.lbl_cor)
        rf.addRow("CoR offset (from center):", self.lbl_offset)
        rf.addRow("Confidence:", self.lbl_conf)
        rf.addRow("Image size (W×H):", self.lbl_size)
        result_group.setLayout(rf)
        lay.addWidget(result_group)

        # ── Log ───────────────────────────────────────────────────
        log_group = QtWidgets.QGroupBox("Log")
        lv = QtWidgets.QVBoxLayout()
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 9pt;")
        lv.addWidget(self.log_text)
        log_group.setLayout(lv)
        lay.addWidget(log_group)

    # ── Frame source (pystream live viewer) ───────────────────────────
    def _grab_current_frame(self) -> Optional[np.ndarray]:
        """Reach into the parent pystream viewer's ImageItem and pull
        the currently-displayed frame. Same idiom as autocenter.py."""
        p = self.parent()
        if p is None or not hasattr(p, 'image_view'):
            return None
        try:
            item = p.image_view.getImageItem()
        except Exception:
            return None
        if item is None or item.image is None:
            return None
        return item.image

    # ── Run / Abort ──────────────────────────────────────────────────
    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            return

        # Preflight: verify a live frame is available. If not, refuse
        # to run so we don't leave the motor at +180 with nothing to
        # correlate.
        if self._grab_current_frame() is None:
            self._log("No live frame yet — start the pystream stream first.")
            return

        self._clear_result()
        self._log(f"── Run: rotate by {_DELTA_DEG:g}° and correlate ──")

        self._worker = _CoRWorker(
            rot_pv=_ROT_PV,
            delta_deg=_DELTA_DEG,
            settle_s=_SETTLE_S,
            average_n=_AVERAGE_N,
            return_to_start=_RETURN_TO_START,
            grab_fn=self._grab_current_frame,
        )
        self._worker.log.connect(self._log)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self.run_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self._worker.start()

    def _on_abort(self):
        if self._worker is not None and self._worker.isRunning():
            self._log("Abort requested …")
            self._worker.request_abort()

    def _on_done(self, result: dict):
        self.lbl_shift.setText(f"{result['shift_px']:+.3f}")
        self.lbl_cor.setText(f"{result['cor_px']:.3f}")
        self.lbl_offset.setText(f"{result['cor_offset_px']:+.3f}")
        self.lbl_conf.setText(f"{result['confidence']:.2f}")
        self.lbl_size.setText(f"{result['width']} × {result['height']}")

    def _on_failed(self, msg: str):
        self._log(f"FAILED: {msg}")

    def _on_worker_finished(self):
        self.run_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        self._worker = None

    # ── Helpers ───────────────────────────────────────────────────────
    def _clear_result(self):
        for lbl in (self.lbl_shift, self.lbl_cor, self.lbl_offset,
                    self.lbl_conf, self.lbl_size):
            lbl.setText("—")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_abort()
            self._worker.wait(3000)
        super().closeEvent(event)
