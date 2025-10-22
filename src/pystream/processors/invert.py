import numpy as np

def process(img, meta=None):
    if meta is None:
        meta = {}

    # Convert to float for safe inversion
    img_f = img.astype(np.float32, copy=False)
    lo = np.nanmin(img_f)
    hi = np.nanmax(img_f)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return img

    out = hi - (img_f - lo)  # invert around mid range
    if np.issubdtype(img.dtype, np.integer):
        out = np.clip(out, lo, hi).astype(img.dtype, copy=False)
    else:
        out = out.astype(img.dtype, copy=False)

    meta["inverted"] = True
    return out*0.0, meta
