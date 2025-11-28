# Python Console Plugin

Interactive Python console for real-time image stream processing with custom user-defined functions.

## Overview

The Python Console plugin provides:
- **Code editor** for writing custom processing functions
- **Real-time execution** on image stream before visualization
- **Built-in libraries** (numpy, scipy, cv2, scikit-image)
- **Live error feedback** and function testing
- **Dark theme editor** with syntax support

## Features

### Code Editor
- Full Python code editor with monospace font
- Dark theme optimized for coding
- Multi-line editing with proper indentation
- Default template with examples

### Function Execution
- **Execute button**: Compile and test your function
- **Enable checkbox**: Toggle real-time processing on/off
- **Automatic validation**: Tests function with dummy data before activation
- **Error handling**: Runtime errors disable processing automatically

### Built-in Imports
The console automatically imports commonly used libraries:
- `numpy` (as `np`)
- `scipy` (if installed)
- `cv2` (OpenCV, if installed)
- `skimage` (scikit-image, if installed)

### Status Display
- Real-time logging with timestamps
- Color-coded messages (green = success, red = error)
- Compilation and runtime error reporting
- Auto-scrolling output

## Usage

### Basic Workflow

1. Open the Python Console dialog
2. Write a `process(img)` function in the editor
3. Click **"Execute (Compile)"** to compile and test
4. Check **"Enable"** to activate real-time processing
5. Your function runs on every frame before visualization

### Function Signature

Your processing function must follow this signature:

```python
def process(img):
    """
    Process incoming image frame.

    Args:
        img: numpy array (2D grayscale or 3D RGB)

    Returns:
        processed numpy array (same or different shape/dtype)
    """
    # Your processing code here
    return processed_img
```

### Example Functions

#### Gaussian Blur
```python
def process(img):
    """Apply Gaussian blur for noise reduction"""
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(img, sigma=2.0)
```

#### Median Filter
```python
def process(img):
    """Remove salt-and-pepper noise"""
    from scipy.ndimage import median_filter
    return median_filter(img, size=3)
```

#### Edge Detection (Sobel)
```python
def process(img):
    """Detect edges using Sobel operator"""
    from scipy.ndimage import sobel
    sx = sobel(img, axis=0)
    sy = sobel(img, axis=1)
    return np.hypot(sx, sy)
```

#### Simple Threshold
```python
def process(img):
    """Binary threshold at mean intensity"""
    threshold = img.mean()
    return np.where(img > threshold, img, 0)
```

#### Background Subtraction
```python
# Global variable for background reference
background = None

def process(img):
    """Subtract background (capture first frame as reference)"""
    global background

    if background is None:
        background = img.copy()
        return img

    # Subtract and clip to valid range
    result = img.astype(np.float32) - background.astype(np.float32)
    result = np.clip(result, 0, None)

    return result.astype(img.dtype)
```

#### Contrast Enhancement
```python
def process(img):
    """Enhance contrast using histogram equalization"""
    # Normalize to 0-1
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-8)

    # Clip extreme values (percentile stretch)
    p2, p98 = np.percentile(img_norm, [2, 98])
    img_clipped = np.clip(img_norm, p2, p98)

    # Rescale to original range
    result = (img_clipped - img_clipped.min()) / (img_clipped.max() - img_clipped.min() + 1e-8)
    result = result * (img.max() - img.min()) + img.min()

    return result.astype(img.dtype)
```

#### OpenCV Canny Edge Detection
```python
def process(img):
    """Canny edge detection using OpenCV"""
    import cv2

    # Convert to uint8 if needed
    if img.dtype != np.uint8:
        img_norm = ((img - img.min()) / (img.max() - img.min() + 1e-8) * 255)
        img_u8 = img_norm.astype(np.uint8)
    else:
        img_u8 = img

    # Apply Canny edge detection
    edges = cv2.Canny(img_u8, threshold1=50, threshold2=150)

    return edges
```

#### Morphological Operations
```python
def process(img):
    """Morphological opening (erosion then dilation)"""
    from scipy.ndimage import binary_erosion, binary_dilation

    # Create binary mask
    threshold = img.mean()
    binary = img > threshold

    # Morphological opening
    eroded = binary_erosion(binary, iterations=2)
    opened = binary_dilation(eroded, iterations=2)

    # Apply mask to original image
    return img * opened
```

## Python API

```python
from pystream.plugins.console import ConsoleDialog
from PyQt5 import QtWidgets

# Create console dialog
console_dialog = ConsoleDialog(logger=logger)

# Show the dialog (non-modal)
console_dialog.show()

# Process an image through the console
import numpy as np
image = np.random.rand(512, 512)
processed = console_dialog.process_image(image)

# Access the console widget directly
console_widget = console_dialog.console

# Check if processing is enabled
is_enabled = console_widget.enabled

# Programmatically set code
custom_code = """
def process(img):
    return img * 2.0
"""
console_widget.code_editor.setPlainText(custom_code)

# Execute the code
console_widget._execute_code()

# Enable processing
console_widget.chk_enable.setChecked(True)
```

## Advanced Usage

### Stateful Processing

You can maintain state between frames using global variables:

```python
# Initialize state
frame_count = 0
running_average = None

def process(img):
    """Compute running average over frames"""
    global frame_count, running_average

    frame_count += 1

    if running_average is None:
        running_average = img.astype(np.float32)
    else:
        # Exponential moving average (alpha = 0.1)
        alpha = 0.1
        running_average = alpha * img + (1 - alpha) * running_average

    return running_average.astype(img.dtype)
```

### Multi-step Processing Pipeline

```python
def process(img):
    """Multi-step processing pipeline"""
    from scipy.ndimage import gaussian_filter, median_filter

    # Step 1: Denoise with median filter
    denoised = median_filter(img, size=3)

    # Step 2: Smooth with Gaussian
    smoothed = gaussian_filter(denoised, sigma=1.5)

    # Step 3: Enhance contrast
    p2, p98 = np.percentile(smoothed, [2, 98])
    clipped = np.clip(smoothed, p2, p98)
    enhanced = (clipped - p2) / (p98 - p2 + 1e-8)

    # Step 4: Convert back to original dtype
    result = enhanced * (img.max() - img.min()) + img.min()

    return result.astype(img.dtype)
```

### Conditional Processing

```python
def process(img):
    """Apply different processing based on image statistics"""
    mean_intensity = img.mean()

    if mean_intensity < 100:
        # Dark image - enhance brightness
        return img * 2.0
    elif mean_intensity > 200:
        # Bright image - reduce brightness
        return img * 0.5
    else:
        # Normal image - apply moderate enhancement
        from scipy.ndimage import gaussian_filter
        return gaussian_filter(img, sigma=1.0)
```

## Error Handling

### Compilation Errors

If your code has syntax errors, they will be displayed in the status window:

```
⚠ COMPILATION ERROR:
SyntaxError: invalid syntax (line 5)
```

Fix the syntax and click **"Execute"** again.

### Runtime Errors

If your function crashes during execution, processing is automatically disabled:

```
⚠ RUNTIME ERROR: division by zero
Real-time processing DISABLED
```

Review your code, fix the issue, and re-execute.

### Validation Errors

The console validates your function:
- **Missing function**: Must define a `process` function
- **Wrong return type**: Must return a numpy array
- **Test failure**: Function must work on test data

## Best Practices

1. **Test incrementally**: Start with simple operations, then add complexity
2. **Use try-except**: Handle edge cases in your function
3. **Check data types**: Ensure output dtype matches expectations
4. **Profile performance**: Complex operations may slow down real-time display
5. **Use numpy operations**: Vectorized operations are much faster than loops
6. **Avoid I/O**: Don't save files or print in the processing function
7. **Reset state**: Use the "Clear" button to reset global variables

## Performance Tips

### Fast Operations (Real-time capable)
- Numpy array operations (add, multiply, clip, etc.)
- Simple filters (median 3×3, Gaussian σ<3)
- Thresholding and masking
- Basic morphology (small kernels)

### Slow Operations (May cause frame drops)
- Large filters (median >5×5, Gaussian σ>5)
- FFT operations on large images
- Complex morphology (many iterations)
- Machine learning inference
- Multiple nested loops

### Optimization Example

```python
# SLOW - Python loops
def process(img):
    result = np.zeros_like(img)
    for i in range(img.shape[0]):
        for j in range(img.shape[1]):
            result[i, j] = img[i, j] * 2.0
    return result

# FAST - Vectorized numpy
def process(img):
    return img * 2.0
```

## Saving and Loading Code

### Save Processing Functions

Click **"Save..."** to save your processing function to a `.py` file:
- Automatically adds `.py` extension if not provided
- Saves entire editor contents
- Use for backing up complex functions
- Share functions with colleagues

### Load Processing Functions

Click **"Load..."** to load a previously saved processing function:
- Opens file dialog to select `.py` file
- Replaces current editor contents
- Preserves function history by saving first
- Click **"Execute"** after loading to activate

### Example: Creating a Function Library

```bash
# Save different processing functions
my_blur_filter.py
my_edge_detector.py
my_background_subtract.py

# Load when needed
# Click "Load..." → select my_blur_filter.py → "Execute" → "Enable"
```

## Buttons and Controls

| Control | Function |
|---------|----------|
| **Enable** checkbox | Toggle real-time processing on/off |
| **Execute (Compile)** | Compile code and test function |
| **Reset to Default** | Load default template with examples |
| **Clear** | Clear function and disable processing |
| **Load...** | Load Python code from a .py file |
| **Save...** | Save Python code to a .py file |

## Status Messages

| Message | Meaning |
|---------|---------|
| `Console ready` | Console initialized, waiting for code |
| `✓ Function compiled successfully` | Code compiled and tested OK |
| `✓ Real-time processing ENABLED` | Function is running on every frame |
| `Real-time processing DISABLED` | Function not running |
| `⚠ No 'process' function found` | Missing required function definition |
| `⚠ Function returned non-array` | Return type error |
| `⚠ RUNTIME ERROR: ...` | Exception during execution |

## Technical Notes

- **Execution context**: Code runs in isolated namespace with pre-imported libraries
- **Performance**: Function called on every frame - optimize for speed
- **Thread safety**: Processing happens in the main GUI thread
- **Memory**: Global variables persist across frames
- **Security**: eval/exec used - only run trusted code
- **Compatibility**: Works with grayscale and RGB images

## Use Cases

### Quality Control
- Real-time defect detection
- Automated inspection
- Threshold monitoring

### Scientific Imaging
- Background subtraction
- Flat-field correction
- Signal enhancement

### Image Processing Research
- Algorithm prototyping
- Filter comparison
- Parameter tuning

### Education
- Learn image processing
- Test algorithms interactively
- Visualize filter effects

## Troubleshooting

### "No 'process' function found"
- Ensure you define `def process(img):`
- Check for typos in function name

### "Function returned non-array"
- Your function must return a numpy array
- Use `return img` at minimum

### Function works but produces wrong results
- Print intermediate values to debug
- Check data type conversions
- Verify array dimensions

### Processing too slow
- Simplify your algorithm
- Use smaller filter kernels
- Avoid loops, use vectorized operations
- Disable processing temporarily with checkbox
