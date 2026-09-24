# pystream — repo-level guidance

## bmsg discipline (required for any new plugin or widget)

pystream is a peer client of the same EPICS blackboard as bl_gui. All
PV traffic and all intra-app events go through `bmsg`:
`https://github.com/mittoalb/bmsg`.

**Every dialog / plugin receives its parent's `hub` and `bus`:**

```python
class MyDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.hub = parent.hub if parent is not None and hasattr(parent, 'hub') else None
        self.bus = parent.bus if parent is not None and hasattr(parent, 'bus') else None
```

* PV read → `self.hub.subscribe(pv).valueChanged.connect(...)` or
  `self.hub.value(pv)` (cached last value).
* PV write → `self.hub.put(pv, v, verify_timeout=2.0)` — returns
  `False` when the IOC silently reverts (Acquire lock, autosave,
  competing writer). Log the mismatch; do not treat a silent revert
  as success.
* Intra-app event → `self.bus.<signal>.emit(...)` /
  `self.bus.<signal>.connect(...)`. Add new signals in
  `pystream/app_bus.py`.

**Never do any of these in widget code:**

* `subprocess.run(["caget", ...])` or `subprocess.run(["caput", ...])`.
* Open a raw `pvaccess.Channel` for a PV that the hub could own.
* Peek at `self.parent().image_view.getImageItem().image` — subscribe
  to the parent's `image_ready` signal instead.
* Invent a `~/.pystream/*_request.json` file for events that live
  inside one process. (Cross-process handshakes — e.g. the QGMax
  request file, read by pystream and written by xanes_gui / bl_gui —
  do still need a file or a dedicated PV, but never for intra-process
  events.)

Reference migrations: `beamlines/bl32ID/detectorcontrol.py` (pilot),
`beamlines/bl32ID/qgmax.py`.
