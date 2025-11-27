# Testing Mosalign Offline

The mosalign plugin now includes a **Test Mode** that allows you to test all functionality offline without requiring:
- Real EPICS PVs
- Camera connections
- Motor hardware
- Tomoscan installation

## Quick Start

### Option 1: Using the test script

```bash
cd /Users/amittone/Software/pystream
python test/test_mosalign.py
```

This will launch mosalign with test mode automatically enabled and pre-configured parameters.

### Option 2: Manual testing

```bash
# Launch mosalign normally
mosalign

# Or from pystream
pystream --pv dummy:pv  # The PV won't be used in test mode
```

Then in the GUI:
1. Check the **"Test Mode (Mock PVs/Tomoscan)"** checkbox in Additional Settings
2. Configure your scan parameters
3. Click "Start Scan"

## What Test Mode Does

### Mock Image Generation
- Generates synthetic 1280x1024 uint16 images
- Each position has a unique pattern (gradients + circular features + noise)
- Images vary based on position index to verify stitching logic

### Mock Motor Control
- All `caput` commands are logged but not executed
- Motor movements return instantly (no waiting for hardware)
- Position tolerance checks always succeed

### Mock Tomoscan
- Simulates `tomoscan single` command with 0.5s delay
- Generates a slightly different image pattern (offset by 1000) to distinguish from preview images
- Tests the tomoscan integration logic including:
  - Position storage before zeroing
  - First projection capture
  - Correct placement in stitched preview
  - Motor position restoration

## Testing Scenarios

### 1. Basic Stitching Test
```
Test Mode: ✓ Enabled
Grid: 2x2 (quick test)
Run tomoscan: ✗ Disabled
```
Tests basic preview stitching without tomoscan.

### 2. Tomoscan Integration Test
```
Test Mode: ✓ Enabled
Grid: 2x2 or 3x3
Run tomoscan: ✓ Enabled
Tomoscan Prefix: any value (mocked)
```
Tests the full tomoscan workflow:
- Preview image at each position
- Tomoscan execution
- First projection capture and placement
- Motor position handling

### 3. Larger Grid Test
```
Test Mode: ✓ Enabled
Grid: 5x5
Settle Time: 0.1s (faster in test mode)
```
Tests performance with more positions.

## Visual Verification

When test mode is working correctly, you should see:

1. **Live Preview**: Stitched mosaic building up in real-time
2. **Position-dependent patterns**: Each tile should look slightly different
3. **Borders**: White borders around each stitched tile
4. **Log messages**: `[MOCK]` prefix on simulated operations

## Test Mode vs Real Mode

| Feature | Test Mode | Real Mode |
|---------|-----------|-----------|
| PV Connection | Mocked | Required |
| Motor Movement | Instant | Hardware-dependent |
| Image Acquisition | Synthetic | From camera |
| Tomoscan | Simulated (0.5s) | Real (minutes) |
| Settle Time | Reduced to 0.1s | User-configured |
| Error Handling | Simplified | Full validation |

## Code Implementation

Test mode is implemented throughout [mosalign.py](src/pystream/plugins/mosalign.py):

- **`_toggle_test_mode()`** (line 505): Enables/disables test mode
- **`_generate_mock_image()`** (line 522): Creates synthetic images
- **`_get_image_now()`** (line 634): Returns mock or real images
- **`_caput()`** (line 669): Logs or executes motor commands
- **`_wait_for_motor()`** (line 689): Returns instantly in test mode
- **Tomoscan logic** (line 1240+): Simulates or executes tomoscan

Test script: [test/test_mosalign.py](test/test_mosalign.py)

## Troubleshooting

### Images not appearing
- Check that Test Mode checkbox is enabled
- Verify "Enable Live Preview" is checked
- Try Auto Contrast checkbox

### Scan runs too fast/slow
- Test mode uses 0.1s settle time (ignores configured value)
- Adjust grid size for desired test duration
- Tomoscan adds 0.5s per position when enabled

### Test mode not working
- Ensure you're using the latest version of mosalign.py
- Check the log for `[MOCK]` messages
- Connection status should show "Test Mode: Mock camera enabled"

## Next Steps

Once you've verified the logic works in test mode:
1. Disable test mode checkbox
2. Connect to real PVs
3. Test with real hardware in a controlled environment
4. Gradually increase scan complexity
