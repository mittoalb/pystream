"""
Beamline Configuration for PyStream

This file allows users to configure which beamline plugins to load.
Set ACTIVE_BEAMLINE to your beamline name, or None to disable beamline plugins.

Available beamlines:
- 'bl32ID': Beamline 32-ID plugins (SoftBPM, Detector Control, etc.)
- None: No beamline plugins loaded

To add a new beamline:
1. Create a folder in src/pystream/beamlines/<your_beamline>
2. Add your plugin dialogs to that folder
3. Create an __init__.py that exports your dialog classes
4. Set ACTIVE_BEAMLINE = '<your_beamline>' below
"""

# Set this to your beamline name, or None to disable
ACTIVE_BEAMLINE = 'bl32ID'

# Optional: Customize which plugins to load from the active beamline
# If None, all available plugins will be loaded
# Example: ENABLED_PLUGINS = ['SoftBPMDialog', 'DetectorControlDialog']
ENABLED_PLUGINS = None
