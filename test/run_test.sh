#!/bin/bash
# Quick test launcher for pystream

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}PyStream Test Image Generator${NC}\n"

# Check if pattern argument provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <test_name>"
    echo ""
    echo "Available tests:"
    echo "  fast       - Fast random noise (50 FPS) - test recording"
    echo "  slow       - Slow moving dot (2 FPS) - easy to see"
    echo "  normal     - Normal random noise (10 FPS) - default"
    echo "  circles    - Animated circles (15 FPS) - nice pattern"
    echo "  gradient   - Moving gradient (20 FPS) - smooth"
    echo "  sine       - Sine waves (25 FPS) - complex pattern"
    echo "  hires      - High resolution (1920x1080, 5 FPS)"
    echo "  lowres     - Low resolution (256x256, 30 FPS)"
    echo ""
    echo "Example: $0 fast"
    exit 1
fi

TEST=$1
PV=${PV:-"TEST:image"}

echo -e "${GREEN}Publishing to PV: $PV${NC}"
echo -e "${GREEN}Press Ctrl+C to stop${NC}\n"

case $TEST in
    fast)
        echo "Fast random noise (50 FPS) - good for testing recording buffering"
        python3 generate_test_images.py --pv $PV --fps 50 --pattern noise
        ;;
    slow)
        echo "Slow moving dot (2 FPS) - easy to see individual frames"
        python3 generate_test_images.py --pv $PV --fps 2 --pattern moving_dot
        ;;
    normal)
        echo "Normal random noise (10 FPS)"
        python3 generate_test_images.py --pv $PV --fps 10 --pattern noise
        ;;
    circles)
        echo "Animated concentric circles (15 FPS)"
        python3 generate_test_images.py --pv $PV --fps 15 --pattern circles
        ;;
    gradient)
        echo "Moving gradient (20 FPS)"
        python3 generate_test_images.py --pv $PV --fps 20 --pattern gradient
        ;;
    sine)
        echo "Sine wave pattern (25 FPS)"
        python3 generate_test_images.py --pv $PV --fps 25 --pattern sine_wave
        ;;
    hires)
        echo "High resolution (1920x1080 @ 5 FPS)"
        python3 generate_test_images.py --pv $PV --fps 5 --width 1920 --height 1080 --pattern circles
        ;;
    lowres)
        echo "Low resolution (256x256 @ 30 FPS)"
        python3 generate_test_images.py --pv $PV --fps 30 --width 256 --height 256 --pattern noise
        ;;
    *)
        echo "Unknown test: $TEST"
        echo "Run '$0' without arguments to see available tests"
        exit 1
        ;;
esac
