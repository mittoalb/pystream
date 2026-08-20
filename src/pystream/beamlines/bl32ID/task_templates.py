"""Task templates for bl32ID's Task Recorder.

A "task template" is a pre-populated entry in the Task Recorder
dialog's dropdown: a display name, a curated context string, and the
list of motor PVs the task typically touches. Templates save typing
and make procedures self-documenting; the user is still free to add
motors on the fly (uncheck defaults, use free-text mode, etc.).

**Authoritative source for PVs**: the beamline's
`txmOptics.substitutions` file (in txmOptics EPICS module,
`db/txmOptics.template` macros). Every motor PV below mirrors that
file's pattern block — update here when txmOptics changes.

The 32-ID templates are ordered per the standard alignment workflow
(steps 1–6 done individually, then a joint refinement) plus a Sample
task (positioning between scans — off the 1–6 numbering):

    1. Detector      — focus & rotation
    2. Zone Plate    — position & focus
    3. Phase Ring    — position
    4. Condenser     — position & angles
    5. Pinhole       — position
    6. Beam Stop     — position
    –  Sample        — per-scan positioning
    7. Final Joint Refinement — all 15 optics axes together

`task_template_map()` is what beamline_agent.task_recorder consumes
via bl32ID/__init__.py's provide_task_templates() hook.

`bl_gui_element_dump()` remains available for cross-checking PV
assignments against bl_gui's own layout when txmOptics is edited.
"""

import json
import os
from typing import Dict, List


# ── curated map — mirrors txmOptics.substitutions ────────────────────
#
# NOTE:
#   - Motors marked "x" in txmOptics.substitutions (CONDENSER_YAW,
#     FURNACE_X/Y/Z) are omitted here — the hardware isn't installed.
#   - Detector rotation is NOT defined in txmOptics.substitutions;
#     `32idbTXM:nf:m2` is picked up from bl_gui's Queensgate#4 panel.
#     Confirm on the live beamline before trusting it in a recording.

CURATED_TASKS: Dict[str, Dict[str, object]] = {
    "Detector": {
        "context": (
            "# Detector alignment  (step 1 of 6)\n\n"
            "**Goal:** focus and rotation.\n\n"
            "**Motors:**\n"
            "- Det Focus (Z)  —  32idbSoft:m1\n"
            "- Det Rotation   —  32idbTXM:nf:m2\n\n"
            "**Notes:**\n"
            "- Det X / Det Y are usually NOT touched during this step.\n"
            "  Add them via free-text mode if a session needs them.\n"
            "- Det Rotation PV is not in txmOptics.substitutions — it\n"
            "  came from bl_gui's Queensgate#4 panel. Verify on live\n"
            "  beamline before trusting a recording of this element.\n"
        ),
        "motors": [
            {"label": "Det Focus (Z)", "pv": "32idbSoft:m1"},        # DETECTOR_Z
            {"label": "Det Rotation",  "pv": "32idbTXM:nf:m2"},      # not in txmOptics — from bl_gui
        ],
    },
    "Zone Plate": {
        "context": (
            "# Zone plate alignment  (step 2 of 6)\n\n"
            "**Goal:** X/Y position + Z focus.\n\n"
            "**Motors:**\n"
            "- ZP X          —  32idbTXM:mcs2:c1:m13\n"
            "- ZP Y          —  32idbTXM:mcs2:c1:m14\n"
            "- ZP Focus (Z)  —  32idbTXM:mcs2:c1:m15\n\n"
            "**Notes:**\n"
            "- Depends on Detector step 1 being complete.\n"
        ),
        "motors": [
            {"label": "ZP X",          "pv": "32idbTXM:mcs2:c1:m13"},  # ZONEPLATE_X
            {"label": "ZP Y",          "pv": "32idbTXM:mcs2:c1:m14"},  # ZONEPLATE_Y
            {"label": "ZP Focus (Z)",  "pv": "32idbTXM:mcs2:c1:m15"},  # ZONEPLATE_Z
        ],
    },
    "Phase Ring": {
        "context": (
            "# Phase ring alignment  (step 3 of 6)\n\n"
            "**Goal:** X/Y position.\n\n"
            "**Motors:**\n"
            "- Phase Ring X  —  32idbTXM:mcs2:c3:m1\n"
            "- Phase Ring Y  —  32idbTXM:mcs2:c3:m2\n"
        ),
        "motors": [
            {"label": "Phase Ring X",  "pv": "32idbTXM:mcs2:c3:m1"},   # PHASERING_X
            {"label": "Phase Ring Y",  "pv": "32idbTXM:mcs2:c3:m2"},   # PHASERING_Y
        ],
    },
    "Condenser": {
        "context": (
            "# Condenser alignment  (step 4 of 6)\n\n"
            "**Goal:** X/Y/Z position and pitch angle.\n\n"
            "**Motors:**\n"
            "- Cond X      —  32idbTXM:mcs2:c1:m10\n"
            "- Cond Y      —  32idbTXM:mcs2:c1:m2\n"
            "- Cond Z      —  32idbSoft:m6\n"
            "- Cond Pitch  —  32idbTXM:mcs2:c1:m1\n\n"
            "**Notes:**\n"
            "- Yaw is intentionally omitted — no hardware\n"
            "  (CONDENSER_YAW = \"x\" in txmOptics.substitutions).\n"
        ),
        "motors": [
            {"label": "Cond X",        "pv": "32idbTXM:mcs2:c1:m10"},  # CONDENSER_X
            {"label": "Cond Y",        "pv": "32idbTXM:mcs2:c1:m2"},   # CONDENSER_Y
            {"label": "Cond Z",        "pv": "32idbSoft:m6"},          # CONDENSER_Z
            {"label": "Cond Pitch",    "pv": "32idbTXM:mcs2:c1:m1"},   # CONDENSER_PITCH
            # CONDENSER_YAW = "x" in txmOptics.substitutions (no hardware)
        ],
    },
    "Pinhole": {
        "context": (
            "# Pinhole alignment  (step 5 of 6)\n\n"
            "**Goal:** X/Y position.\n\n"
            "**Motors:**\n"
            "- Pinhole X  —  32idbTXM:mcs2:c1:m4\n"
            "- Pinhole Y  —  32idbTXM:mcs2:c1:m5\n"
        ),
        "motors": [
            {"label": "Pinhole X",     "pv": "32idbTXM:mcs2:c1:m4"},   # PINHOLE_X
            {"label": "Pinhole Y",     "pv": "32idbTXM:mcs2:c1:m5"},   # PINHOLE_Y
        ],
    },
    "Beam Stop": {
        "context": (
            "# Beam stop alignment  (step 6 of 6)\n\n"
            "**Goal:** X/Y position.\n\n"
            "**Motors:**\n"
            "- Beamstop X  —  32idbTXM:mcs2:c1:m6\n"
            "- Beamstop Y  —  32idbTXM:mcs2:c1:m3\n"
        ),
        "motors": [
            {"label": "Beamstop X",    "pv": "32idbTXM:mcs2:c1:m6"},   # BEAMSTOP_X
            {"label": "Beamstop Y",    "pv": "32idbTXM:mcs2:c1:m3"},   # BEAMSTOP_Y
        ],
    },
    "Sample": {
        "context": (
            "# Sample alignment\n\n"
            "**Goal:** position the sample on top of the rotation axis\n"
            "and set the rotary stage angle. Distinct from the six\n"
            "optics-alignment tasks — do this before or between scans,\n"
            "not part of the systematic 1–6 procedure.\n\n"
            "**Motors:**\n"
            "- Sample Top X  —  32idbTXM:mcs:c2:m1  (TOP_X / SAMPLE_X)\n"
            "- Sample Top Z  —  32idbTXM:mcs:c2:m2  (TOP_Z / SAMPLE_Z)\n"
            "- Rotary        —  32idbTXM:ens:c1:m1  (ROTARY)\n\n"
            "**Notes:**\n"
            "- TOP_X and SAMPLE_X share the same PV — the top stage IS\n"
            "  the sample X in this configuration.\n"
            "- CoR / AlignPart plugins do this algorithmically; a\n"
            "  recording here is the manual/fallback procedure.\n"
        ),
        "motors": [
            {"label": "Sample Top X", "pv": "32idbTXM:mcs:c2:m1"},   # TOP_X / SAMPLE_X
            {"label": "Sample Top Z", "pv": "32idbTXM:mcs:c2:m2"},   # TOP_Z / SAMPLE_Z
            {"label": "Rotary",       "pv": "32idbTXM:ens:c1:m1"},   # ROTARY
        ],
    },
    "Final Joint Refinement": {
        "context": (
            "# Final joint refinement  (step 7 — after 1–6)\n\n"
            "**Goal:** fine-tune all 15 alignment axes together after\n"
            "each element has been dialed in individually.\n\n"
            "**When to run:** only after the six per-element steps\n"
            "produce a clean image. Small perturbations here should\n"
            "not shift the alignment far from the individually-tuned\n"
            "starting point.\n\n"
            "**Tips:**\n"
            "- Uncheck axes you don't want to touch this pass.\n"
            "- Consider recording separate sessions for coarse-vs-fine\n"
            "  refinement so replays can be picked per situation.\n"
        ),
        "motors": [
            # Everything that was touched individually — the full set.
            {"label": "Det Focus (Z)",  "pv": "32idbSoft:m1"},
            {"label": "Det Rotation",   "pv": "32idbTXM:nf:m2"},
            {"label": "ZP X",           "pv": "32idbTXM:mcs2:c1:m13"},
            {"label": "ZP Y",           "pv": "32idbTXM:mcs2:c1:m14"},
            {"label": "ZP Focus (Z)",   "pv": "32idbTXM:mcs2:c1:m15"},
            {"label": "Phase Ring X",   "pv": "32idbTXM:mcs2:c3:m1"},
            {"label": "Phase Ring Y",   "pv": "32idbTXM:mcs2:c3:m2"},
            {"label": "Cond X",         "pv": "32idbTXM:mcs2:c1:m10"},
            {"label": "Cond Y",         "pv": "32idbTXM:mcs2:c1:m2"},
            {"label": "Cond Z",         "pv": "32idbSoft:m6"},
            {"label": "Cond Pitch",     "pv": "32idbTXM:mcs2:c1:m1"},
            {"label": "Pinhole X",      "pv": "32idbTXM:mcs2:c1:m4"},
            {"label": "Pinhole Y",      "pv": "32idbTXM:mcs2:c1:m5"},
            {"label": "Beamstop X",     "pv": "32idbTXM:mcs2:c1:m6"},
            {"label": "Beamstop Y",     "pv": "32idbTXM:mcs2:c1:m3"},
        ],
    },
}


# ── ordered task list — determines dropdown order + workflow order

TASK_ORDER: List[str] = [
    "Detector",
    "Zone Plate",
    "Phase Ring",
    "Condenser",
    "Pinhole",
    "Beam Stop",
    "Sample",                  # off the 1–6 numbering; done per-scan
    "Final Joint Refinement",
]


def task_template_map() -> Dict[str, Dict[str, object]]:
    """Ordered dict of curated task templates consumed by pystream's
    Task Recorder. Order matches the beamline's alignment workflow
    (Detector → ... → Beam Stop → Sample → Final Joint Refinement).
    Each value is a dict with keys:
        "context": str — auto-filled into the dialog's Context editor
                   when the task is picked.
        "motors":  [{"label", "pv"}, ...] — checkboxes populated in
                   the dialog's motor list.
    """
    return {
        name: {
            "context": CURATED_TASKS[name].get("context", ""),
            "motors":  [dict(m) for m in CURATED_TASKS[name]["motors"]],
        }
        for name in TASK_ORDER if name in CURATED_TASKS
    }


# ── optional: raw bl_gui parser (kept for inspection / reference) ────

LAYOUT_FILENAME = "bl32id.json"


def _layout_path() -> str:
    """Locate the bundled bl32id.json inside bl_gui's install. Returns
    empty string if bl_gui not importable."""
    try:
        import bl_gui
    except ImportError:
        return ""
    root = os.path.dirname(bl_gui.__file__)
    p = os.path.join(root, "layouts", LAYOUT_FILENAME)
    return p if os.path.isfile(p) else ""


def bl_gui_task_template_map() -> Dict[str, List[Dict[str, str]]]:
    """Parse bl_gui's _mcs section verbatim. Useful for spotting motor
    PVs to cross-check against CURATED_TASKS above; not consumed by
    the recorder because bl_gui's panel names + labels are unreliable
    (Zone Plate panel had Beamstop PVs, Pinhole panel had ZP PVs, etc.).
    txmOptics.substitutions is the source of truth instead."""
    path = _layout_path()
    if not path:
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    mcs = data.get("_mcs")
    if not isinstance(mcs, dict):
        return {}

    result: Dict[str, List[Dict[str, str]]] = {}
    seen_pvs: Dict[str, set] = {}
    for key, entries in mcs.items():
        if not isinstance(entries, list):
            continue
        element = key.split("::", 1)[0].strip()
        if not element:
            continue
        bucket = result.setdefault(element, [])
        seen = seen_pvs.setdefault(element, set())
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pv = str(entry.get("pv", "")).strip()
            label = str(entry.get("label", "")).strip() or pv
            if not pv or pv in seen:
                continue
            seen.add(pv)
            bucket.append({"label": label, "pv": pv})
    return {name: motors for name, motors in result.items() if motors}
