# sum_frames.py
import threading
import time
import sys
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

LOG = lambda *a: sys.stderr.write("[SumFrames] " + " ".join(map(str, a)) + "\n")

class SumFrames:
    """
    Running frame summation with a small control window:
      - Start / Stop accumulation
      - Reset accumulator
      - Save (.npy raw float64 or .png scaled)
      - Optional preview: show running sum in the viewer

    Window appears automatically once a Tk root exists (even if constructed
    before tk.Tk()). Also tries to pop on first frame.
    """

    def __init__(self, preview_sum: bool = True, window_title: str = "Sum Frames"):
        self.preview_sum_default = bool(preview_sum)
        self.window_title = window_title

        # Accumulator
        self._lock = threading.RLock()
        self._running = False
        self._sum: Optional[np.ndarray] = None
        self._count = 0
        self._shape = None

        # UI
        self._ui_ready = False
        self._popped_once = False
        self._top: Optional[tk.Toplevel] = None
        self._var_running: Optional[tk.BooleanVar] = None
        self._var_preview: Optional[tk.BooleanVar] = None
        self._lbl_count: Optional[ttk.Label] = None
        self._lbl_shape: Optional[ttk.Label] = None

        # Start a tiny watcher thread to wait for Tk root, then build window
        self._watcher_stop = threading.Event()
        t = threading.Thread(target=self._root_watcher, name="SumFramesRootWatcher", daemon=True)
        t.start()
        LOG("initialized; waiting for Tk root to build window")

    # ---------------- proc interface ----------------
    def apply(self, img: np.ndarray, meta: dict):
        # Make sure UI exists (in case watcher raced)
        self._ensure_ui()

        # Accumulate
        with self._lock:
            if (self._sum is None) or (self._shape != img.shape):
                self._init_accumulator(img)

            if self._running:
                arrf = img.astype(np.float64, copy=False)
                np.nan_to_num(arrf, copy=False)
                self._sum += arrf
                self._count += 1

        self._ui_async_update()
        self._maybe_pop_window()

        if self._var_preview and self._var_preview.get():
            with self._lock:
                return self._sum.astype(np.float32, copy=False)
        return img

    # ---------------- internals ----------------
    def _init_accumulator(self, img: np.ndarray):
        self._sum = np.zeros_like(img, dtype=np.float64)
        self._count = 0
        self._shape = img.shape
        LOG("accumulator initialized with shape", self._shape)

    def _root_watcher(self):
        # Poll for a Tk root; once found, schedule window build on Tk thread
        while not self._watcher_stop.is_set():
            root = tk._default_root
            if root is not None:
                try:
                    root.after(0, self._build_window_safe, root)
                    LOG("root found; scheduling window creation")
                except Exception as e:
                    LOG("failed scheduling window creation:", e)
                return
            time.sleep(0.1)  # light poll

    def _ensure_ui(self):
        if self._ui_ready:
            return
        root = tk._default_root
        if root is None:
            return
        try:
            root.after(0, self._build_window_safe, root)
        except Exception as e:
            LOG("ensure_ui error:", e)

    def _build_window_safe(self, root):
        if self._ui_ready:
            return
        try:
            self._top = tk.Toplevel(root)
            self._top.title(self.window_title)
            self._top.resizable(False, False)

            frame = ttk.Frame(self._top, padding=8)
            frame.pack(fill="both", expand=True)

            row1 = ttk.Frame(frame); row1.pack(fill="x")
            ttk.Button(row1, text="Start", command=self._ui_start).pack(side="left")
            ttk.Button(row1, text="Stop", command=self._ui_stop).pack(side="left", padx=(6, 0))
            ttk.Button(row1, text="Reset", command=self._ui_reset).pack(side="left", padx=(12, 0))
            ttk.Button(row1, text="Save…", command=self._ui_save).pack(side="left", padx=(12, 0))

            row2 = ttk.Frame(frame); row2.pack(fill="x", pady=(8, 0))
            self._var_running = tk.BooleanVar(master=self._top, value=False)
            self._var_preview = tk.BooleanVar(master=self._top, value=self.preview_sum_default)
            ttk.Checkbutton(row2, text="Running", variable=self._var_running,
                            command=self._ui_toggle_running).pack(side="left")
            ttk.Checkbutton(row2, text="Preview sum in viewer",
                            variable=self._var_preview).pack(side="left", padx=(12, 0))

            row3 = ttk.Frame(frame); row3.pack(fill="x", pady=(8, 0))
            ttk.Label(row3, text="Frames summed:").pack(side="left")
            self._lbl_count = ttk.Label(row3, text="0"); self._lbl_count.pack(side="left", padx=(4, 20))
            ttk.Label(row3, text="Shape:").pack(side="left")
            self._lbl_shape = ttk.Label(row3, text="—"); self._lbl_shape.pack(side="left", padx=(4, 0))

            self._top.protocol("WM_DELETE_WINDOW", self._ui_hide)

            self._ui_ready = True
            self._ui_async_update()
            LOG("window created")
        except Exception as e:
            LOG("window creation failed:", e)

    def _maybe_pop_window(self):
        if not self._ui_ready or self._popped_once:
            return
        self._popped_once = True
        top = self._top
        if not top:
            return
        def _raise():
            try:
                top.deiconify()
                top.lift()
                top.attributes("-topmost", True)
                top.after(250, lambda: top.attributes("-topmost", False))
                LOG("window raised")
            except Exception as e:
                LOG("raise failed:", e)
        try:
            top.after(0, _raise)
        except Exception as e:
            LOG("after raise failed:", e)

    # ---------------- UI <-> state ----------------
    def _ui_async_update(self):
        if not self._ui_ready:
            return
        with self._lock:
            count = self._count
            shape = self._shape

        def _do():
            try:
                if self._lbl_count is not None:
                    self._lbl_count.config(text=str(count))
                if self._lbl_shape is not None:
                    self._lbl_shape.config(text=str(shape) if shape else "—")
            except Exception as e:
                LOG("label update failed:", e)

        try:
            self._top.after(0, _do)
        except Exception as e:
            LOG("after update failed:", e)

    def _ui_start(self):
        with self._lock:
            self._running = True
        if self._var_running:
            self._var_running.set(True)
        LOG("started")

    def _ui_stop(self):
        with self._lock:
            self._running = False
        if self._var_running:
            self._var_running.set(False)
        LOG("stopped")

    def _ui_reset(self):
        with self._lock:
            if self._shape is not None:
                self._sum = np.zeros(self._shape, dtype=np.float64)
            self._count = 0
        self._ui_async_update()
        LOG("reset")

    def _ui_toggle_running(self):
        with self._lock:
            self._running = bool(self._var_running.get() if self._var_running else False)
        LOG("running =", self._running)

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
                data = arr
                vmin, vmax = np.nanmin(data), np.nanmax(data)
                if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
                    data = np.zeros_like(data, dtype=np.uint16)
                else:
                    rng = vmax - vmin if (vmax - vmin) > 0 else 1.0
                    norm = np.clip((data - vmin) / rng, 0, 1)
                    data = (norm * 65535.0).astype(np.uint16)
                from PIL import Image
                Image.fromarray(data).save(path)
            else:
                np.save(path, arr)
            messagebox.showinfo("Save Sum", f"Saved to:\n{path}")
            LOG("saved", path)
        except Exception as e:
            messagebox.showerror("Save Sum", f"Failed to save:\n{e}")
            LOG("save failed:", e)

    def _ui_hide(self):
        if self._top is not None:
            try:
                self._top.withdraw()
                LOG("window hidden")
            except Exception as e:
                LOG("hide failed:", e)

    # Optional external hook if your pipeline exposes it
    def show_window(self):
        self._ensure_ui()
        self._popped_once = False
        self._maybe_pop_window()

