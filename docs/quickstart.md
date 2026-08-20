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
pip install -e .               # viewer + plugins only
pip install -e ".[ai]"         # …plus the AI agent (optional)
```

The `[ai]` extra installs the standalone [`beamline-agent`](https://github.com/mittoalb/beamline-agent) package, which provides the chat panel, Task Recorder, and Agents/Console dialogs. Without it, pystream runs normally — you just won't see the 🎥 Task Rec / 👥 Agents / 📜 Console toolbar buttons or the AI Agent dock.

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
- **AI Agent bottom panel** *(only if `beamline-agent` is installed)*:
  chat with an LLM assistant that can read live beamline state and
  (on bl32ID) run allowlisted IOC scripts. Configure protocol, URL,
  API key, model, and agent name via the panel's ⚙ Settings. See
  [Röntgen](beamlines/txmbot.md).
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
Beamline plugin settings live in `~/.pystream/<beamline>_settings.json`
(e.g. `bl32ID_settings.json`). When `beamline-agent` is installed,
its config lives in `~/.pystream/agent_settings.json` and its
conversation history in `~/.pystream/agent_history_dock.json`
(task recordings under `~/.pystream/task_recordings/`). API keys
stay local — nothing under `~/.pystream/` is tracked by git.
