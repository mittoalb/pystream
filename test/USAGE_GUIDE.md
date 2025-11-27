# Mosalign Test Mode - Simple Guide

## What is Test Mode?

Test mode lets you run mosalign **without any hardware** - no PVs, no motors, no tomoscan.

## Two Ways to Use It

### Method 1: Run the test script (Recommended for testing)
```bash
python test/test_mosalign.py
```

**What happens:**
- Opens mosalign window
- Test Mode checkbox is **already checked** ✓
- Settings are pre-configured (2x2 grid, fast)
- Instructions appear in the log window
- Just click "Start Scan" to see it work!

### Method 2: Run mosalign normally (For real use)
```bash
mosalign
```

**What happens:**
- Opens mosalign window
- Test Mode checkbox is **unchecked** (real mode)
- You configure all settings yourself
- To test offline: **manually check** "Test Mode (Mock PVs/Tomoscan)" checkbox

---

## The Test Mode Checkbox

When you check **"Test Mode (Mock PVs/Tomoscan)"**:

| Feature | Real Mode (unchecked) | Test Mode (checked) |
|---------|---------------------|-------------------|
| Motor movements | Sends real caput commands | Just logs them |
| Images | From real camera PV | Generated fake images |
| Tomoscan | Runs actual tomoscan | Simulates with 0.5s delay |
| Settle time | Uses your setting | Fast (0.1s) |
| Connection | Needs real PVs | Works offline |

---

## Quick Test Instructions

1. Run: `python test/test_mosalign.py`
2. You'll see a window with TWO panels:
   - **Left**: Controls and settings
   - **Right**: Live preview (top) + Log (bottom)
3. The log shows instructions
4. Click **"Start Scan"** button
5. Watch the stitched mosaic build in the preview!

### To test tomoscan integration:
1. After opening, check **"Run tomoscan at each position"**
2. Click **"Start Scan"**
3. Watch: preview image → tomoscan runs → different image appears

---

## Small Screen Tips

If the window is too big:

**Option 1:** The test script now uses 1000x700 (smaller)

**Option 2:** Manually resize the window by dragging corners

**Option 3:** Edit the test script to make it even smaller:
```python
dialog.resize(800, 600)  # Even smaller
```

---

## What You Should See

### Live Preview (top right)
- A stitched mosaic appearing tile by tile
- Each tile has a slightly different pattern
- White borders around each tile

### Log Window (bottom right)
- `[MOCK]` messages for motor movements
- Position updates
- Image capture messages
- Progress updates

### Progress Bar (bottom left)
- Shows how many positions completed

---

## Still Confused?

The test script does **nothing special** - it just:
1. Opens the same mosalign window
2. Checks the test mode checkbox for you
3. Sets small values for quick testing
4. Adds helpful messages to the log

You can do all of this manually too!
