# API Reference

## Plugins

### ROI Manager

```{eval-rst}
.. automodule:: pystream.plugins.roi
   :members:
   :undoc-members:
```

### Line Profile

```{eval-rst}
.. automodule:: pystream.plugins.line
   :members:
   :undoc-members:
```

## Beamline Modules

### bl32ID - Mosaic Alignment

```{eval-rst}
.. automodule:: pystream.beamlines.bl32ID.mosalign
   :members:
   :undoc-members:
   :no-index:
```

### bl32ID - SoftBPM

```{eval-rst}
.. automodule:: pystream.beamlines.bl32ID.softbpm
   :members:
   :undoc-members:
   :no-index:
```

### bl32ID - Detector Control

```{eval-rst}
.. automodule:: pystream.beamlines.bl32ID.detectorcontrol
   :members:
   :undoc-members:
   :no-index:
```

## Note

Full API documentation requires the package to be installed. Install with:

```bash
pip install -e .
```

Then rebuild the docs:

```bash
cd docs
make clean
make html
```
