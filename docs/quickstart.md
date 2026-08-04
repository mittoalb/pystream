# Quickstart

PyStream is a viewer for EPICS PVAccess **NTNDArray** image streams,
with TIFF recording, flat-field correction, and a plugin pipeline.

## Install

```bash
conda create -n pystream python=3.10 numpy pyqt -c conda-forge
conda activate pystream
pip install pvapy pyqtgraph Pillow
conda install h5py

git clone https://github.com/mittoalb/pystream.git
cd pystream
pip install -e .
```

If Qt can't find the `xcb` plugin, point `QT_QPA_PLATFORM_PLUGIN_PATH`
at your conda env's `plugins/platforms`.

## Run

```bash
pystream --pv YOUR:NTNDARRAY:PV
```

Common flags: `--max-fps`, `--display-bin`, `--proc-config`,
`--no-plugins`, `--log-level`, `--log-file`. See `pystream --help`.

## What's in the UI

- **Top toolbar**: Reset View, Beamlines toggle, HDF5 Viewer.
- **Beamlines bar**: appears when toggled; lists tools from the active
  beamline (see [Beamlines](beamlines/index.md)).
- **Side panel**: crosshair, ROI, ellipse, line profile, scale bar,
  metrics, console — see [Plugins](plugins/index.md).
- **Recording**: Browse to pick an output dir, set a filename prefix,
  click **⏺ Record**. Frames go to RAM and are written as TIFFs by a
  background writer pool; click again to stop.
- **Flat field**: *Capture* to store the current frame, *Apply Flat* to
  toggle `I_norm = (I_raw / I_flat) * mean(I_flat)`.

## Plugin pipeline

Each frame can be processed by an ordered chain of plugins declared in
`pipelines/processors.json`:

```json
{
  "processors": [
    {"name": "MyFilter", "module": "processors.myfilter",
     "class": "MyFilter", "kwargs": {"param": 1.0}}
  ]
}
```

A processor is any class with an `apply(img, meta) -> img` method:

```python
class MyFilter:
    def __init__(self, **kwargs):
        self.param = kwargs.get("param", 1.0)

    def apply(self, img, meta):
        return img * self.param
```

Drop the file under `processors/` and reference it from the JSON.

## Config

Viewer state (last PV, etc.) lives in `~/.pystream/viewer_config.json`.
Beamline plugin settings live in `~/.pystream/bl32ID_settings.json`.
