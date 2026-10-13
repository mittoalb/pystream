# Screenshots for the architecture decks

Screenshots live here, named consistently so the decks pick them up on
every rebuild. Capture them from the beamline when each tool is on
screen.

## Capture

```bash
cd docs/slides
./capture.sh --all          # grab every shot the slides reference
./capture.sh 'QGMax' pystream-qgmax.png     # or one at a time
```

Behind the scenes: `wmctrl` finds the window by title regex, `import`
(ImageMagick) grabs the pixels. Both already installed on the beamline
workstation.

## Expected filenames

| Deck | Filename | What it shows | Status |
|---|---|---|---|
| overview, pystream, bl_gui | `pystream-main.png`      | pystream main window with camera stream | **present** (seeded from `docs/Images/pystream.png`) |
| pystream                    | `pystream-viewer.png`    | pystream viewer with ROI overlay        | **present** (seeded from `docs/Images/viewer.png`) |
| pystream                    | `pystream-mosalign.png`  | motor scan alignment dialog             | **present** (seeded from `docs/Images/mosalign.png`) |
| pystream                    | `pystream-detector.png`  | Detector Control dialog (Apply Binning) | capture needed |
| pystream, beamline-agent    | `pystream-qgmax.png`     | QGMax auto-mode window                  | capture needed |
| pystream                    | `pystream-autocenter.png`| AutoCenter dialog                       | capture needed |
| pystream                    | `pystream-cor.png`       | Center of Rotation dialog               | capture needed |
| pystream                    | `pystream-datamap.png`   | DataMap scan dialog                     | capture needed |
| bl_gui                      | `bl_gui-main.png`        | bl_gui layout — User Mode tab           | capture needed |
| bl_gui                      | `bl_gui-expert.png`      | bl_gui — Expert Mode tab                | capture needed |
| bl_gui                      | `bl_gui-edit.png`        | bl_gui in edit mode                     | capture needed |
| detectors                   | `detectors-gui.png`      | detectors Qt GUI                        | capture needed |
| detectors                   | `detectors-cli.png`      | terminal: `python run_ioc.py --list-cameras` + output | capture needed |
| beamline-agent              | `agent-chat.png`         | AI agent chat dock in pystream          | capture needed |
| beamline-agent              | `agent-console.png`      | agent Console panel (tool wire trace)   | capture needed |
| beamline-agent              | `agent-agents-panel.png` | Agents panel showing sub-agent tree     | capture needed |
| beamlines-procedures        | `procedures-tree.png`    | terminal: `tree ~/.pystream/procedures/` | capture needed |
| beamlines-procedures        | `procedures-example.png` | `cat` output of a sample procedure .md  | capture needed |
| xanes_gui                   | `xanes_gui-scan.png`     | XANES scan-setup tab                    | capture needed |
| xanes_gui                   | `xanes_gui-plot.png`     | XANES live spectrum tab                 | capture needed |

For the "capture needed" rows, drop the PNG into this directory with the
exact filename and `make -C .. html` rebuilds the deck with the new
image.

## Tips

- **Transparent background**: `import -alpha remove` to flatten.
- **Crop to window content** only (no desktop): `import -frame` includes
  WM decorations; omit `-frame` for the window only.
- **Capture during real use** when the GUIs show actual data — empty
  dialogs with blank plots don't communicate much.
