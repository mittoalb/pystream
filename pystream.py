#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NTNDArray Real-time Viewer (Dark UI + Grayscale + Flat-field)
-------------------------------------------------------------

Usage:
    python pv_ntnda_viewer.py --pv 32idbSP1:Pva1:Image

Options:
    --pv <name>         NTNDArray PV (required)
    --max-fps 30        UI redraw throttle (0 = unthrottled)
    --no-toolbar        Hide Matplotlib toolbar

Features:
  - Black/dark UI (Tk + Matplotlib)  ✅
  - Grayscale enforced (RGB -> luminance) + cmap='gray'
  - Histogram (default ON), autoscale or manual Min/Max
  - Zoom/Pan, Flip H/V, Transpose
  - Flat-field normalization: Capture/Load/Save/Clear + Apply Flat toggle
  - Pause/Resume, Save frame (.png/.npy), FPS/UID readout
"""

import argparse
import sys
import math
import time
import queue
import threading
from typing import Optional, Tuple

import numpy as np
import pvaccess as pva

# Tk / MPL
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

# Try to use user's AdImageUtility if available, else fallback reshaper
try:
    from AdImageUtility import AdImageUtility as _ADU  # noqa: F401
    _HAS_ADU = True
except Exception:
    _HAS_ADU = False


# -----------------------------------------------------------------------------
# NTNDArray reshaping (uses AdImageUtility if available, else robust fallback)
# -----------------------------------------------------------------------------
def reshape_ntnda(ntnda) -> Tuple[int, np.ndarray, int, int, Optional[int], int, str]:
    """
    Returns: (imageId, image, nx, ny, nz, colorMode, fieldKey)
    """
    if _HAS_ADU:
        from AdImageUtility import AdImageUtility
        return AdImageUtility.reshapeNtNdArray(ntnda)

    image_id = ntnda['uniqueId']
    dims = ntnda['dimension']
    nDims = len(dims)

    # Default MONO
    color_mode = 0
    if 'attribute' in ntnda:
        for a in ntnda['attribute']:
            if a.get('name') == 'ColorMode':
                try:
                    color_mode = a['value'][0]['value']
                except Exception:
                    pass
                break

    # Get union field and raw data
    try:
        field_key = ntnda.getSelectedUnionFieldName()
        raw = ntnda['value'][0][field_key]
    except Exception:
        field_key = next(iter(ntnda['value'][0].keys()))
        raw = ntnda['value'][0][field_key]

    if nDims == 0:
        return (image_id, None, None, None, None, color_mode, field_key)

    if nDims == 2 and color_mode == 0:  # MONO
        nx = dims[0]['size']
        ny = dims[1]['size']
        img = np.asarray(raw).reshape(ny, nx)
        return (image_id, img, nx, ny, None, color_mode, field_key)

    if nDims == 3:
        d0, d1, d2 = dims[0]['size'], dims[1]['size'], dims[2]['size']
        arr = np.asarray(raw)
        if color_mode == 2:  # RGB1: [3, NX, NY] -> (ny, nx, 3)
            nz, nx, ny = d0, d1, d2
            img = arr.reshape(nz, nx, ny).transpose(2, 1, 0)
        elif color_mode == 3:  # RGB2: [NX, 3, NY] -> (ny, nx, 3)
            nx, nz, ny = d0, d1, d2
            img = arr.reshape(nx, nz, ny).transpose(2, 0, 1)
        elif color_mode == 4:  # RGB3: [NX, NY, 3] -> (ny, nx, 3)
            nx, ny, nz = d0, d1, d2
            img = arr.reshape(nx, ny, nz).transpose(1, 0, 2)
        else:
            # If effectively mono with one dim == 1, flatten to 2D
            if 1 in (d0, d1, d2):
                dims_sorted = sorted([d0, d1, d2], reverse=True)
                ny, nx = dims_sorted[:2]
                img = arr.reshape(ny, nx)
                color_mode = 0
            else:
                raise pva.InvalidArgument(f'Unsupported dims/colorMode: {dims}, cm={color_mode}')
        return (image_id, img, img.shape[1], img.shape[0], img.shape[2] if img.ndim == 3 else None,
                color_mode, field_key)

    raise pva.InvalidArgument(f'Invalid NTNDArray dims: {dims}')


# -----------------------------------------------------------------------------
# PVA subscriber (background thread) -> Tk queue
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
            # Force grayscale: convert RGB(A) -> luminance Y
            if img.ndim == 3 and img.shape[2] in (3, 4):
                img = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])
                if not np.issubdtype(img.dtype, np.floating):
                    img = img.astype(np.float32, copy=False)

            self.out_q.put((time.time(), uid, img))
        except Exception as exc:
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
# Tk viewer app (dark theme)
# -----------------------------------------------------------------------------
class PvViewerApp:
    def __init__(self, root, pv_name: str, max_fps: int = 30, show_toolbar: bool = True):
        self.root = root
        self.root.title(f"NTNDArray Viewer - {pv_name}")
        self.root.geometry("1280x880")

        self.max_fps = int(max_fps)
        self.frame_interval = (1.0 / self.max_fps) if self.max_fps > 0 else 0.0

        self.queue = queue.Queue(maxsize=10)
        self.sub = NtndaSubscriber(pv_name, self.queue)
        self.last_draw = 0.0
        self.paused = False

        # View/contrast state
        self.vmin = None
        self.vmax = None
        self.autoscale = tk.BooleanVar(value=True)
        self.flip_h = tk.BooleanVar(value=False)
        self.flip_v = tk.BooleanVar(value=False)
        self.transpose = tk.BooleanVar(value=False)
        self.current_uid = -1
        self.fps_ema = None
        self._last_ts = time.time()

        # Flat-field state
        self.flat = None
        self.apply_flat = tk.BooleanVar(value=False)
        self._last_display_img = None  # keeps last shown (for Capture Flat)

        self.show_toolbar = show_toolbar

        self._build_ui()
        self.sub.start()
        self._pump_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------- UI construction (dark) -------------
    def _build_ui(self):
        # Top controls
        top = ttk.Frame(self.root)
        top.pack(side="top", fill="x", padx=8, pady=6)

        ttk.Button(top, text="Pause", command=self._toggle_pause).pack(side="left")

        ttk.Checkbutton(top, text="Autoscale", variable=self.autoscale, command=self._apply_contrast)\
            .pack(side="left", padx=(10, 0))
        ttk.Checkbutton(top, text="Flip H", variable=self.flip_h, command=self._redraw)\
            .pack(side="left", padx=(8, 0))
        ttk.Checkbutton(top, text="Flip V", variable=self.flip_v, command=self._redraw)\
            .pack(side="left", padx=(6, 0))
        ttk.Checkbutton(top, text="Transpose", variable=self.transpose, command=self._redraw)\
            .pack(side="left", padx=(6, 0))

        # Flat-field controls
        ttk.Checkbutton(top, text="Apply Flat", variable=self.apply_flat, command=self._redraw)\
            .pack(side="left", padx=(14, 0))
        ttk.Button(top, text="Capture Flat", command=self._capture_flat)\
            .pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Load Flat…", command=self._load_flat)\
            .pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Save Flat…", command=self._save_flat)\
            .pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Clear Flat", command=self._clear_flat)\
            .pack(side="left", padx=(6, 0))

        ttk.Button(top, text="Save Frame…", command=self._save_frame)\
            .pack(side="left", padx=(14, 0))

        # Status (right side)
        self.lbl_uid = ttk.Label(top, text="UID: —")
        self.lbl_uid.pack(side="right")
        self.lbl_fps = ttk.Label(top, text="FPS: —")
        self.lbl_fps.pack(side="right", padx=(0, 14))

        # Main split: left (contrast + histogram) / right (image)
        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

        # Left panel
        left = ttk.Frame(main, width=320)
        left.pack_propagate(False)
        main.add(left, weight=0)

        # Contrast group
        cf = ttk.Labelframe(left, text="Contrast")
        cf.pack(side="top", fill="x", padx=6, pady=6)

        self.sld_min = tk.Scale(cf, from_=0, to=65535, orient="horizontal",
                                label="Min (vmin)", command=lambda e: self._slider_changed(),
                                bg="black", fg="white", highlightthickness=0)
        self.sld_max = tk.Scale(cf, from_=0, to=65535, orient="horizontal",
                                label="Max (vmax)", command=lambda e: self._slider_changed(),
                                bg="black", fg="white", highlightthickness=0)
        self.sld_min.pack(fill="x", padx=6, pady=(6, 6))
        self.sld_max.pack(fill="x", padx=6, pady=(0, 8))

        # Histogram group (default ON) - dark faces
        hf = ttk.Labelframe(left, text="Histogram")
        hf.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.hist_fig = Figure(figsize=(3, 2), dpi=100, facecolor="black")
        self.hist_ax = self.hist_fig.add_subplot(111, facecolor="black")
        self.hist_canvas = FigureCanvasTkAgg(self.hist_fig, master=hf)
        self.hist_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Right panel: image (dark)
        right = ttk.Frame(main)
        main.add(right, weight=1)

        self.fig = Figure(figsize=(6, 5), dpi=100, facecolor="black")
        self.ax = self.fig.add_subplot(111, facecolor="black")
        self.ax.set_axis_off()
        self.im_artist = None

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side="top", fill="both", expand=True)

        if self.show_toolbar:
            toolbar = NavigationToolbar2Tk(self.canvas, right)
            toolbar.update()

        # Try a dark-ish ttk theme
        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure(".", background="black", foreground="white")
            style.configure("TFrame", background="black")
            style.configure("TLabel", background="black", foreground="white")
            style.configure("TLabelframe", background="black", foreground="white")
            style.configure("TLabelframe.Label", background="black", foreground="white")
            style.configure("TCheckbutton", background="black", foreground="white")
            style.configure("TButton", background="#222222", foreground="white")
            style.configure("TPanedwindow", background="black")
        except Exception:
            pass

    # ------------- Queue pump -------------
    def _pump_queue(self):
        if self.paused:
            self.root.after(5, self._pump_queue)
            return

        if self.max_fps > 0:
            now = time.time()
            if now - self.last_draw < self.frame_interval:
                self.root.after(2, self._pump_queue)
                return
            latest = None
            while not self.queue.empty():
                latest = self.queue.get_nowait()
            if latest is not None:
                ts, uid, img = latest
                self._update_image(uid, img, ts)
                self.last_draw = now
            self.root.after(2, self._pump_queue)
        else:
            # Unthrottled: draw ASAP, coalesce to latest
            latest = None
            while not self.queue.empty():
                latest = self.queue.get_nowait()
            if latest is not None:
                ts, uid, img = latest
                self._update_image(uid, img, ts)
            self.root.after(1, self._pump_queue)

    # ------------- Image update/draw -------------
    def _update_image(self, uid: int, img: np.ndarray, ts: float):
        # View transforms
        if self.transpose.get():
            img = img.T
        if self.flip_h.get():
            img = np.flip(img, axis=1)
        if self.flip_v.get():
            img = np.flip(img, axis=0)

        # Flat-field (if enabled)
        if self.apply_flat.get() and self.flat is not None:
            img = self._apply_flat_field(img)

        # Remember displayed copy for Capture Flat
        self._last_display_img = img

        self.current_uid = uid

        # Slider ranges by dtype
        self._ensure_slider_range(img)

        # Contrast
        if self.autoscale.get() or self.vmin is None or self.vmax is None:
            vmin, vmax = self._autoscale_values(img)
            self._set_sliders(vmin, vmax, from_img=True)
        else:
            vmin, vmax = self.vmin, self.vmax

        # Draw (force grayscale cmap on black)
        if self.im_artist is None:
            self.im_artist = self.ax.imshow(img, origin='upper', vmin=vmin, vmax=vmax,
                                            aspect='equal', cmap='gray')
        else:
            self.im_artist.set_data(img)
            self.im_artist.set_clim(vmin=vmin, vmax=vmax)

        self.ax.set_axis_off()
        self.canvas.draw_idle()

        # Histogram
        self._draw_hist(img, vmin, vmax)

        # Status: FPS EMA
        now = time.time()
        dt = max(1e-6, now - getattr(self, "_last_ts", now))
        inst_fps = 1.0 / dt
        self.fps_ema = inst_fps if self.fps_ema is None else (0.8 * self.fps_ema + 0.2 * inst_fps)
        self._last_ts = now

        self.lbl_uid.config(text=f"UID: {uid}")
        self.lbl_fps.config(text=f"FPS: {self.fps_ema:4.1f}")

    def _draw_hist(self, img, vmin, vmax):
        self.hist_ax.clear()
        arr = img
        if arr.size > 4_000_000:
            sy = max(1, arr.shape[0] // 1000)
            sx = max(1, arr.shape[1] // 1000)
            arr = arr[::sy, ::sx]
        # white ticks on black background handled by style below
        self.hist_ax.hist(arr.ravel(), bins=256, color="white")
        self.hist_ax.set_title("Histogram", color="white")
        self.hist_ax.axvline(vmin, linestyle="--", color="white", alpha=0.8)
        self.hist_ax.axvline(vmax, linestyle="--", color="white", alpha=0.8)
        self.hist_ax.tick_params(colors="white")
        for spine in self.hist_ax.spines.values():
            spine.set_color("white")
        self.hist_canvas.draw_idle()

    # ------------- Contrast helpers -------------
    def _ensure_slider_range(self, img: np.ndarray):
        dtype = img.dtype
        if np.issubdtype(dtype, np.integer):
            info = np.iinfo(dtype)
            lo, hi = int(info.min), int(info.max)
            res = max(1, (hi - lo) // 1024)
        else:
            lo = float(np.nanpercentile(img, 0.1))
            hi = float(np.nanpercentile(img, 99.9))
            if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
                lo, hi = float(np.nanmin(img)), float(np.nanmax(img))
            res = max((hi - lo) / 1024.0, 1e-6)

        # Update slider bounds if changed
        if (float(self.sld_min.cget("to")) != float(hi)) or (float(self.sld_min.cget("from")) != float(lo)):
            self.sld_min.config(from_=lo, to=hi, resolution=res)
            self.sld_max.config(from_=lo, to=hi, resolution=res)

    def _autoscale_values(self, img: np.ndarray):
        lo = float(np.nanpercentile(img, 0.5))
        hi = float(np.nanpercentile(img, 99.5))
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            lo, hi = float(np.nanmin(img)), float(np.nanmax(img))
        return lo, hi

    def _set_sliders(self, vmin, vmax, from_img=False):
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
        if self.im_artist is None:
            return
        if self.autoscale.get():
            self.vmin, self.vmax = None, None
        else:
            if self.vmin is not None and self.vmax is not None:
                self.im_artist.set_clim(vmin=self.vmin, vmax=self.vmax)
                self.canvas.draw_idle()

    # ------------- Flat-field helpers -------------
    def _apply_flat_field(self, img: np.ndarray) -> np.ndarray:
        flat = self.flat
        if flat is None:
            return img
        if flat.shape != img.shape:
            messagebox.showwarning(
                "Apply Flat",
                f"Flat shape {flat.shape} != image shape {img.shape}. Skipping."
            )
            return img

        img_f = img.astype(np.float32, copy=False)
        flat_f = flat.astype(np.float32, copy=False)

        eps = 1e-6
        denom = np.maximum(flat_f, eps)
        scale = float(np.mean(flat_f)) if np.isfinite(flat_f).any() else 1.0

        out = (img_f / denom) * scale

        if np.issubdtype(img.dtype, np.integer):
            info = np.iinfo(img.dtype)
            out = np.clip(out, info.min, info.max).astype(img.dtype, copy=False)
        else:
            out = out.astype(img.dtype, copy=False)
        return out

    def _capture_flat(self):
        if self._last_display_img is None:
            messagebox.showinfo("Capture Flat", "No image to capture yet.")
            return
        self.flat = np.array(self._last_display_img, copy=True)
        messagebox.showinfo("Capture Flat", "Flat captured from current view.")

    def _load_flat(self):
        path = filedialog.askopenfilename(
            title="Load Flat (.npy)",
            filetypes=[("NumPy array", "*.npy"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            arr = np.load(path)
            self.flat = arr
            messagebox.showinfo("Load Flat", f"Loaded flat {arr.shape}, dtype={arr.dtype}")
            self._redraw()
        except Exception as e:
            messagebox.showerror("Load Flat", f"Failed to load flat:\n{e}")

    def _save_flat(self):
        if self.flat is None:
            messagebox.showinfo("Save Flat", "No flat to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Flat as .npy",
            defaultextension=".npy",
            filetypes=[("NumPy array", "*.npy"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            np.save(path, self.flat)
            messagebox.showinfo("Save Flat", f"Saved flat to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Flat", f"Failed to save flat:\n{e}")

    def _clear_flat(self):
        self.flat = None
        messagebox.showinfo("Clear Flat", "Flat cleared.")
        self._redraw()

    # ------------- Commands -------------
    def _toggle_pause(self):
        self.paused = not self.paused

    def _redraw(self):
        try:
            if self.im_artist is None:
                return
            arr = np.array(self.im_artist.get_array())
            self._update_image(self.current_uid, arr, time.time())
        except Exception:
            pass

    def _save_frame(self):
        if self.im_artist is None:
            messagebox.showinfo("Save Frame", "No image to save yet.")
            return
        arr = np.array(self.im_artist.get_array())
        path = filedialog.asksaveasfilename(
            defaultextension=".npy",
            filetypes=[("NumPy array", "*.npy"), ("PNG image", "*.png"), ("All files", "*.*")]
        )
        if not path:
            return
        if path.lower().endswith(".png"):
            self.fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="black")
        else:
            np.save(path, arr)

    def _on_close(self):
        try:
            self.sub.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Real-time NTNDArray Viewer (dark UI + grayscale + flat-field)")
    ap.add_argument("--pv", required=True, help="PVAccess NTNDArray PV name")
    ap.add_argument("--max-fps", type=int, default=30, help="Max redraw FPS (0 = unthrottled)")
    ap.add_argument("--no-toolbar", action="store_true", help="Hide Matplotlib zoom/pan toolbar")
    args = ap.parse_args()

    root = tk.Tk()
    # --- Dark background for the whole window ---
    root.configure(bg='black')
    try:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="black", foreground="white")
        style.configure("TFrame", background="black")
        style.configure("TLabel", background="black", foreground="white")
        style.configure("TLabelframe", background="black", foreground="white")
        style.configure("TLabelframe.Label", background="black", foreground="white")
        style.configure("TCheckbutton", background="black", foreground="white")
        style.configure("TButton", background="#222222", foreground="white")
        style.configure("TPanedwindow", background="black")
    except Exception:
        pass

    app = PvViewerApp(root,
                      pv_name=args.pv,
                      max_fps=args.max_fps,
                      show_toolbar=not args.no_toolbar)
    root.mainloop()


if __name__ == "__main__":
    main()
