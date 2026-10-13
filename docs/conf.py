# Sphinx configuration
# Sphinx configuration
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join("..", "src")))

project = 'PyStream'
copyright = '2025'
author = 'Alberto Mittone'
release = '0.1.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'myst_parser',
    'sphinxcontrib.mermaid',
]

# Mermaid: render client-side via CDN JS (same path as the RTD theme's
# own JS). Use the "default" theme for light/dark readability.
mermaid_version = "10.9.1"
mermaid_init_js = "mermaid.initialize({startOnLoad:true,theme:'default',securityLevel:'loose'});"

# Build-noise control.
#
#   myst.xref_missing — stale {doc}/{ref} target in a page we aren't
#       touching now (ai_backends.md:87 → beamlines/bl32ID anchor).
#       Shown as info, not failure.
#   misc.highlighting_failure — Pygments trips on placeholder syntax
#       like `<ID>` in a TOML fence and `…` ellipses inside JSON /
#       Python fences. These are illustrative snippets, not runnable
#       code; the "relaxed mode" fallback already renders them
#       sensibly.
suppress_warnings = [
    "myst.xref_missing",
    "misc.highlighting_failure",
    # autodoc complains "A mocked object is detected" when it reaches
    # a beamline submodule whose transitive imports we've mocked
    # (PyQt5, pvapy, etc). The mocking is intentional — these would
    # otherwise fail to import at docs-build time without hardware
    # SDKs. The warning is noise, not a build problem.
    "autodoc",
]
nitpicky = False

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']
html_logo = "./_static/logo_gray.png"


myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# -- Options for Texinfo output -------------------------------------------
# http://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#confval-autodoc_mock_imports

autodoc_mock_imports = [
    'argparse',
    'cv2',
    'h5py',
    'importlib',
    'json',
    'logging',
    'math',
    'numpy',
    'os',
    'pvaccess',
    'pvapy',
    'pyqtgraph',
    'queue',
    'subprocess',
    'sys',
    'tempfile',
    'threading',
    'time',
    'tkinter',
    'traceback',
    'types',
    'dataclasses',
    'PyQt5',
    'typing',
    'epics',
    'pystream.beamlines.bl32ID',
]
