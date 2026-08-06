#!/usr/bin/env python
"""
SAM 2 worker — runs in a heavy conda env (torch + sam2 + weights) and
gets called out-of-process by the light pystream env.

Contract (I/O is via files, so nothing has to be JSON-parseable across
env boundaries):

  argv[1] = path to input JSON file with keys:
              image_path  : path to a .npy file containing a 2D uint16 array
              point_x     : float, click x in image pixels
              point_y     : float, click y in image pixels
              model_type  : str  (e.g. "sam2_hiera_small")
              device      : str  ("cpu", "cuda", "cuda:0", "mps")
              checkpoint  : str or null (null = sam2 default)
              output_path : path where mask .npy should be written

  On success: exit 0, mask.npy written as a bool 2D array (H, W)
  On failure: exit non-zero, one-line error on stderr

This file has NO pystream imports — must run under an env that only has
torch/sam2 (not pystream / PyQt5 / etc.).
"""

import json
import os
import sys

import numpy as np


def _select_device(torch, device_str):
    if device_str == "cpu":
        return torch.device("cpu")
    if device_str.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but not available")
        return torch.device(device_str)
    if device_str == "mps":
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise RuntimeError("MPS requested but not available")
        return torch.device("mps")
    # Auto fall-through
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _to_uint8_rgb(image):
    """SAM2 wants uint8 (H, W, 3). Percentile-stretch a grayscale image
    into 0-255 and stack to 3 channels."""
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] == 3:
        return image.astype(np.uint8, copy=False) if image.dtype != np.uint8 \
            else image
    else:
        raise ValueError(f"Expected (H,W) or (H,W,3), got {image.shape}")

    if gray.dtype == np.uint8:
        pass
    else:
        f = gray.astype(np.float64)
        lo, hi = np.percentile(f, [1, 99])
        if hi > lo:
            gray = np.clip((f - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
        else:
            gray = np.zeros_like(gray, dtype=np.uint8)
    return np.stack([gray, gray, gray], axis=-1)


def main():
    if len(sys.argv) != 2:
        print("usage: _sam2_worker.py <request.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1]) as f:
        req = json.load(f)

    try:
        image = np.load(req["image_path"])
    except Exception as ex:
        print(f"failed to read image_path: {ex}", file=sys.stderr)
        return 3

    # Set CUDA_VISIBLE_DEVICES BEFORE importing torch so cuda=cpu really means cpu.
    if req.get("device", "cpu") == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    try:
        import torch  # noqa: F401
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except Exception as ex:
        print(f"missing torch or sam2: {ex}", file=sys.stderr)
        return 4

    model_type = req.get("model_type", "sam2_hiera_small")
    config_map = {
        "sam2_hiera_tiny":       "sam2_hiera_t.yaml",
        "sam2_hiera_small":      "sam2_hiera_s.yaml",
        "sam2_hiera_base_plus":  "sam2_hiera_b+.yaml",
        "sam2_hiera_large":      "sam2_hiera_l.yaml",
    }
    if model_type not in config_map:
        print(f"unknown model_type: {model_type}", file=sys.stderr)
        return 5

    device = _select_device(torch, req.get("device", "cpu"))
    try:
        sam2_model = build_sam2(
            config_file=config_map[model_type],
            ckpt_path=req.get("checkpoint"),   # None = sam2 default
            device=device,
        )
        predictor = SAM2ImagePredictor(sam2_model)
    except Exception as ex:
        print(f"model load failed: {ex}", file=sys.stderr)
        return 6

    try:
        rgb = _to_uint8_rgb(image)
        predictor.set_image(rgb)
        point_coords = np.array([[req["point_x"], req["point_y"]]], dtype=np.float32)
        point_labels = np.array([1], dtype=np.int64)   # 1 = foreground
        masks, scores, _ = predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=True,
        )
    except Exception as ex:
        print(f"predict failed: {ex}", file=sys.stderr)
        return 7

    masks = np.asarray(masks)
    scores = np.asarray(scores)
    if masks.ndim == 2:
        masks = masks[None, ...]
    best = int(np.argmax(scores))
    mask = masks[best].astype(bool)

    try:
        np.save(req["output_path"], mask)
    except Exception as ex:
        print(f"failed to write output_path: {ex}", file=sys.stderr)
        return 8

    return 0


if __name__ == "__main__":
    sys.exit(main())
