"""
Scaffold a new beamline package under `pystream/beamlines/<name>/`.

Creates the directory and an `__init__.py` with an empty plugin list,
so pystream sees the beamline (empty toolbar) with zero hand-editing.
Prints the pyproject.toml snippet you need to add to
`[project.optional-dependencies]` so `pip install ".[<name>]"` works.

Run:
    pystream-new-beamline bl19BM
    pystream-new-beamline BL7BM --description "APS 7-BM tomography"
    pystream-new-beamline bl22ID --overwrite   # replace an existing scaffold
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


_INIT_TEMPLATE = '''"""{name} beamline plugins.{description_block}

Empty scaffold — no plugins registered yet. Add one by:

    1. Create `plugin_name.py` in this folder with a class:
           class MyPluginDialog(QtWidgets.QDialog):
               BUTTON_TEXT  = "MyPlugin"
               GROUP        = "Alignment"      # or "Scans", "Tools", ...
               HANDLER_TYPE = 'singleton'      # or 'launcher' / 'multi-instance'
               def __init__(self, parent=None, logger=None): ...
    2. Import + add to __all__ below.

pystream's toolbar builder discovers plugins by iterating this module's
`__all__` and grouping by each class's `GROUP` attribute.

Select this beamline via ~/.pystream/beamline_config (or beamline_config.py
at the pystream package root) — see the bl32ID package for a fully-wired
reference.
"""

__all__: list[str] = []


def start_background_services(parent_window):
    """Hook for long-running watchers that should be active regardless of
    whether the user has opened the corresponding dialog. No services yet
    for {name}."""
    pass
'''


def _find_beamlines_root() -> Path:
    """Locate `src/pystream/beamlines/` starting from this script's install
    location. Works both for editable installs (walks up the source tree)
    and copy installs (finds the installed pystream/beamlines dir)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "beamlines"
        if cand.is_dir() and (cand / "bl32ID").is_dir():
            return cand
    raise RuntimeError(
        f"could not locate pystream/beamlines/ starting from {here}")


def _validate_name(name: str) -> str:
    """Basic sanity: must be a valid Python identifier so `import
    pystream.beamlines.<name>` works. `bl19BM`, `BL7bm`, `beamline_x`
    all fine. Reject empty, or names starting with a digit, or names
    containing spaces / dots."""
    n = name.strip()
    if not n:
        raise ValueError("beamline name is empty")
    if not n.isidentifier():
        raise ValueError(
            f"'{n}' is not a valid Python identifier "
            f"(letters/digits/underscore only, cannot start with a digit)")
    return n


def scaffold(name: str, *, description: str = "",
             overwrite: bool = False, dry_run: bool = False) -> Path:
    """Create the beamline package on disk. Returns the created dir path."""
    beamlines_root = _find_beamlines_root()
    pkg_dir = beamlines_root / name
    init_path = pkg_dir / "__init__.py"

    if init_path.exists() and not overwrite:
        raise FileExistsError(
            f"{init_path} already exists (use --overwrite to replace)")

    desc_block = f"\n\n{description}" if description else ""
    content = _INIT_TEMPLATE.format(name=name, description_block=desc_block)

    if dry_run:
        print(f"[dry-run] would create {init_path}")
        print(f"[dry-run] contents ({len(content)} chars):")
        print(content)
        return pkg_dir

    pkg_dir.mkdir(parents=True, exist_ok=True)
    init_path.write_text(content, encoding="utf-8")
    return pkg_dir


def _print_next_steps(name: str, pkg_dir: Path):
    print()
    print(f"✓ created {pkg_dir}")
    print()
    print("Next steps:")
    print()
    print(f"  1. (optional) declare a pip extra so `pip install \".[{name}]\"`")
    print("     succeeds. Add to pyproject.toml under")
    print("     [project.optional-dependencies]:")
    print()
    print(f'        {name} = [')
    print("          # No external deps yet.")
    print("        ]")
    print()
    print("  2. To make it the ACTIVE beamline in pystream, edit")
    print("     src/pystream/beamline_config.py and set:")
    print(f"        ACTIVE_BEAMLINE = '{name}'")
    print()
    print("  3. Restart pystream. Toolbar shows the new beamline with an")
    print("     empty menu (no plugins yet). Drop plugin files into")
    print(f"     the {name}/ folder and register them in __init__.py.")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog='pystream-new-beamline',
        description="Scaffold a new beamline package under pystream/beamlines/.",
    )
    p.add_argument('name', help="Beamline name, e.g. 'bl19BM'. Must be a "
                                "valid Python identifier.")
    p.add_argument('--description', default="",
                   help="One-line description put in the module docstring.")
    p.add_argument('--overwrite', action='store_true',
                   help="Replace an existing __init__.py.")
    p.add_argument('--dry-run', action='store_true',
                   help="Print what would be created; don't write anything.")
    args = p.parse_args(argv)

    try:
        name = _validate_name(args.name)
    except ValueError as ex:
        p.error(str(ex))
        return 2

    try:
        pkg_dir = scaffold(name,
                           description=args.description,
                           overwrite=args.overwrite,
                           dry_run=args.dry_run)
    except FileExistsError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    except Exception as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1

    if not args.dry_run:
        _print_next_steps(name, pkg_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
