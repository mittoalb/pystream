#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVAccess NTNDArray Image Simulator
-----------------------------------
Streams test images to a PVAccess channel for testing viewers.

Usage:
    python test_image_streamer.py --pv TEST:IMAGE --fps 10 --pattern random
    
Patterns:
    - random: Random noise
    - gradient: Gradient pattern
    - circles: Moving circles
    - checkerboard: Checkerboard pattern
"""

import argparse
import time
import numpy as np
import pvaccess as pva


# ==================== AdImageUtility ====================
class AdImageUtility:
    """Utility class for creating NTNDArray structures"""
    
    NTNDA_DATA_FIELD_KEY_MAP = {
        np.dtype('uint8')   : 'ubyteValue',
        np.dtype('int8')    : 'byteValue',
        np.dtype('uint16')  : 'ushortValue',
        np.dtype('int16')   : 'shortValue',
        np.dtype('uint32')  : 'uintValue',
        np.dtype('int32')   : 'intValue',
        np.dtype('uint64')  : 'ulongValue',
        np.dtype('int64')   : 'longValue',
        np.dtype('float32') : 'floatValue',
        np.dtype('float64') : 'doubleValue'
    }

    PVA_DATA_TYPE_MAP = {
        np.dtype('uint8')   : pva.UBYTE,
        np.dtype('int8')    : pva.BYTE,
        np.dtype('uint16')  : pva.USHORT,
        np.dtype('int16')   : pva.SHORT,
        np.dtype('uint32')  : pva.UINT,
        np.dtype('int32')   : pva.INT,
        np.dtype('uint64')  : pva.ULONG,
        np.dtype('int64')   : pva.LONG,
        np.dtype('float32') : pva.FLOAT,
        np.dtype('float64') : pva.DOUBLE
    }

    @classmethod
    def generateNtNdArray2D(cls, imageId, imageData):
        """Generate NTNDArray for a 2D image"""
        ntNdArray = pva.NtNdArray()
        
        dataFieldKey = cls.NTNDA_DATA_FIELD_KEY_MAP.get(imageData.dtype)
        pvaDataType = cls.PVA_DATA_TYPE_MAP.get(imageData.dtype)
        
        data = imageData.flatten()
        ny, nx = imageData.shape
        size = nx * ny * data.itemsize
        
        ntNdArray['compressedSize'] = size
        ntNdArray['uncompressedSize'] = size
        ntNdArray['uniqueId'] = int(imageId)
        
        dims = [pva.PvDimension(nx, 0, nx, 1, False),
                pva.PvDimension(ny, 0, ny, 1, False)]
        ntNdArray['dimension'] = dims
        
        ts = pva.PvTimeStamp(time.time())
        ntNdArray['timeStamp'] = ts
        ntNdArray['dataTimeStamp'] = ts
        ntNdArray['descriptor'] = 'Simulated image'
        
        ntNdArray['value'] = {dataFieldKey: data}
        
        attrs = [pva.NtAttribute('ColorMode', pva.PvInt(0))]
        ntNdArray['attribute'] = attrs
        
        return ntNdArray

    @classmethod
    def replaceNtNdArrayImage2D(cls, ntNdArray, imageId, image):
        """Replace image data in existing NTNDArray"""
        dataFieldKey = cls.NTNDA_DATA_FIELD_KEY_MAP.get(image.dtype)
        pvaDataType = cls.PVA_DATA_TYPE_MAP.get(image.dtype)
        
        data = image.flatten()
        ntNdArray['uniqueId'] = int(imageId)
        
        ny, nx = image.shape
        dims = ntNdArray['dimension']
        if dims[0]['size'] != nx or dims[1]['size'] != ny:
            dims = [pva.PvDimension(nx, 0, nx, 1, False),
                    pva.PvDimension(ny, 0, ny, 1, False)]
            ntNdArray['dimension'] = dims
            size = nx * ny * data.itemsize
            ntNdArray['compressedSize'] = size
            ntNdArray['uncompressedSize'] = size
        
        ts = pva.PvTimeStamp(time.time())
        ntNdArray['timeStamp'] = ts
        ntNdArray['dataTimeStamp'] = ts
        
        u = pva.PvObject({dataFieldKey: [pvaDataType]}, {dataFieldKey: data})
        ntNdArray.setUnion(u)
        
        return ntNdArray


# ==================== Image generators ====================
def create_random_image(width=1000, height=1000, frame=0):
    """Create random noise image"""
    return np.random.randint(0, 65535, size=(height, width), dtype=np.uint16)


def create_gradient_image(width=1000, height=1000, frame=0):
    """Create gradient pattern that shifts over time"""
    x = np.linspace(0, 4*np.pi, width)
    y = np.linspace(0, 4*np.pi, height)
    xx, yy = np.meshgrid(x, y)
    
    offset = frame * 0.1
    img = np.sin(xx + offset) * np.cos(yy + offset)
    img = ((img + 1) * 32767).astype(np.uint16)
    return img


def create_circles_image(width=1000, height=1000, frame=0):
    """Create moving circles pattern"""
    img = np.zeros((height, width), dtype=np.uint16)
    
    y, x = np.ogrid[:height, :width]
    
    for i in range(3):
        angle = frame * 0.05 + i * 2 * np.pi / 3
        cx = width // 2 + int(width * 0.3 * np.cos(angle))
        cy = height // 2 + int(height * 0.3 * np.sin(angle))
        radius = 100 + 50 * np.sin(frame * 0.1 + i)
        
        dist = np.sqrt((x - cx)**2 + (y - cy)**2)
        mask = dist < radius
        img[mask] = int(20000 + 10000 * np.sin(frame * 0.1 + i))
    
    return img


def create_checkerboard_image(width=1000, height=1000, frame=0):
    """Create animated checkerboard pattern"""
    square_size = 50 + int(20 * np.sin(frame * 0.05))
    img = np.zeros((height, width), dtype=np.uint16)
    
    for i in range(0, height, square_size):
        for j in range(0, width, square_size):
            if ((i // square_size) + (j // square_size)) % 2 == 0:
                img[i:i+square_size, j:j+square_size] = 40000
            else:
                img[i:i+square_size, j:j+square_size] = 10000
    
    return img


# ==================== Image Streamer ====================
class ImageStreamer:
    """PVAccess image streamer using AdImageUtility"""
    
    def __init__(self, pv_name: str, width: int = 1000, height: int = 1000, 
                 fps: float = 10.0, pattern: str = 'random'):
        self.pv_name = pv_name
        self.width = width
        self.height = height
        self.fps = fps
        self.pattern = pattern
        self.frame_count = 0
        self.running = False
        
        self.patterns = {
            'random': create_random_image,
            'gradient': create_gradient_image,
            'circles': create_circles_image,
            'checkerboard': create_checkerboard_image
        }
        
        if pattern not in self.patterns:
            raise ValueError(f"Unknown pattern: {pattern}. Available: {list(self.patterns.keys())}")
        
        # Create PVA server
        self.server = pva.PvaServer()
        
        # Create initial NTNDArray using AdImageUtility
        initial_image = self.patterns[self.pattern](self.width, self.height, 0)
        self.ntnda = AdImageUtility.generateNtNdArray2D(0, initial_image)
        
        # Add channel to server
        self.server.addRecord(pv_name, self.ntnda)
        
        print(f"PVA Server started: {pv_name}")
        print(f"Image size: {width}x{height}")
        print(f"Pattern: {pattern}")
        print(f"Target FPS: {fps}")
        print("\nPress Ctrl+C to stop\n")
    
    def start(self):
        """Start streaming images"""
        self.running = True
        frame_interval = 1.0 / self.fps
        
        try:
            while self.running:
                start_time = time.time()
                
                # Generate image
                img = self.patterns[self.pattern](self.width, self.height, self.frame_count)
                
                # Update NTNDArray with new image using AdImageUtility
                AdImageUtility.replaceNtNdArrayImage2D(self.ntnda, self.frame_count, img)
                
                # Update PV
                self.server.update(self.pv_name, self.ntnda)
                
                self.frame_count += 1
                
                # Print status every 100 frames
                if self.frame_count % 100 == 0:
                    print(f"Frame {self.frame_count} | "
                          f"Min: {img.min()} | Max: {img.max()} | "
                          f"Mean: {img.mean():.1f}")
                
                # Sleep to maintain frame rate
                elapsed = time.time() - start_time
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\nStopping streamer...")
        finally:
            self.stop()
    
    def stop(self):
        """Stop streaming"""
        self.running = False
        print(f"Streamed {self.frame_count} frames")


# ==================== Main ====================
def main():
    parser = argparse.ArgumentParser(
        description="PVAccess NTNDArray Image Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_image_streamer.py --pv TEST:IMAGE --fps 10 --pattern random
  python test_image_streamer.py --pv TEST:IMAGE --fps 30 --pattern gradient
  python test_image_streamer.py --pv TEST:IMAGE --fps 20 --pattern circles --width 800 --height 600
        """
    )
    
    parser.add_argument('--pv', type=str, default='TEST:IMAGE',
                        help='PV name (default: TEST:IMAGE)')
    parser.add_argument('--width', type=int, default=1000,
                        help='Image width (default: 1000)')
    parser.add_argument('--height', type=int, default=1000,
                        help='Image height (default: 1000)')
    parser.add_argument('--fps', type=float, default=10.0,
                        help='Frames per second (default: 10.0)')
    parser.add_argument('--pattern', type=str, default='random',
                        choices=['random', 'gradient', 'circles', 'checkerboard'],
                        help='Image pattern (default: random)')
    
    args = parser.parse_args()
    
    streamer = ImageStreamer(
        pv_name=args.pv,
        width=args.width,
        height=args.height,
        fps=args.fps,
        pattern=args.pattern
    )
    
    streamer.start()


if __name__ == '__main__':
    main()