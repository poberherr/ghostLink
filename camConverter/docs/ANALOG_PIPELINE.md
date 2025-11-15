# Analog Signal Pipeline

Complete pipeline for converting video to analog signals, applying scrambling, and viewing results.

## Pipeline Overview

```
┌──────────────┐
│ Video Source │ (file or webcam)
└──────┬───────┘
       │
       ▼
┌─────────────────────┐
│ video_to_analog.py  │  Converts video → composite analog signal
└──────┬──────────────┘
       │ .analog file (binary waveform)
       ▼
┌─────────────────────┐
│ analog_scrambler.py │  (TODO: your scrambling algorithm)
└──────┬──────────────┘
       │ .analog file (scrambled)
       ▼
┌─────────────────────┐
│ analog_to_video.py  │  Decodes analog → video for viewing
└─────────────────────┘
```

## Step 1: Convert Video to Analog Signal

### Basic Usage

```bash
# From video file
uv run camConverter/video_to_analog.py input.mp4 output.analog

# From webcam (record 10 seconds = 300 frames)
uv run camConverter/video_to_analog.py 0 webcam.analog --max-frames 300
```

### Advanced Options

```bash
# NTSC with high sample rate
uv run camConverter/video_to_analog.py input.mp4 output.analog \
    --standard ntsc \
    --sample-rate 14000000 \
    --bandwidth 4.5 \
    --preview

# PAL with noise
uv run camConverter/video_to_analog.py input.mp4 output.analog \
    --standard pal \
    --add-noise \
    --noise-level 0.03 \
    --preview

# Custom resolution
uv run camConverter/video_to_analog.py input.mp4 output.analog \
    --width 720 \
    --height 576 \
    --verbose
```

### Output Format

The `.analog` file contains:
- **Header**: Magic number, version, JSON metadata
- **Data**: Continuous float32 samples representing voltage waveform

**File Structure:**
```
[ANLG][version:4][metadata_len:4][metadata_json][sample1:f32][sample2:f32]...
```

**Metadata includes:**
- Standard (NTSC/PAL)
- Sample rate (Hz)
- Resolution (width×height)
- Frame rate (fps)
- Samples per line/frame
- Voltage levels (sync, blanking, black, white)
- Timestamp

**Signal characteristics:**
- 1D temporal waveform (like oscilloscope view)
- Proper H-sync pulses every line
- V-blanking intervals
- Bandwidth-limited luminance (default 4.2 MHz)
- Voltage range: -0.3V (sync tip) to +0.7V (peak white)

## Step 2: View/Verify Analog Signal

### Basic Usage

```bash
# View with display
uv run camConverter/analog_to_video.py output.analog --display

# Convert to video file
uv run camConverter/analog_to_video.py output.analog --output decoded.mp4

# View with waveform analysis
uv run camConverter/analog_to_video.py output.analog \
    --show-waveform \
    --analyze
```

### Viewer Controls

- **Space**: Pause/Resume
- **Q**: Quit
- **--fast**: Play as fast as possible (no frame delay)

### Analysis Features

```bash
# Analyze signal quality
uv run camConverter/analog_to_video.py output.analog \
    --analyze \
    --verbose

# Output includes:
# - Sync pulse count vs expected
# - Sync level min/mean
# - Signal range (min/max voltage)
```

## Step 3: Scrambling (Your Work)

Create `analog_scrambler.py` to implement your scrambling algorithms:

### Example Scrambler Template

```python
#!/usr/bin/env python3
"""Analog signal scrambler."""

import numpy as np
from analog_to_video import AnalogFileReader
from video_to_analog import AnalogFileWriter

def scramble_line_rotation(signal, metadata):
    """Rotate lines by random amounts."""
    samples_per_line = metadata['samples_per_line']
    lines = signal.reshape(-1, samples_per_line)
    
    # Rotate each line
    for i in range(len(lines)):
        shift = np.random.randint(0, samples_per_line)
        lines[i] = np.roll(lines[i], shift)
    
    return lines.flatten()

def scramble_sync_suppression(signal, metadata):
    """Suppress or modify sync pulses."""
    sync_threshold = metadata['voltage_levels']['sync_tip'] * 0.5
    signal[signal < sync_threshold] = 0  # Remove sync
    return signal

# Main scrambler
reader = AnalogFileReader('input.analog')
reader.open()

# Process each frame
while True:
    signal = reader.read_frame()
    if signal is None:
        break
    
    # Apply scrambling
    scrambled = scramble_line_rotation(signal, reader.metadata)
    
    # Write to output
    # ... (use AnalogFileWriter)
```

## Performance Notes

### File Sizes

For 1 second of video:

- **NTSC @ 10 MHz sampling:**
  - 525 lines/frame × 30 fps = 15,750 lines/sec
  - ~635 samples/line × 15,750 = 10M samples/sec
  - 10M × 4 bytes (float32) = **~40 MB/sec**

- **10 seconds of video = ~400 MB**
- **1 minute = ~2.4 GB**

### Processing Speed

On modern Mac:
- **Encoding**: 30-60 fps (depends on resolution)
- **Decoding**: 60-120 fps
- **Scrambling**: depends on algorithm (should be very fast for simple ops)

### Optimization Tips

1. **Lower sample rate** (8 MHz is often sufficient):
   ```bash
   --sample-rate 8000000
   ```

2. **Lower resolution**:
   ```bash
   --width 320 --height 240
   ```

3. **Process shorter clips** for iteration:
   ```bash
   --max-frames 90  # 3 seconds at 30fps
   ```

## Signal Structure Details

### Horizontal Line Timing (NTSC)

```
|←────────────── 63.556 μs ──────────────→|
|←sync→|←back→|←─────── active video ─────→|←front→|
  4.7μs  4.7μs         52.656 μs              1.5μs

At 10 MHz sampling:
- Total: 635 samples/line
- Sync: 47 samples
- Back porch: 47 samples
- Active: 526 samples
- Front porch: 15 samples
```

### Voltage Levels

```
 1.0V ┤
      │
 0.7V ┤──────────────────  Peak White
      │    ████████
 0.0V ┤────        ────────  Blanking Level
      │    ▼
-0.3V ┤   Sync Tip
```

### Frame Structure (NTSC)

- **525 total lines**
- **~480 active lines** with video
- **~45 lines** for vertical blanking
- **H-sync** on every line
- **V-sync** during vertical blanking

## Troubleshooting

### "Module not found" errors

Make sure dependencies are installed:
```bash
uv add opencv-python numpy matplotlib
```

### Camera permission issues

On macOS, grant camera permissions:
```bash
System Preferences → Security & Privacy → Camera
```

Or use a video file instead of webcam.

### File size too large

Reduce sample rate or resolution:
```bash
--sample-rate 8000000 --width 320 --height 240
```

### Decoded video looks wrong

Check signal levels with analysis:
```bash
uv run camConverter/analog_to_video.py output.analog --analyze --verbose
```

## Next Steps

1. **Generate test signal**:
   ```bash
   uv run camConverter/video_to_analog.py test_video.mp4 test.analog --max-frames 90
   ```

2. **Verify it works**:
   ```bash
   uv run camConverter/analog_to_video.py test.analog --display
   ```

3. **Build your scrambler**:
   - Read `.analog` file
   - Modify signal (line rotation, sync suppression, etc.)
   - Write new `.analog` file

4. **Test scrambled signal**:
   ```bash
   uv run camConverter/analog_to_video.py scrambled.analog --display
   ```

5. **Build descrambler** and verify recovery!

## Examples

See `examples/` directory for:
- Sample video files
- Example scrambling algorithms
- Test patterns
- Reference signals


