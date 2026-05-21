# Python Console

Runs a user-defined `process(img)` function on every frame before
visualization. `numpy` (as `np`), and `scipy`, `cv2`, `skimage` when
installed, are pre-imported.

## Usage

Write a function with the signature:

```python
def process(img):
    return img      # numpy array in, numpy array out
```

Click **Execute (Compile)** to compile and test, then check **Enable**
to apply it to the live stream. A runtime error disables processing
automatically. Globals persist between frames, so you can build stateful
filters (running averages, captured backgrounds, etc.). **Save…** /
**Load…** persist the code to a `.py` file.

## Adding a built-in import

The list of pre-imported modules is defined where the execution
namespace is built in
[src/pystream/plugins/console.py](../../src/pystream/plugins/console.py).
Add the module (wrapped in `try/except ImportError` if optional) to that
namespace and it becomes available to user code.
