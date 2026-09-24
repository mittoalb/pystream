# QGMax background mode doesn't work when the dialog window isn't open

## Summary
QGMax's "background" execution paths (both the single-shot file trigger
from XANES2D and the auto-mode HDF5-location polling) do not actually run
optimizations unless the QGMax dialog window is physically open. The
whole point of the `QGMaxBackgroundWatcher` is that this should work
headless.

## Two independent bugs in `src/pystream/beamlines/bl32ID/qgmax.py`

### Bug 1 — Two disjoint `QGMaxDialog` instances

- Clicking the **QGMax** toolbar button goes through
  `PvViewerApp._open_singleton()` → caches
  `self.qgmaxdialog_instance` (dialog **A**, shown).
- `QGMaxBackgroundWatcher._ensure_dialog()` (qgmax.py:57-62) creates
  its own `QGMaxDialog(parent=self._parent_window, logger=logger)` in
  `self._dialog` (dialog **B**, never shown).

A and B are separate objects with independent state (`auto_mode_enabled`,
motor PV inputs, step sizes, `optimization_active`, `_qgmax_*_ts`, all
three QTimers). Any tweak the user makes in A is invisible to B, and B
runs against whatever `_restore_settings()` last persisted to disk.

If the user opens A and clicks *Enable Automated Mode*, the file
watcher's B never learns; and conversely a XANES2D `auto_enable` request
toggles B, not the visible A the user is watching.

### Bug 2 — `closeEvent` silently kills auto mode

`QGMaxDialog.closeEvent` (qgmax.py:1219-1237) does:

```python
self.trigger_poll_timer.stop()
if self.auto_mode_enabled:
    self.hdf5_location_monitor_timer.stop()
if self.is_running:
    self.optimization_timer.stop()
```

but never clears `self.auto_mode_enabled`, `self.is_running`, or the
button state.

Consequence: user opens the dialog, enables Auto, closes the dialog →
timers stop, but `auto_mode_enabled` stays `True`. A later file-trigger
that reaches `_external_set_auto_mode(True)` short-circuits at

```python
if self.auto_mode_enabled == enable:
    return
```

so the timer is never restarted. Silent no-op — auto mode looks
"enabled" but polls nothing.

## Repro
1. `pystream` on bl32ID (main window visible, image stream running).
2. Do **not** click the QGMax button.
3. Have XANES2D (or any client) write a fresh `ts` + `cmd: "auto_enable"`
   to `~/.pystream/qgmax_request.json`.
4. Observe: response file gets written (watcher acked), auto mode looks
   armed in logs — but no `_check_hdf5_location` firing on the visible
   dialog if the user later opens it, and the running B instance may or
   may not have a fresh enough image / correct settings.

Reverse case (visible A, close A after enabling Auto, XANES2D triggers):
- No optimization, no obvious error in log.

## Suggested fix

Two changes to `qgmax.py`:

1. **Make the background watcher reuse the singleton owned by
   `PvViewerApp`.** In `_ensure_dialog()`, before creating a new
   `QGMaxDialog`, first check for `self._parent_window.qgmaxdialog_instance`
   and reuse it. When the user opens the dialog for the first time
   *after* the watcher created one, likewise adopt the watcher's dialog
   as the singleton — or, simpler, always route through
   `PvViewerApp._open_singleton_headless('QGMaxDialog')` that returns
   the cached instance without calling `.show()`.

2. **In `closeEvent`, reset the enabled/running state alongside stopping
   timers**, so a subsequent `_toggle_auto_mode(True)` (or
   `_toggle_optimization(True)`) actually re-arms:

   ```python
   self.trigger_poll_timer.stop()
   if self.auto_mode_enabled:
       self.hdf5_location_monitor_timer.stop()
       self.auto_mode_enabled = False
       self.auto_mode_btn.setChecked(False)
   if self.is_running:
       self.optimization_timer.stop()
       self.is_running = False
       self.toggle_btn.setChecked(False)
   ```

   Or (cleaner): don't stop the timers on closeEvent at all — since the
   singleton stays alive, let the background timers keep running so the
   dialog behaves the same whether it's visible or hidden. Only stop
   them on true destruction.

Fix #1 is the load-bearing one for the reported symptom. Fix #2 removes
the reopen footgun.

## Notes
- `_get_image()` (qgmax.py:514) reads `parent().image_view.getImageItem().image`
  — that path works regardless of dialog visibility as long as the
  parent viewer is receiving frames, so the failure is not on the image
  side.
- Related recent context: `showEvent` was added to refresh status labels
  on re-show (commit `fb0e03b`). That fix is orthogonal — it addresses
  display staleness, not the background execution bug.
- Env: pystream branch `dev` @ `fb0e03b`.
