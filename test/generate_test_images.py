#!/usr/bin/env python3
"""
Generate random test images and publish to EPICS PV using pvaPy.

Usage:
    python generate_test_images.py --pv TEST:image --fps 10 --width 512 --height 512
    python generate_test_images.py --pv TEST:image --fps 30 --pattern noise
    python generate_test_images.py --pv TEST:image --fps 5 --pattern gradient --moving
"""

import argparse
import time
import numpy as np
import pvaccess as pva


class ImageGenerator:
    """Generate test images with various patterns."""

    def __init__(self, width=512, height=512, pattern='noise', dtype=np.uint16):
        self.width = width
        self.height = height
        self.pattern = pattern
        self.dtype = dtype
        self.frame_counter = 0
        self.t0 = time.time()

    def generate(self):
        """Generate a single frame based on pattern type."""
        if self.pattern == 'noise':
            return self._noise_pattern()
        elif self.pattern == 'gradient':
            return self._gradient_pattern()
        elif self.pattern == 'circles':
            return self._circles_pattern()
        elif self.pattern == 'moving_dot':
            return self._moving_dot_pattern()
        elif self.pattern == 'sine_wave':
            return self._sine_wave_pattern()
        else:
            return self._noise_pattern()

    def _noise_pattern(self):
        """Random noise."""
        if self.dtype == np.uint16:
            return np.random.randint(0, 65536, (self.height, self.width), dtype=np.uint16)
        else:
            return np.random.randint(0, 256, (self.height, self.width), dtype=np.uint8)

    def _gradient_pattern(self):
        """Horizontal gradient with optional motion."""
        x = np.linspace(0, 1, self.width)
        y = np.ones(self.height)
        gradient = np.outer(y, x)

        # Add some temporal variation
        phase = self.frame_counter * 0.1
        gradient = (gradient + 0.3 * np.sin(phase)) / 1.3

        if self.dtype == np.uint16:
            return (gradient * 65535).astype(np.uint16)
        else:
            return (gradient * 255).astype(np.uint8)

    def _circles_pattern(self):
        """Concentric circles."""
        y, x = np.ogrid[:self.height, :self.width]
        cx, cy = self.width // 2, self.height // 2
        r = np.sqrt((x - cx)**2 + (y - cy)**2)

        # Animate circles
        phase = self.frame_counter * 0.2
        pattern = np.sin(r / 20 - phase)
        pattern = (pattern + 1) / 2  # Normalize to [0, 1]

        if self.dtype == np.uint16:
            return (pattern * 65535).astype(np.uint16)
        else:
            return (pattern * 255).astype(np.uint8)

    def _moving_dot_pattern(self):
        """Single dot moving in a circle."""
        img = np.zeros((self.height, self.width), dtype=self.dtype)

        # Circular motion
        t = self.frame_counter * 0.1
        cx = self.width // 2 + int(self.width // 4 * np.cos(t))
        cy = self.height // 2 + int(self.height // 4 * np.sin(t))

        # Draw dot
        y, x = np.ogrid[:self.height, :self.width]
        r = np.sqrt((x - cx)**2 + (y - cy)**2)
        mask = r < 20

        if self.dtype == np.uint16:
            img[mask] = 65535
        else:
            img[mask] = 255

        return img

    def _sine_wave_pattern(self):
        """Animated sine wave pattern."""
        y, x = np.ogrid[:self.height, :self.width]

        # Create sine wave
        phase = self.frame_counter * 0.2
        pattern = np.sin(x / 30 + phase) * np.sin(y / 30 + phase * 0.7)
        pattern = (pattern + 1) / 2  # Normalize to [0, 1]

        if self.dtype == np.uint16:
            return (pattern * 65535).astype(np.uint16)
        else:
            return (pattern * 255).astype(np.uint8)


def create_ntnda_dict(image, uid, timestamp):
    """
    Create NTNDArray dictionary for PVAccess.

    Args:
        image: numpy array
        uid: unique ID counter
        timestamp: timestamp in seconds

    Returns:
        dict: NTNDArray structure
    """
    height, width = image.shape

    # Create attribute list (can add more metadata here)
    attributes = [
        {'name': 'ColorMode', 'value': 0},  # Mono
    ]

    # Build NTNDArray structure
    ntnda = {
        'value': image.flatten().tolist(),
        'codec': {'name': '', 'parameters': ''},
        'compressedSize': 0,
        'uncompressedSize': image.nbytes,
        'uniqueId': uid,
        'dataTimeStamp': {
            'secondsPastEpoch': int(timestamp),
            'nanoseconds': int((timestamp % 1) * 1e9)
        },
        'alarm': {
            'severity': 0,
            'status': 0,
            'message': ''
        },
        'timeStamp': {
            'secondsPastEpoch': int(timestamp),
            'nanoseconds': int((timestamp % 1) * 1e9)
        },
        'dimension': [
            {'size': width, 'offset': 0, 'fullSize': width, 'binning': 1, 'reverse': False},
            {'size': height, 'offset': 0, 'fullSize': height, 'binning': 1, 'reverse': False}
        ],
        'attribute': attributes
    }

    return ntnda


def main():
    parser = argparse.ArgumentParser(description='Generate test images for EPICS PVAccess')
    parser.add_argument('--pv', type=str, default='TEST:image',
                        help='PV name to publish to (default: TEST:image)')
    parser.add_argument('--fps', type=float, default=10.0,
                        help='Frames per second (default: 10)')
    parser.add_argument('--width', type=int, default=512,
                        help='Image width (default: 512)')
    parser.add_argument('--height', type=int, default=512,
                        help='Image height (default: 512)')
    parser.add_argument('--pattern', type=str, default='noise',
                        choices=['noise', 'gradient', 'circles', 'moving_dot', 'sine_wave'],
                        help='Pattern type (default: noise)')
    parser.add_argument('--dtype', type=str, default='uint16',
                        choices=['uint8', 'uint16'],
                        help='Data type (default: uint16)')
    parser.add_argument('--duration', type=float, default=None,
                        help='Duration in seconds (default: run forever)')

    args = parser.parse_args()

    # Convert dtype string to numpy dtype
    dtype = np.uint16 if args.dtype == 'uint16' else np.uint8

    # Create image generator
    generator = ImageGenerator(args.width, args.height, args.pattern, dtype)

    # Create PVAccess server channel
    print(f"Publishing to PV: {args.pv}")
    print(f"Pattern: {args.pattern}")
    print(f"Resolution: {args.width}x{args.height}")
    print(f"FPS: {args.fps}")
    print(f"Data type: {args.dtype}")
    print("Press Ctrl+C to stop\n")

    try:
        server = pva.PvaServer()

        # Calculate frame interval
        frame_interval = 1.0 / args.fps
        start_time = time.time()
        uid = 0

        while True:
            # Generate image
            image = generator.generate()
            generator.frame_counter += 1
            uid += 1

            # Get timestamp
            timestamp = time.time()

            # Create NTNDArray structure
            ntnda = create_ntnda_dict(image, uid, timestamp)

            # Create PvObject and publish
            pv_object = pva.PvObject(ntnda)
            server.addRecord(args.pv, pv_object)

            # Print status
            elapsed = time.time() - start_time
            actual_fps = uid / elapsed if elapsed > 0 else 0
            print(f"\rFrame {uid:6d} | "
                  f"Elapsed: {elapsed:6.1f}s | "
                  f"Actual FPS: {actual_fps:5.1f} | "
                  f"Target: {args.fps:5.1f}",
                  end='', flush=True)

            # Check duration limit
            if args.duration is not None and elapsed >= args.duration:
                print(f"\n\nReached duration limit of {args.duration} seconds")
                break

            # Sleep to maintain frame rate
            next_frame_time = start_time + uid * frame_interval
            sleep_time = next_frame_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\nStopped by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
