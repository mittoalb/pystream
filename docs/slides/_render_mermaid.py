"""Pre-render ``` mermaid blocks in a markdown deck to SVG files.

Marp doesn't understand mermaid; running mermaid in-browser is fragile
(CDN cache, module-script timing, Marp's own JS). We render every
mermaid block to a standalone SVG at build time via `mmdc` (mermaid
CLI) and rewrite the markdown to reference each SVG as an image.
After this step Marp renders a normal markdown with images.

Usage:
    python _render_mermaid.py <input.md> <output.md> <img_dir>
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys


MERMAID_FENCE = re.compile(
    r"^```mermaid\s*\n(?P<body>.*?)\n```\s*$",
    re.MULTILINE | re.DOTALL,
)


def _render(src: str, img_dir: pathlib.Path, ref_prefix: str) -> str:
    """Return the markdown with every mermaid fence replaced by an
    `![](...)` reference to a freshly-rendered SVG.

    `ref_prefix` is the directory the HTML output will reference the
    SVG by, relative to where the HTML lands. For slides rendered by
    marp from `_build/.processed/<deck>.md` into `_build/<deck>.html`,
    with SVGs stored at `_build/img/`, the correct prefix is `img/`.
    """
    img_dir.mkdir(parents=True, exist_ok=True)

    def replace(match: re.Match) -> str:
        body = match.group("body")
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
        svg_name = f"mermaid-{digest}.svg"
        svg_path = img_dir / svg_name
        if not svg_path.exists():
            tmp = img_dir / f".tmp-{digest}.mmd"
            tmp.write_text(body + "\n")
            try:
                subprocess.run(
                    [
                        "npx", "--yes",
                        "-p", "@mermaid-js/mermaid-cli",
                        "mmdc",
                        "-i", str(tmp),
                        "-o", str(svg_path),
                        "-b", "transparent",
                        "-s", "2",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"[mermaid] render failed:\n{e.stderr}", file=sys.stderr)
                raise
            finally:
                tmp.unlink(missing_ok=True)
        return f"![mermaid]({ref_prefix}{svg_name})"

    return MERMAID_FENCE.sub(replace, src)


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print("usage: _render_mermaid.py <input.md> <output.md> <img_dir> "
              "[ref_prefix (default img/)]", file=sys.stderr)
        return 2
    inp, outp, imgs = map(pathlib.Path, sys.argv[1:4])
    ref_prefix = sys.argv[4] if len(sys.argv) == 5 else "img/"
    src = inp.read_text()
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(_render(src, imgs, ref_prefix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
