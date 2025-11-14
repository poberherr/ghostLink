#!/bin/bash
# Compare different scrambling strengths

echo "=== Analog Scrambling Comparison ==="
echo ""

INPUT="assets/analog/berlin.analog"

# 1. Basic scrambling
echo "1. Basic scrambling (line_shuffle)..."
uv run analog_scrambler.py "$INPUT" assets/scrambled/berlin_basic.analog \
    --method line_shuffle --blocks 20
uv run analog_to_video.py assets/scrambled/berlin_basic.analog \
    --output assets/output/berlin_basic.mp4 --no-display
echo "   ✓ Created berlin_basic.mp4"
echo ""

# 2. Moderate crypto scrambling (16 segments)
echo "2. Moderate crypto scrambling (16 segments)..."
uv run analog_scrambler_crypto.py "$INPUT" assets/scrambled/berlin_crypto16.analog \
    --segments 16 --password "test123"
uv run analog_to_video.py assets/scrambled/berlin_crypto16.analog \
    --output assets/output/berlin_crypto16.mp4 --no-display
echo "   ✓ Created berlin_crypto16.mp4"
echo ""

# 3. Strong crypto scrambling (32 segments)
echo "3. Strong crypto scrambling (32 segments)..."
uv run analog_scrambler_crypto.py "$INPUT" assets/scrambled/berlin_crypto32.analog \
    --segments 32 --password "test123"
uv run analog_to_video.py assets/scrambled/berlin_crypto32.analog \
    --output assets/output/berlin_crypto32.mp4 --no-display
echo "   ✓ Created berlin_crypto32.mp4"
echo ""

# 4. Maximum security (32 segments + different key)
echo "4. Maximum security (32 segments, strong password)..."
uv run analog_scrambler_crypto.py "$INPUT" assets/scrambled/berlin_ultra.analog \
    --segments 32 --password "ultra_secure_fpv_military_grade"
uv run analog_to_video.py assets/scrambled/berlin_ultra.analog \
    --output assets/output/berlin_ultra.mp4 --no-display
echo "   ✓ Created berlin_ultra.mp4"
echo ""

echo "=== Comparison Complete ==="
echo ""
echo "View results:"
echo "  Original:    uv run analog_to_video.py $INPUT --display"
echo "  Basic:       open assets/output/berlin_basic.mp4"
echo "  16 segments: open assets/output/berlin_crypto16.mp4"
echo "  32 segments: open assets/output/berlin_crypto32.mp4"
echo "  Ultra:       open assets/output/berlin_ultra.mp4"
echo ""
echo "File sizes:"
ls -lh assets/output/*.mp4

