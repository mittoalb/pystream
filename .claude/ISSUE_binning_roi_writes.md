# Cam Binning / SizeX / ROI writes don't take effect from pystream *or* bl_gui

## Summary
`caput` from either **pystream** (`DetectorControlDialog` → Apply Binning / Apply ROI)
or **bl_gui** (`_apply_cam_binning`, ROI fields) no longer changes the
`32idbSP1:cam1:BinX/BinY/SizeX/SizeY` and `32id:TXMOptics:CropLeft/Right/Top/Bottom`
PVs. The only way to change them is to write directly on the IOC host
(MEDM / caput from the IOC console). This worked several iterations ago;
regression coincides roughly with the "agent-ready" refactor of pystream.

## Affected code
- `src/pystream/beamlines/bl32ID/detectorcontrol.py`
  - `_apply_binning()` — writes `BinX`, `BinY`, `SizeX`, `SizeY`
    via `_set_pv_value()` → `caput -c` (subprocess).
  - `_apply_roi()` — writes `CropLeft/Right/Top/Bottom` then triggers
    `:Crop = 1`.
- `bl_gui/src/bl_gui/main_window.py::_apply_cam_binning` — mirrors the
  same PV set, using `caput_bg` (async, no put-callback).

Both apps use the identical PV names, hit the same IOC, and neither stops
`Acquire` before writing.

## Symptoms
- Log in `DetectorControlDialog` shows "Applied: BinX=..." (i.e. `caput`
  returns 0) but the value seen by any other client is unchanged.
- Same behavior from bl_gui.
- `caput` from the IOC host itself works normally.
- Users started noticing this once pystream sessions began staying open
  for days (post agent-ready), so the "worked before" observation may be
  survivorship — but the write-not-sticking is real either way.

## Likely root causes (in order of suspicion)
1. **Camera left in `Acquire=1` continuously.** AreaDetector drivers
   silently drop `BinX`/`SizeX` writes while acquiring; `caput` still
   exits 0. Something in the streaming / agent path may now hold the
   camera in continuous acquire.
2. **Autosave restore loop** aggressively re-applying old snapshot
   values inside the settle window after each put.
3. **Another CA client** (streaming server, agent tool, worker loop) is
   writing the old values right after the GUI writes the new ones.
4. Access-security / gateway change on the CA path — unlikely because
   MEDM from the IOC host works but is worth ruling out from a client
   host.

## How to diagnose (5 min at the beamline)
From a pystream/bl_gui client host, not the IOC:

```bash
caget 32idbSP1:cam1:Acquire 32idbSP1:cam1:BinX 32idbSP1:cam1:SizeX \
      32idbSP1:cam1:MaxSizeX_RBV 32idbSP1:cam1:DetectorState_RBV

# Try to change with Acquire on:
caput -c 32idbSP1:cam1:BinX 2
sleep 1
caget 32idbSP1:cam1:BinX     # → still old value?  Acquire lock confirmed.

# Stop acquire and retry:
caput -c 32idbSP1:cam1:Acquire 0
caput -c 32idbSP1:cam1:BinX 2
caget 32idbSP1:cam1:BinX     # → 2?  Then #1 is the cause.

# Restore:
caput -c 32idbSP1:cam1:BinX 1
caput -c 32idbSP1:cam1:Acquire 1
```

If BinX flips back to the old value seconds later even with Acquire=0,
suspect autosave (#2) or a competing writer (#3): `camonitor
32idbSP1:cam1:BinX` for a minute after a manual write and see who nudges
it back.

## Suggested fixes
Once root cause is confirmed:

- **If Acquire lock (most likely)**: in `_apply_binning` / `_apply_roi`
  save current `Acquire` state, `caput -c Acquire 0`, do the writes, then
  restore. bl_gui's `_apply_cam_binning` needs the same treatment.
- **Regardless of cause**: harden `_set_pv_value` to `caget` back after
  `caput -c` and log a mismatch as a WARN in the log widget, so a silent
  IOC-side reject is visible without leaving the UI.
- **If autosave**: coordinate with IOC config to drop these PVs from the
  autosave restore list, or extend the settle window in the GUI before
  the RBV verify.

## Notes
- Recent related fix (already in): `showEvent` refresh in
  `DetectorControlDialog` and `QGMaxDialog` so the singleton dialogs
  re-read PVs on every re-open (commits `e422167`, `fb0e03b`). That fix
  addressed *display staleness* only; this issue is about *writes not
  landing* and is unrelated.
- Env / versions: pystream branch `dev` @ `e422167` (plus qgmax
  `fb0e03b`); bl_gui HEAD `53b9489`.
