#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Real-time NTNDArray Viewer for EPICS PVA
----------------------------------------

- Subscribes to a PVA NTNDArray PV and displays 2D images in real time.
- ImageJ-like tools: zoom, pan (via Matplotlib toolbar), contrast sliders, autoscale, histogram, flips.
- Falls back to an internal NTNDArray reshaper if AdImageUtility is not present.

Usage:
    python pv_ntnda_viewer.py --pv 32idbSP1:Pva1:Image
    python pv_ntnda_viewer.py --pv SIM:IMG --hist  # enable live histogram

Options:
    --pv PVNAME               PVAccess NTNDArray PV name (required)
    --max-fps 30              Throttle UI refresh to this FPS (default 30)
    --hist                    Show live histogram panel (off by default)
    --no-toolbar              Hide the Matplotlib toolbar (zoom/pan)
"""

import argparse
import queue
import threading
import time
import sys
import math
from typing import Optional, Tuple

import numpy as np
import pvaccess as pva

# Tk / MPL
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


# -----------------------------------------------------------------------------
# NTNDArray reshaping utilities
# -----------------------------------------------------------------------------
def _has_ad_image_utility():
    try:
        from AdImageUtility import AdImageUtility as _A  # pragma: no cover
        return True
    except Exception:
        return False

_ADU_AVAILABLE = _has_ad_image_utility()

if _ADU_AVAILABLE:
    from AdImageUtility import AdImageUtility  # use your provided class

def reshape_ntnda(ntnda) -> Tuple[int, np.ndarray, int, int, Optional[int], int, str]:
    """
    Return: (imageId, image, nx, ny, nz, colorMode, fieldKey)
    Uses your AdImageUtility if present, otherwise minimal fallback for MONO/RGB*.
    """
    if _ADU_AVAILABLE:
        return AdImageUtility.reshapeNtNdArray(ntnda)

    # -------- Fallback reshaper (minimal but robust) --------
    image_id = ntnda['uniqueId']
    dims = ntnda['dimension']
    nDims = len(dims)

    # Color mode from attribute if present, else MONO
    color_mode = 0  # MONO
    if 'attribute' in ntnda:
        for a in ntnda['attribute']:
            if a.get('name') == 'ColorMode':
                try:
                    color_mode = a['value'][0]['value']
                except Exception:
                    pass
                break

    # union field key and raw 1-D buffer
    try:
        field_key = ntnda.getSelectedUnionFieldName()
        raw = ntnda['value'][0][field_key]
    except Exception:
        # safer fallback
        field_key = next(iter(ntnda['value'][0].keys()))
        raw = ntnda['value'][0][field_key]

    # sizes
    if nDims == 0:
        return (image_id, None, None, None, None, color_mode, field_key)

    if nDims == 2 and color_mode == 0:  # MONO
        nx = dims[0]['size']
        ny = dims[1]['size']
        img = np.asarray(raw).reshape(ny, nx)
        return (image_id, img, nx, ny, None, color_mode, field_key)

    # 3-D + color
    if nDims == 3:
        d0, d1, d2 = dims[0]['size'], dims[1]['size'], dims[2]['size']
        arr = np.asarray(raw)
        # Try common layouts; prefer MONO if misdeclared but nDims==3 with nz==1
        if color_mode == 2:  # RGB1: [3, NX, NY]
            nz, nx, ny = d0, d1, d2
            img = arr.reshape(nz, nx, ny).transpose(2, 1, 0)  # -> (ny, nx, nz)
        elif color_mode == 3:  # RGB2: [NX, 3, NY]
            nx, nz, ny = d0, d1, d2
            img = arr.reshape(nx, nz, ny).transpose(2, 0, 1)  # -> (ny, nx, nz)
        elif color_mode == 4:  # RGB3: [NX, NY, 3]
            nx, ny, nz = d0, d1, d2
            img = arr.reshape(nx, ny, nz).transpose(1, 0, 2)  # -> (ny, nx, nz)
        else:
            # If nz==1 treat as mono
            if 1 in (d0, d1, d2):
                # pick the two >1 dims for (ny, nx)
                dims_sorted = sorted([d0, d1, d2], reverse=True)
                ny, nx = dims_sorted[:2]
                img = arr.reshape(ny, nx)
                color_mode = 0
            else:
                raise pva.InvalidArgument(
                    f'Unsupported dims/colorMode combination: dims={dims}, colorMode={color_mode}'
                )
        return (image_id, img, img.shape[1], img.shape[0], img.shape[2] if img.ndim == 3 else None,
                color_mode, field_key)

    raise pva.InvalidArgument(f'Invalid NTNDArray dims: {dims}')


# -----------------------------------------------------------------------------
# PVA Subscriber (threaded) -> Tk queue
# -----------------------------------------------------------------------------
class NtndaSubscriber:
    def __init__(self, pv_name: str, out_queue: queue.Queue):
        self.pv_name = pv_name
        self.out_q = out_queue
        self.chan = pva.Channel(pv_name)
        self.subscribed = False
        self._lock = threading.Lock()

    def _callback(self, pv: pva.PvObject):
        try:
            uid, img, nx, ny, nz, cm, key = reshape_ntnda(pv)
            if img is None:
                return
            # Ensure 2-D grayscale shown (if RGB, convert quick luminance)
            if img.ndim == 3 and img.shape[2] in (3, 4):
                # simple luminance (no gamma); fast path
                img = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]).astype(img.dtype)
            self.out_q.put((time.time(), uid, img))
        except Exception as exc:
            # Avoid flooding stderr; enqueue error if needed
            sys.stderr.write(f"[NtndaSubscriber] callback error: {exc}\n")

    def start(self):
        with self._lock:
            if self.subscribed:
                return
            self.chan.subscribe("viewer", self._callback)
            self.chan.startMonitor()
            self.subscribed = True

    def stop(self):
        with self._lock:
            if not self.subscribed:
                return
            try:
                self.chan.stopMonitor()
            except Exception:
                pass
            try:
                self.chan.unsubscribe("viewer")
            except Exception:
                pass
            self.subscribed = False


# -----------------------------------------------------------------------------
# Tk Viewer
# -----------------------------------------------------------------------------
class PvViewerApp:
    def __init__(self, root, pv_name: str, max_fps: int = 30, show_hist: bool = False, show_toolbar: bool = True):
        self.root = root
        self.root.title(f"NTNDArray Viewer - {pv_name}")
        self.root.geometry("1200x800")

        self.max_fps = max(1, int(max_fps))
        self.frame_interval = 1.0 / self.max_fps
        self.show_hist = show_hist
        self.show_toolbar = show_toolbar

        self.queue = queue.Queue(maxsize=10)
        self.sub = NtndaSubscriber(pv_name, self.queue)
        self.last_draw = 0.0
        self.paused = False

        # view state
        self.vmin = None
        self.vmax = None
        self.autoscale = tk.BooleanVar(value=True)
        self.flip_h = tk.BooleanVar(value=False)
        self.flip_v = tk.BooleanVar(value=False)
        self.transpose = tk.BooleanVar(value=False)
        self.current_uid = -1
        self.fps_ema = None

        # layout
        self._build_ui()

        # start subscription and UI pump
        self.sub.start()
        self._pump_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI construction ----------------
    def _build_ui(self):
        # Top frame: controls
        top = ttk.Frame(self.root)
        top.pack(side="top", fill="x", padx=8, pady=6)

        # Pause/Resume
        self.btn_pause = ttk.Button(top, text="Pause", command=self._toggle_pause)
        self.btn_pause.pack(side="left")

        # Autoscale
        ttk.Checkbutton(top, text="Autoscale", variable=self.autoscale, command=self._apply_contrast)\
            .pack(side="left", padx=(10, 0))

        # Flip/Transpose
        ttk.Checkbutton(top, text="Flip H", variable=self.flip_h, command=self._redraw)\
            .pack(side="left", padx=(10, 0))
        ttk.Checkbutton(top, text="Flip V", variable=self.flip_v, command=self._redraw)\
            .pack(side="left", padx=(6, 0))
        ttk.Checkbutton(top, text="Transpose", variable=self.transpose, command=self._redraw)\
            .pack(side="left", padx=(6, 0))

        # Save button
        ttk.Button(top, text="Save Frame…", command=self._save_frame)\
            .pack(side="left", padx=(12, 0))

        # Status labels
        self.lbl_uid = ttk.Label(top, text="UID: —")
        self.lbl_uid.pack(side="right")
        self.lbl_fps = ttk.Label(top, text="FPS: —")
        self.lbl_fps.pack(side="right", padx=(0, 14))

        # Main area: left controls (contrast) + right canvas (image)
        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

        # Left panel: contrast / histogram
        left = ttk.Frame(main, width=280)
        left.pack_propagate(False)
        main.add(left, weight=0)

        # Contrast frame
        cf = ttk.Labelframe(left, text="Contrast")
        cf.pack(side="top", fill="x", padx=6, pady=6)

        self.sld_min = tk.Scale(cf, from_=0, to=65535, orient="horizontal",
                                label="Min (vmin)", command=lambda e: self._slider_changed())
        self.sld_max = tk.Scale(cf, from_=0, to=65535, orient="horizontal",
                                label="Max (vmax)", command=lambda e: self._slider_changed())
        self.sld_min.pack(fill="x", padx=6, pady=(4, 4))
        self.sld_max.pack(fill="x", padx=6, pady=(0, 6))

        # Histogram frame (optional)
        self.hist_fig = None
        self.hist_ax = None
        self.hist_canvas = None
        if self.show_hist:
            hf = ttk.Labelframe(left, text="Histogram")
            hf.pack(side="top", fill="both", expand=True, padx=6, pady=6)
            self.hist_fig = Figure(figsize=(3, 2), dpi=100)
            self.hist_ax = self.hist_fig.add_subplot(111)
            self.hist_canvas = FigureCanvasTkAgg(self.hist_fig, master=hf)
            self.hist_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Right panel: image canvas
        right = ttk.Frame(main)
        main.add(right, weight=1)

        self.fig = Figure(figsize=(6, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_axis_off()
        self.im = None

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side="top", fill="both", expand=True)

        if self.show_toolbar:
            toolbar = NavigationToolbar2Tk(self.canvas, right)
            toolbar.update()

    # --------------- Queue/UI pump -------------------
    def _pump_queue(self):
        """Pull frames from subscriber queue and refresh at max_fps."""
        now = time.time()
        while not self.queue.empty():
            ts, uid, img = self.queue.get_nowait()
            if self.paused:
                continue
            # throttle to ~max_fps
            if now - self.last_draw < self.frame_interval:
                # keep most recent only
                while not self.queue.empty():
                    try:
                        _ = self.queue.get_nowait()
                    except Exception:
                        break
                break
            self._update_image(uid, img, ts)
            self.last_draw = now
            break  # only draw once per pump

        self.root.after(5, self._pump_queue)  # pump frequently (5 ms)

    # --------------- Image update/draw ---------------
    def _update_image(self, uid: int, img: np.ndarray, ts: float):
        # View transforms
        if self.transpose.get():
            img = img.T
        if self.flip_h.get():
            img = np.flip(img, axis=1)
        if self.flip_v.get():
            img = np.flip(img, axis=0)

        self.current_uid = uid

        # Determine dtype range for sliders (first time or dtype change)
        self._ensure_slider_range(img)

        # Contrast
        if self.autoscale.get() or self.vmin is None or self.vmax is None:
            vmin, vmax = self._autoscale_values(img)
            self._set_sliders(vmin, vmax, from_img=True)
        else:
            vmin, vmax = self.vmin, self.vmax

        # --- Force grayscale display ---
        if img.ndim == 3 and img.shape[2] in (3, 4):
        # Convert RGB to luminance (Y)
            img = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])

        if self.im is None:
            self.im = self.ax.imshow(img, origin='upper', vmin=vmin, vmax=vmax,
                             aspect='equal', cmap='gray')
        else:
            self.im.set_data(img)
            self.im.set_clim(vmin=vmin, vmax=vmax)

        self.ax.set_axis_off()
        self.canvas.draw_idle()

        # Histogram (optional)
        if self.hist_ax is not None:
            self._draw_hist(img, vmin, vmax)

        # Status: FPS EMA
        now = time.time()
        if self.fps_ema is None:
            self.fps_ema = 0.0
        else:
            dt = max(1e-6, now - getattr(self, "_last_ts", now - 1.0/self.max_fps))
            inst_fps = 1.0 / dt
            self.fps_ema = 0.8 * self.fps_ema + 0.2 * inst_fps
        self._last_ts = now

        self.lbl_uid.config(text=f"UID: {uid}")
        self.lbl_fps.config(text=f"FPS: {self.fps_ema:4.1f}")

    def _draw_hist(self, img, vmin, vmax):
        self.hist_ax.clear()
        # downsample heavy images for speed
        arr = img
        if arr.size > 4_000_000:
            # simple stride-based downsample
            sy = max(1, arr.shape[0] // 1000)
            sx = max(1, arr.shape[1] // 1000)
            arr = arr[::sy, ::sx]
        self.hist_ax.hist(arr.ravel(), bins=256)
        self.hist_ax.set_title("Histogram")
        self.hist_ax.axvline(vmin, linestyle="--")
        self.hist_ax.axvline(vmax, linestyle="--")
        self.hist_canvas.draw_idle()

    # --------------- Contrast helpers ----------------
    def _ensure_slider_range(self, img: np.ndarray):
        # Determine reasonable slider range based on dtype
        dtype = img.dtype
        if np.issubdtype(dtype, np.integer):
            info = np.iinfo(dtype)
            lo, hi = int(info.min), int(info.max)
        elif np.issubdtype(dtype, np.floating):
            # For float images, derive range from data (robust percentiles)
            lo = float(np.nanpercentile(img, 0.1))
            hi = float(np.nanpercentile(img, 99.9))
        else:
            lo, hi = float(np.nanmin(img)), float(np.nanmax(img))

        # Update slider bounds only if they changed significantly
        current_to = self.sld_min.cget("to")
        if int(current_to) != int(hi):
            self.sld_min.config(from_=lo, to=hi, resolution=max(1, (hi - lo) // 1024) if np.issubdtype(img.dtype, np.integer) else (hi - lo) / 1024.0)
            self.sld_max.config(from_=lo, to=hi, resolution=max(1, (hi - lo) // 1024) if np.issubdtype(img.dtype, np.integer) else (hi - lo) / 1024.0)

    def _autoscale_values(self, img: np.ndarray):
        # robust autocontrast: 0.5%–99.5% percentiles
        lo = float(np.nanpercentile(img, 0.5))
        hi = float(np.nanpercentile(img, 99.5))
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            lo, hi = float(np.nanmin(img)), float(np.nanmax(img))
        return lo, hi

    def _set_sliders(self, vmin, vmax, from_img=False):
        # Avoid recursive slider triggers
        self._updating_sliders = True
        try:
            self.sld_min.set(vmin)
            self.sld_max.set(vmax)
        finally:
            self._updating_sliders = False
        if not from_img:
            self.vmin, self.vmax = float(vmin), float(vmax)

    def _slider_changed(self):
        if getattr(self, "_updating_sliders", False):
            return
        self.autoscale.set(False)
        vmin = float(self.sld_min.get())
        vmax = float(self.sld_max.get())
        if vmax <= vmin:
            vmax = vmin + 1e-6
        self.vmin, self.vmax = vmin, vmax
        self._apply_contrast()

    def _apply_contrast(self):
        if self.im is None:
            return
        if self.autoscale.get():
            # force recompute next redraw
            self.vmin, self.vmax = None, None
        else:
            if self.vmin is not None and self.vmax is not None:
                self.im.set_clim(vmin=self.vmin, vmax=self.vmax)
                self.canvas.draw_idle()

    # ----------------- Commands ----------------------
    def _toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text=("Resume" if self.paused else "Pause"))

    def _redraw(self):
        # force redraw using the last received frame if present
        try:
            # Peek at last image by looking at current clim and array on artist
            arr = self.im.get_array()
            self._update_image(self.current_uid, np.array(arr), time.time())
        except Exception:
            pass

    def _save_frame(self):
        if self.im is None:
            messagebox.showinfo("Save Frame", "No image to save yet.")
            return
        arr = np.array(self.im.get_array())
        path = filedialog.asksaveasfilename(
            defaultextension=".npy",
            filetypes=[("NumPy array", "*.npy"), ("PNG image", "*.png"), ("All files", "*.*")]
        )
        if not path:
            return
        if path.lower().endswith(".png"):
            # Save via matplotlib with current contrast
            self.fig.savefig(path, dpi=150, bbox_inches="tight")
        else:
            np.save(path, arr)

    # ----------------- Shutdown ----------------------
    def _on_close(self):
        try:
            self.sub.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Real-time NTNDArray Viewer for EPICS PVA")
    ap.add_argument("--pv", required=True, help="PVAccess NTNDArray PV name")
    ap.add_argument("--max-fps", type=int, default=30, help="Max redraw FPS (UI throttle)")
    ap.add_argument("--hist", action="store_true", help="Show live histogram panel")
    ap.add_argument("--no-toolbar", action="store_true", help="Hide Matplotlib zoom/pan toolbar")
    args = ap.parse_args()

    root = tk.Tk()
    # ttk theme for cleaner look
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    app = PvViewerApp(root,
                      pv_name=args.pv,
                      max_fps=args.max_fps,
                      show_hist=args.hist,
                      show_toolbar=not args.no_toolbar)
    root.mainloop()


if __name__ == "__main__":
    main()
