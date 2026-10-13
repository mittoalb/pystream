# beamlines-procedures

Hand-authored, version-controlled procedures the AI agent reads on
demand. The scientist's canonical knowledge base — kept in the
scientist's words, in markdown, in git.

## Purpose in one sentence

Ship a tree of markdown procedures (motor conventions, valve
sequences, alignment recipes, scan setups) separately from
`beamline-agent` and `pystream`, so the scientist updates knowledge
in one place with a `git push` and every machine that `pip install -e`s
this package picks it up on next launch.

## Where it fits

```{mermaid}
flowchart LR
    SCI[scientist]
    REPO[beamlines-procedures<br/>git repo]
    PKG[pip install -e<br/>on each machine]
    HOME[~/.pystream/procedures/]
    BA[beamline-agent]
    AGENT[agent at run time]

    SCI -- edit .md + git push --> REPO
    REPO --> PKG
    PKG -- copy at chat startup --> HOME
    HOME --> BA
    BA -- include in system prompt / lookup --> AGENT
    AGENT -- writes .ai.md twins --> HOME
    SCI -. review .ai.md, merge, delete .-> HOME
```

Three important properties:

1. **Independent of pystream and beamline-agent**. Pure data package.
   Install it, don't install it — nothing breaks either way.
2. **One-way sync into the user's home**. The package tree is the
   source of truth; `~/.pystream/procedures/` is a snapshot the
   agent reads from. Delete a file in `~/.pystream/procedures/` to
   force a fresh copy on next launch.
3. **Two file kinds, same directory**. Human markdown and agent
   markdown live side by side with a naming convention — never
   collide.

## Architecture

```{mermaid}
flowchart TB
    subgraph Repo ["beamlines-procedures (git)"]
        TREE[src/beamlines_procedures/data/<br/>bl32ID/.../topic.md]
    end

    subgraph Env ["Python env"]
        PIP[pip install -e beamlines-procedures]
        IMPORT[import beamlines_procedures]
    end

    subgraph Runtime ["Per user / per machine"]
        BOOT[beamline-agent bootstrap]
        LOCAL[~/.pystream/procedures/]
        AGENT[agent read]
        AI[agent writes .ai.md twin]
    end

    TREE --> PIP
    PIP --> IMPORT
    IMPORT --> BOOT
    BOOT --> LOCAL
    LOCAL --> AGENT
    AGENT --> AI
    AI --> LOCAL
```

## File naming convention

Two kinds in the same directory:

| Filename pattern   | Author  | Agent permission                              |
|--------------------|---------|-----------------------------------------------|
| `<topic>.md`       | human   | **read only** — never overwritten by agent   |
| `<topic>.ai.md`    | agent   | read / write — agent persists observations    |

The `.ai.md` split is deliberate. It lets the agent capture
observations ("this motor overshoots when exposure > 0.5s") without
ever touching the scientist's canonical file. The scientist reviews
the `.ai.md` at leisure, merges useful bits into the main `.md`,
deletes the `.ai.md` twin.

## Layout

```
src/beamlines_procedures/data/
├── README.md              (naming convention + per-file format)
├── bl32ID/
│   ├── motors/           (zone_plate.md, sample.md, condenser.md, …)
│   ├── valves/           (granite_air.md, shutters.md, …)
│   ├── energy/           (mono_calibration.md, xanes_setup.md, …)
│   ├── alignment/        (cor.md, zp_alignment.md, particle_align.md, …)
│   └── general.md
├── bl19BM/
└── general/
```

Filename is the topic, path is the scope. The agent constructs the
exact path (`<beamline>/<category>/<topic>.md`) rather than scanning
the tree — fast and deterministic.

## Per-file format (recommended)

Each `<topic>.md` should answer:

| Section         | What goes there                                                |
|-----------------|----------------------------------------------------------------|
| Preconditions   | What state the beamline must be in before this procedure runs  |
| PVs             | Named CA / PVA channels the procedure touches                  |
| Procedure       | Step list, concrete values, no hand-waving                     |
| Verification    | How to tell it worked                                          |
| Gotchas         | Known failure modes + their fixes                              |

The agent uses the `PVs` section to populate its tool calls and the
`Gotchas` section to warn the user before firing anything
destructive.

## Startup bootstrap

At pystream launch:

1. `beamline-agent` tries `import beamlines_procedures`.
2. If present → copies `beamlines_procedures/data/<beamline>/` tree
   to `~/.pystream/procedures/<beamline>/` (skip files that already
   exist locally — never overwrites a file the user may have edited
   locally).
3. If absent → agent runs with no procedures section in its system
   prompt; nothing else changes.

The copy is **additive**. Delete a file in `~/.pystream/procedures/`
and restart pystream to force a fresh copy from the package.

## Authoring workflow

```
cd ~/Software/beamlines-procedures
vim src/beamlines_procedures/data/bl32ID/valves/granite_air.md
git add -A && git commit -m "..." && git push

# On any other machine (home is NFS so often already visible):
git pull
rm ~/.pystream/procedures/bl32ID/valves/granite_air.md    # if updated
# restart pystream — the agent re-copies from the package
```

The scientist does not need to touch pystream or beamline-agent to
roll out an update to a procedure.

## Dependencies

* None at runtime beyond standard library (it's a data package).
* Build-time: `setuptools>=61` (`pip install -e .` works out of the box).

## Known gotchas

* **Local edits in `~/.pystream/procedures/` persist** across
  restarts (that's intentional). To blow them away and resync from
  the package, delete the file and relaunch.
* **The agent never writes to `<topic>.md`**. If you see a change
  you didn't make, it's in the `.ai.md` twin — merge or discard.
* **Package installs via `-e` only**. The agent is written against
  the editable install path layout (`src/beamlines_procedures/data`).
  A regular `pip install .` works but then the data lives inside
  `site-packages/` and `git pull` won't help — stick with `-e`.

## Future / open questions

* Multi-beamline overlay (procedures that apply to all beamlines
  that use a specific detector, cross-cutting). Current structure
  is strictly per-beamline + a `general/`.
* Signed `<topic>.ai.md` entries so merge decisions have provenance
  (which agent run, which sample, when).
* Procedure search by example PV name — currently the agent has to
  know the path to the file.
