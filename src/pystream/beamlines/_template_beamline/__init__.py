"""
Template Beamline Plugin Package

This is a template for creating your own beamline plugins.

To use this template:
1. Copy this folder to a new name (e.g., cp -r _template_beamline my_beamline)
2. Rename and customize the example plugin
3. Update the imports and __all__ list below
4. Set ACTIVE_BEAMLINE = 'my_beamline' in beamline_config.py
"""

from .example_plugin import ExamplePluginDialog

__all__ = ['ExamplePluginDialog']
