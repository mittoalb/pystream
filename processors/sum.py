# sum_frames.py
import threading
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class SumFrames:
    """
    Processor plugin for procplug. Keeps a running sum of frames.
    - Buttons: Start / Stop / Reset / Save (.npy or .png)
    - Optionally preview the running sum instead of the live frame (checkbox)
    """

    def __init__(self, preview_sum: bool = True, window_title: str = "Sum Frames"):
        self.preview_sum_default = bool(preview_sum)
        self.window_title = window_title

        self._lock = threading.RLock()
        self._running = False
        self._sum = None
        self._count = 0
        self._dtype = None
        self._shape = None

        # UI bits (created on first safe opportunity on the Tk main thread)
        self._ui_ready = False
        self._var_running = tk.BooleanVar(value=False) if tk._default_root else None
        self._var_preview = tk.BooleanVar(value=self.preview_sum_default) if tk._default_root else None
        self._lbl_count = None
        self._lbl_shape = None
        self._top = None

    # ----- proc interface -----
    def apply(self, img: np.ndarray, meta: dict):
        """
        The pipeline calls this for each frame.
        """
        # Lazily create UI on the Tk main thread
        self._ensure_ui()

        with self._lock:
            # (Re)initialize accumulator on first frame or shape change
            if (self._sum is None) or (self._shape != img.shape):
                self._init_accumulator(img)

            if self._running:
                # Accumulate in float64 to avoid overflow; keep NaNs out
                arrf = img.astype(np.float64, copy=False)
                np.nan_to_num(arrf, copy=False)
                self._sum += arrf
                self._count += 1

            # Update labels (on Tk thread)
            self._ui_async_update()

            # Output either the live frame or the running sum
            if self._var_preview and self._var_preview.get():
                # Return the sum as float32 (viewer handles float)
                return self._sum.astype(np.float32, copy=False)
            else:
                return img

    # ----- internals -----
    def _init_accumulator(self, img: np.ndarray):
        self._sum = np.zeros_like(img, dtype=np.float64)
        self._count = 0
        self._dtype = img.dtype
        self._shape = img.shape

    # ----- UI creation / updates -----
    def _ensure_ui(self):
        # No root yet? skip (viewer will call again)
        root = tk._default_root
        if (root is None) or self._ui_ready:
            return
        # Schedule actual UI creation on Tk thread
        try:
            root.after(0, self._build_window_safe, root)
        except Exception:
            pass

    def _build_window_safe(self, root):
        if self._ui_ready:
            return

        self._top = tk.Toplevel(root)
        self._top.title(self.window_title)
        self._top.attributes("-topmost", False)
        self._top.resizable(False, False)

        frame = ttk.Frame(self._top, padding=8)
        frame.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        ttk.Button(btns, text="Start", command=self._ui_start).pack(side="left")
        ttk.Button(btns, text="Stop", command=self._ui_stop).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Reset", command=self._ui_reset).pack(side="left", padx=(12, 0))
        ttk.Button(btns, text="Save…", command=self._ui_save).pack(side="left", padx=(12, 0))

        opts = ttk.Frame(frame)
        opts.pack(fill="x", pady=(8, 0))
        self._var_running = tk.BooleanVar(value=False)
        self._var_preview = tk.BooleanVar(value=self.preview_sum_default)
        ttk.Checkbutton(opts, text="Running", variable=self._var_running,
                        command=self._ui_toggle_running).pack(side="left")
        ttk.Checkbutton(opts, text="Preview sum in viewer", variable=self._var_preview)\
            .pack(side="left", padx=(12, 0))

        stats = ttk.Frame(frame)
        stats.pack(fill="x", pady=(8, 0))
        ttk.Label(stats, text="Frames summed:").pack(side="left")
        self._lbl_count = ttk.Label(stats, text="0")
        self._lbl_count.pack(side="left", padx=(4, 20))
        ttk.Label(stats, text="Shape:").pack(side="left")
        self._lbl_shape = ttk.Label(stats, text="—")
        self._lbl_shape.pack(side="left", padx=(4, 0))

        # Close behavior
        self._top.protocol("WM_DELETE_WINDOW", self._ui_hide)

        self._ui_ready = True
        self._ui_async_update()

    def _ui_async_update(self):
        root = tk._default_root
        if not (root and self._ui_ready):
            return
        # Read counters under lock, push to labels on Tk thread
        with self._lock:
            count = self._count
            shape = self._shape

        def _do():
            if self._lbl_count is not None:
                self._lbl_count.config(text=str(count))
            if self._lbl_shape is not None:
                self._lbl_shape.config(text=str(shape) if shape else "—")
        try:
            root.after(0, _do)
        except Exception:
            pass

    # ----- UI callbacks -----
    def _ui_start(self):
        with self._lock:
            self._running = True
        if self._var_running:
            self._var_running.set(True)

    def _ui_stop(self):
        with self._lock:
            self._running = False
        if self._var_running:
            self._var_running.set(False)

    def _ui_reset(self):
        with self._lock:
            if self._shape is not None:
                self._sum = np.zeros(self._shape, dtype=np.float64)
            self._count = 0
        self._ui_async_update()

    def _ui_toggle_running(self):
        with self._lock:
            self._running = bool(self._var_running.get())

    def _ui_save(self):
        with self._lock:
            if self._sum is None:
                messagebox.showinfo("Save Sum", "No sum yet.")
                return
            arr = self._sum.copy()
        path = filedialog.asksaveasfilename(
            title="Save sum",
            defaultextension=".npy",
            filetypes=[("NumPy array", "*.npy"), ("PNG image", "*.png"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            if path.lower().endswith(".png"):
                # Convert to 16-bit for PNG if dynamic range fits; else 8-bit
                data = arr
                vmin, vmax = np.nanmin(data), np.nanmax(data)
                if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
                    data = np.zeros_like(data, dtype=np.uint16)
                else:
                    rng = vmax - vmin
                    if rng <= 0:
                        data = np.zeros_like(data, dtype=np.uint16)
                    else:
                        norm = (data - vmin) / rng
                        norm = np.clip(norm, 0, 1)
                        data = (norm * 65535.0).astype(np.uint16)
                # Lazy import to avoid hard dependency
                from PIL import Image
                Image.fromarray(data).save(path)
            else:
                # Save raw float64 sum
                np.save(path, arr)
            messagebox.showinfo("Save Sum", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Sum", f"Failed to save:\n{e}")

    def _ui_hide(self):
        # Just hide the window; keep accumulation state
        if self._top is not None:
            self._top.withdraw()

