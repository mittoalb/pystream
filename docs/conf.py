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
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']
html_logo = "./_static/logo_gray.png"


myst_enable_extensions = ["colon_fence", "deflist"]

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
    'tkinter',
    'typing',
]
