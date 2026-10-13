# Architecture slide decks

Marp Markdown decks mirroring the long-form architecture docs in
[`../architecture/`](../architecture/). Same content, slide-shaped,
with the same mermaid diagrams.

## Decks

| File | Topic |
|---|---|
| `00-overview.md`                | Stack + conventions + who owns what         |
| `01-pystream.md`                | Viewer, dialogs, agent host, stream auto-pick |
| `02-bl_gui.md`                  | Layout engine, PVField, edit-mode autosave  |
| `03-detectors.md`               | Python IOC, ctypes backends, HDF5 from JSON |
| `04-beamline-agent.md`          | Chat loop, tools, sub-agents, in-process vs MCP |
| `05-beamlines-procedures.md`    | Markdown KB, human/AI file split            |
| `06-xanes_gui.md`               | Scan engine + QGMax interlock               |

## Build

Requires the Marp CLI:

```bash
npm install -g @marp-team/marp-cli
# or, no global install:
alias marp='npx @marp-team/marp-cli'
```

Then:

```bash
make html    # one HTML per deck, mermaid rendered via CDN JS
make pdf     # one PDF per deck  (needs Chromium / Chrome installed)
make pptx    # one PPTX per deck (editable in PowerPoint / LibreOffice / Keynote)
make serve   # live-reload browser preview of this directory
make clean
```

Output lands in `_build/`.

## Edit

Open any `*.md` in VSCode with the **Marp for VS Code** extension for
live WYSIWYG preview as you type. Changes are plain Markdown — git
diffs stay human-readable.

The front matter at the top of each file controls theme / paginate /
header / footer. The included decks use the stock `default` theme —
drop a custom CSS file in and set `theme:` to its basename to rebrand.
