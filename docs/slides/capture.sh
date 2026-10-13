#!/usr/bin/env bash
# capture.sh
#
# Screenshot GUI windows by title regex, dump PNG into img/screenshots/.
# Run from the slides/ directory. Needs ImageMagick's `import` and
# `wmctrl` on PATH (both already present on this machine).
#
# Usage:
#   ./capture.sh <window-title-regex> <output-name>
#   ./capture.sh --all        # take every shot the slides reference
#
# Examples:
#   ./capture.sh 'pystream' pystream-main.png
#   ./capture.sh 'Detector Control' pystream-detector.png
#
# Behaviour:
#   * Picks the first window whose title matches the regex (case-insensitive).
#   * Raises & focuses the window first so decorations are drawn correctly.
#   * Waits 300 ms before grabbing (lets Qt redraw the raise).
#   * Dumps PNG into img/screenshots/<output-name>.
#
# Supported window titles for `--all`:
#   see the TITLES array below. Comment out any you don't currently
#   have running; the script skips missing windows with a warning.

set -euo pipefail

OUT_DIR="$(dirname "$0")/img/screenshots"
mkdir -p "$OUT_DIR"

shot_one() {
    local pattern="$1"
    local outname="$2"
    local wid
    wid="$(wmctrl -l | grep -iE "$pattern" | head -n1 | awk '{print $1}' || true)"
    if [[ -z "$wid" ]]; then
        echo "[capture] no window matching /$pattern/" >&2
        return 1
    fi
    wmctrl -ia "$wid"
    sleep 0.3
    import -window "$wid" "$OUT_DIR/$outname"
    echo "[capture] $outname  <-  $(wmctrl -l | awk -v w="$wid" '$1==w {for(i=4;i<=NF;++i) printf "%s ",$i; print ""}')"
}

# TITLES: each row is "<regex>|<output filename>". Edit as needed.
TITLES=(
    'pystream$|pystream-main.png'
    'Detector Control|pystream-detector.png'
    'QGMax|pystream-qgmax.png'
    'AutoCenter|pystream-autocenter.png'
    'Center of Rotation|pystream-cor.png'
    'DataMap|pystream-datamap.png'
    'bl32id|bl_gui-main.png'
    'XANES|xanes_gui-main.png'
    'XANES 2D|xanes_gui-2d.png'
    'detectors.*cam1|detectors-gui.png'
)

if [[ "${1-}" == "--all" ]]; then
    for row in "${TITLES[@]}"; do
        pattern="${row%%|*}"
        name="${row##*|}"
        shot_one "$pattern" "$name" || true
    done
    exit 0
fi

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <window-title-regex> <output-name>" >&2
    echo "       $0 --all" >&2
    exit 2
fi

shot_one "$1" "$2"
