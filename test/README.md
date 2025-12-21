# PyStream Test Image Generators

This folder contains test scripts to generate synthetic images and publish them to EPICS PVs for testing pystream.

## Scripts

### `generate_test_images.py`
Full-featured image generator with multiple patterns using pvaPy.

**Requirements:**
- pvaccess (pvapy)
- numpy

**Usage:**
```bash
# Random noise at 10 FPS
python generate_test_images.py --pv TEST:image --fps 10

# Moving gradient at 30 FPS
python generate_test_images.py --pv TEST:image --fps 30 --pattern gradient

# Concentric circles at 5 FPS
python generate_test_images.py --pv TEST:image --fps 5 --pattern circles

# Moving dot at 15 FPS
python generate_test_images.py --pv TEST:image --fps 15 --pattern moving_dot

# Sine wave pattern at 20 FPS
python generate_test_images.py --pv TEST:image --fps 20 --pattern sine_wave

# Custom resolution
python generate_test_images.py --pv TEST:image --width 1024 --height 768

# Run for limited duration (60 seconds)
python generate_test_images.py --pv TEST:image --fps 10 --duration 60
```

**Available Patterns:**
- `noise`: Random noise (default)
- `gradient`: Horizontal gradient with animation
- `circles`: Concentric circles
- `moving_dot`: Single bright dot moving in a circle
- `sine_wave`: Animated 2D sine wave pattern

### View the Test Images

In another terminal, start pystream to view the test images:

```bash
pystream --pv TEST:image
```

## Testing Scenarios

### Test Recording Performance
```bash
# Generate fast images (50 FPS) to test buffering
python generate_test_images.py --pv TEST:image --fps 50 --pattern noise

# Then in pystream: use Record button to test RAM buffering
```

### Test Frame Rate Display
```bash
# Variable frame rates
python generate_test_images.py --pv TEST:image --fps 1   # Slow
python generate_test_images.py --pv TEST:image --fps 10  # Medium
python generate_test_images.py --pv TEST:image --fps 60  # Fast
```

### Test Plugin Performance
```bash
# Use patterns to test plugins
python generate_test_images.py --pv TEST:image --fps 10 --pattern moving_dot
# Good for testing ROI, line profiles, etc.
```

## Troubleshooting

**PV not updating:**
- Check that the PV name matches in both scripts
- Ensure pvaPy is installed: `pip install pvapy`
- Check network/firewall settings

**Frame rate too low:**
- Your system might not support the requested FPS
- Try reducing resolution or FPS
- Check actual FPS in the script output

**High CPU usage:**
- Normal for high frame rates
- Reduce FPS or resolution
- Use simpler patterns (noise is fastest)
