# Mosalign Test Script

Quick offline testing for the mosalign plugin without hardware.

## Usage

From project root:
```bash
python test/test_mosalign.py
```

From test directory:
```bash
cd test
python test_mosalign.py
```

## What It Does

- Launches mosalign with **Test Mode** automatically enabled
- Pre-configures a 2x2 grid for quick testing
- Shows instructions in the log window
- All PV/motor/tomoscan operations are mocked

## Testing Workflow

1. **Basic Test**: Click "Start Scan" to test stitching
2. **Tomoscan Test**: Enable "Run tomoscan at each position" checkbox, then start scan
3. **Watch**: See the stitched mosaic build up in real-time
4. **Verify**: Check log for `[MOCK]` messages

## What to Test

- ✅ Stitched preview builds correctly
- ✅ Position-dependent image patterns
- ✅ Progress bar updates
- ✅ Log messages are clear
- ✅ Tomoscan integration (if enabled)
- ✅ First projection placement
- ✅ Motor position handling

## Configuration

Edit [test_mosalign.py](test_mosalign.py) to change:
- Grid size: `dialog.x_step_size.setValue(2)`
- Settle time: `dialog.settle_time.setValue(0.5)`
- Other parameters as needed

## Full Documentation

See [../TESTING_MOSALIGN.md](../TESTING_MOSALIGN.md) for complete testing guide.
