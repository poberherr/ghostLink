#!/bin/bash
# Quick test of the analog video pipeline

set -e  # Exit on error

echo "=== Analog Video Pipeline Test ==="
echo ""

# Step 1: Create test video
echo "Step 1: Creating test video..."
uv run create_test_video.py
echo ""

# Step 2: Convert to analog
echo "Step 2: Converting video to analog signal..."
uv run video_to_analog.py test_pattern.mp4 test_pattern.analog
echo ""

# Step 3: Decode and view
echo "Step 3: Decoding analog signal..."
uv run analog_to_video.py test_pattern.analog --output decoded.mp4 --no-display
echo ""

# Show file sizes
echo "=== Results ==="
ls -lh test_pattern.mp4 test_pattern.analog decoded.mp4
echo ""

echo "✅ Pipeline test complete!"
echo ""
echo "To view the decoded video:"
echo "  uv run analog_to_video.py test_pattern.analog --display"
echo ""
echo "To view with waveform analysis:"
echo "  uv run analog_to_video.py test_pattern.analog --display --show-waveform --analyze"

