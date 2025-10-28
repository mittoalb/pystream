# Sphinx configuration

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
html_logo = "_static/logo_gray.png"


myst_enable_extensions = ["colon_fence", "deflist"]

# -- Options for Texinfo output -------------------------------------------
# http://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#confval-autodoc_mock_imports

autodoc_mock_imports = [
    'argparse',
    'dataclasses',
    'importlib',
    'json',
    'logging',
    'math',
    'numpy',
    'pvaccess',
    'pyqtgraph',
    'PyQt5',
    'queue',
    'scipy',
    'subprocess',
    'tempfile',
    'threading',
    'time',
    'tkinter',
    'traceback',
    'typing',
]
