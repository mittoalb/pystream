# NTNDArray Real-time Viewer (`pystream`)

Real-time viewer for EPICS PVAccess `NTNDArray` data with a dark UI, histogram/contrast controls, flat-field correction, and a **plugin pipeline** for custom image processing. Now includes **PV persistence** across launches and a **colorized logger** with optional file output.

![GUI Interface](https://github.com/mittoalb/pystream/blob/main/GUI.png)

---

## Features

- Real-time 2D image display from EPICS PVA `NTNDArray` PVs
- Grayscale conversion (RGB → luminance) with `cmap='gray'`
- Dark, minimal interface (black background, white text)
- Histogram + manual contrast sliders (Autoscale toggle)
- Flat-field correction (Capture / Load / Save / Clear / Apply)
- **Plugin pipeline** (JSON-defined) — run arbitrary processors on each frame
- Pause / Resume, Save Frame (`.npy`, `.png`)
- FPS and UID readout
- Optional Matplotlib toolbar for zoom/pan
- **PV persistence**: last-used PV is saved to `viewer_config.json`
- **Structured logging**: colored console + optional file (`--log-file`), levels via `--log-level`

---

## Requirements

- Python 3.8+
- EPICS PVA client: `pvaccess`
- GUI: `tkinter` (system package on many Linux distros)
- Core Python libs: `numpy`, `matplotlib`
- (Optional, for some plugins when saving PNGs) `Pillow`

Install deps with pip:

```bash
pip install numpy matplotlib pvaccess Pillow
```

Install Tk for the GUI (Linux example):
```bash
sudo apt install python3-tk
```

---

## Installation

Editable install from the repo root:

```bash
pip install -e .
```

Or run the script/module directly from source as long as dependencies are present.

---

## Usage

Basic run pointing to an NTNDArray PV:

```bash
pystream --pv YOUR:NTNDARRAY:PV
```

Command-line options:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--pv` | Pre-fill PVAccess NTNDArray PV name (GUI can change it at runtime) | `` |
| `--max-fps` | UI redraw throttle (0 = unthrottled) | `30` |
| `--no-toolbar` | Hide Matplotlib toolbar | off |
| `--proc-config` | Path to plugin pipeline JSON | `pipelines/processors.json` |
| `--no-plugins` | Disable plugin processing | off |
| `--log-file` | Path to log file (if set, logs also go to file) | unset |
| `--log-level` | Logging level: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` |

Examples:

```bash
# Typical usage with a pipeline:
pystream --pv 32idbSP1:Pva1:Image --proc-config pipelines/processors.json

# Verbose logging to both console (colored) and file:
pystream --pv 32idbSP1:Pva1:Image --log-level DEBUG --log-file viewer.log
```

---

## PV Persistence

The viewer remembers the last PV you typed in the GUI and saves it to `viewer_config.json` next to the script. On the next launch, the field is pre-filled and the app will auto-connect.

- You can still override on the command line with `--pv` for that run.
- On close, the current value in the PV field is persisted.

---

## Flat-field Correction

Flat-field normalization removes detector/illumination nonuniformity:

```
I_norm = (I_raw / I_flat) * mean(I_flat)
```

| Button       | Function                                |
| ------------ | ---------------------------------------- |
| Capture Flat | Capture current image as flat            |
| Apply Flat   | Enable/disable flat-field correction     |
| Load Flat    | Load `.npy` flat file                    |
| Save Flat    | Save flat to `.npy`                      |
| Clear Flat   | Remove current flat                      |

Notes:
- If the flat shape doesn’t match the incoming frame, it’s ignored with a warning.
- Flat-fielding combines with the plugin pipeline output.

---

## Plugin Pipeline

Processing happens in a **plugin pipeline** defined by a JSON file (passed via `--proc-config`). Each processor can modify the image before it is drawn.

> The exact JSON schema is defined by `procplug.py`. A common schema is shown below (module/class/kwargs). Adjust to your local `procplug.py` if it differs.

### Example (class-based processor)

**`pipelines/processors.json`**
```json
{
  "processors": [
    {
      "name": "SumFrames",
      "module": "sum",
      "class": "SumFrames",
      "kwargs": { "preview_sum": true }
    }
  ]
}
```

This expects a file `sum.py` on the import path with a class `SumFrames` that exposes:
```python
class SumFrames:
    def __init__(self, **kwargs): ...
    def apply(self, img, meta):   # returns processed image
        return img
```

> If your local pipeline expects function-style processors, adapt your plugin or `procplug.py` accordingly. The viewer itself is agnostic and simply calls `PIPE.apply(...)` if a pipeline is present.

---

## Built-in Example Plugin — Sum Frames

A sample plugin `sum.py` (not part of the core) keeps a **running sum** of frames and opens a small control window:

- **Start / Stop** summation
- **Reset** accumulator
- **Save…** to `.npy` (float64 sum) or `.png` (normalized)
- **Preview** checkbox to show the running sum in the viewer instead of the live frame

Add to your pipeline JSON (see above). Place `sum.py` next to the main script or on `PYTHONPATH`.

Troubleshooting the plugin window:
- Ensure the plugin module name in JSON matches the file name (`sum.py` → `"module": "sum"`).
- Confirm the processors JSON is valid UTF‑8 (no BOM, no comments/trailing commas). An empty JSON file will fail to load.
- Make sure `--no-plugins` is **not** set and `--proc-config` points to the right file.
- If using older Python (<3.10), avoid typing unions like `dict | None` in plugin code; use `Optional[dict]` instead.

---

## Logging

Logging is configured via `logger.py` and integrated into the viewer:

- Colored console logs via `ColoredLogFormatter`
- Optional file logging (`--log-file path`)
- Set verbosity with `--log-level`

Examples:
```bash
# Info-level console logs (default)
pystream --pv 32idbSP1:Pva1:Image

# Debug-level + file
pystream --pv 32idbSP1:Pva1:Image --log-level DEBUG --log-file viewer.log
```

The logger name used by the app is `pystream`. Unhandled exceptions and plugin errors are reported with stack traces via `log_exception(...)`.

---

## Directory Layout (example)

```
pystream/
    __init__.py
    pystream.py
    procplug.py
    pipelines/
        processors.json
    plugins/            # optional, if you organize plugins here
        sum.py
    logger.py
README.md
pyproject.toml
```

Your local organization may vary; adjust the `--proc-config` path and Python import paths accordingly.

---

## Notes

- Pipelines execute in JSON order (top to bottom).
- Flat-fielding can be combined with plugin stages.
- Saving frames writes `.png` or raw `.npy` arrays of the current view.
- The histogram auto-subsamples very large arrays to keep UI responsive.
- If you encounter `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`, you are running Python < 3.10 with PEP 604 union types in annotations—switch to `typing.Optional[...]` or upgrade Python.
