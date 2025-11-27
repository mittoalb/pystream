#!/usr/bin/env python3
"""
Simple command-line test for mosalign logic without GUI

This shows you exactly what commands would be executed during a scan.
No GUI needed - just console output.
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np


class MockMotorScan:
    """Mock version that just prints what would happen"""

    def __init__(self):
        self.test_mode = True
        self.motor1_pv = "2bmb:m17"
        self.motor2_pv = "2bmHXP:m3"
        self.tomoscan_prefix = "2bmb:TomoScan:"

    def run_scan(self, x_start, x_step, x_steps, y_start, y_step, y_steps,
                 run_tomoscan=False):
        """Run a mock scan and print commands"""

        print("\n" + "="*70)
        print("MOSALIGN TEST - Showing commands that would be executed")
        print("="*70)
        print(f"\nScan Parameters:")
        print(f"  X: start={x_start}, step={x_step}, steps={x_steps}")
        print(f"  Y: start={y_start}, step={y_step}, steps={y_steps}")
        print(f"  Total positions: {x_steps * y_steps}")
        print(f"  Run tomoscan: {run_tomoscan}")
        print("\n" + "="*70 + "\n")

        position = 0
        total = x_steps * y_steps

        # Move to start
        print(f"[SETUP] Moving to start position")
        print(f"  → caput {self.motor1_pv} {x_start}")
        print(f"  → caput {self.motor2_pv} {y_start}")
        print(f"  → wait for motors to settle...")
        print()

        # Scan grid
        for i in range(x_steps):
            for j in range(y_steps):
                position += 1
                x_pos = x_start + (i * x_step)
                y_pos = y_start + (j * y_step)

                print(f"\n[Position {position}/{total}] X:{i+1}/{x_steps}, Y:{j+1}/{y_steps}")
                print(f"  Target: X={x_pos:.3f}, Y={y_pos:.3f}")
                print(f"  ┌─ Move motors")
                print(f"  │  $ caput {self.motor1_pv} {x_pos}")
                print(f"  │  $ caput {self.motor2_pv} {y_pos}")
                print(f"  ├─ Wait for motors to reach position (check .RBV)")
                print(f"  │  $ caget -t {self.motor1_pv}.RBV")
                print(f"  │  $ caget -t {self.motor2_pv}.RBV")
                print(f"  ├─ Settle time delay (wait for vibrations)")
                print(f"  ├─ Capture preview image from PV")
                print(f"  └─ Place image in stitched canvas at grid position ({i}, {j})")

                if run_tomoscan:
                    print(f"\n  ┌─[TOMOSCAN] Starting at position ({x_pos:.3f}, {y_pos:.3f})")
                    print(f"  │  1. Store absolute positions BEFORE tomoscan:")
                    print(f"  │     abs_x = {x_pos:.3f}, abs_y = {y_pos:.3f}")
                    print(f"  │")
                    print(f"  │  2. Run tomoscan:")
                    print(f"  │     $ tomoscan single --tomoscan-prefix {self.tomoscan_prefix}")
                    print(f"  │")
                    print(f"  │  3. [IMPORTANT] Tomoscan zeros motors internally!")
                    print(f"  │     After tomoscan starts:")
                    print(f"  │     - Motor positions become relative (0-based)")
                    print(f"  │     - Our stored abs_x, abs_y values are still valid")
                    print(f"  │")
                    print(f"  │  4. Wait for tomoscan completion (5 min timeout)")
                    print(f"  │")
                    print(f"  │  5. Capture FIRST projection from tomoscan")
                    print(f"  │     (this is different from preview image)")
                    print(f"  │")
                    print(f"  │  6. Place tomoscan projection in stitched canvas")
                    print(f"  │     Using grid position ({i}, {j}) - same as preview")
                    print(f"  │")
                    print(f"  │  7. Restore motors to absolute positions:")
                    print(f"  │     $ caput {self.motor1_pv} {x_pos}")
                    print(f"  │     $ caput {self.motor2_pv} {y_pos}")
                    print(f"  │     (This accounts for the zeroing that tomoscan did)")
                    print(f"  └─[TOMOSCAN] Complete")

                print()

        print("="*70)
        print("SCAN COMPLETE")
        print("="*70)
        print(f"\nSummary:")
        print(f"  Total positions: {position}")
        print(f"  Motor commands issued: {position * 2 + 2}")  # 2 per position + 2 for start
        if run_tomoscan:
            print(f"  Tomoscan runs: {position}")
            print(f"  Motor restores after tomoscan: {position * 2}")
        print()


def main():
    """Run test scenarios"""

    scanner = MockMotorScan()

    print("\n" + "#"*70)
    print("# TEST 1: Basic 2x2 scan WITHOUT tomoscan")
    print("#"*70)
    scanner.run_scan(
        x_start=-0.16, x_step=4.0, x_steps=2,
        y_start=0.0, y_step=1.4, y_steps=2,
        run_tomoscan=False
    )

    input("\nPress Enter to see TEST 2 (with tomoscan)...")

    print("\n" + "#"*70)
    print("# TEST 2: Same 2x2 scan WITH tomoscan")
    print("#"*70)
    scanner.run_scan(
        x_start=-0.16, x_step=4.0, x_steps=2,
        y_start=0.0, y_step=1.4, y_steps=2,
        run_tomoscan=True
    )

    print("\n" + "="*70)
    print("Key Points:")
    print("="*70)
    print("1. Motors moved to each position in grid")
    print("2. Preview image captured at each position")
    print("3. When tomoscan enabled:")
    print("   - Absolute motor positions stored BEFORE tomoscan")
    print("   - tomoscan runs (which zeros motors internally)")
    print("   - First projection captured from tomoscan")
    print("   - Motors restored to absolute positions")
    print("4. All coordinates use absolute values (not relative)")
    print("="*70)
    print()


if __name__ == '__main__':
    main()
