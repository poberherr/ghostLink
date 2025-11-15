# Quick Start Guide - Analog Video Scrambler

## 🎯 Goal
Convert video to realistic analog signals for scrambling experiments.

## ⚡ 3-Minute Test

```bash
cd camConverter

# 1. Create test video (3 seconds, 90 frames)
uv run create_test_video.py

# 2. Convert to analog signal
uv run video_to_analog.py test_pattern.mp4 test_pattern.analog

# 3. View the analog signal
uv run analog_to_video.py test_pattern.analog --display

# 4. Scramble it
uv run analog_scrambler.py test_pattern.analog scrambled.analog --method line_rotation

# 5. View scrambled result
uv run analog_to_video.py scrambled.analog --display
```

## 📁 What You Have Now

```
camConverter/
├── video_to_analog.py      ← Video → Analog converter
├── analog_to_video.py      ← Analog → Video viewer
├── analog_scrambler.py     ← Scrambler with 6+ methods
├── create_test_video.py    ← Test pattern generator
├── test_pipeline.sh        ← Automated test script
│
├── README_ANALOG.md        ← Comprehensive guide
├── ANALOG_PIPELINE.md      ← Technical details
└── QUICKSTART.md          ← This file
```

## 🎨 Try Different Scrambling Methods

```bash
# Line rotation (horizontal shift)
uv run analog_scrambler.py test_pattern.analog out.analog \
    --method line_rotation --shift 100

# Sync suppression (remove sync pulses)
uv run analog_scrambler.py test_pattern.analog out.analog \
    --method sync_suppression --level 0.7

# Line shuffle (scramble vertical order)
uv run analog_scrambler.py test_pattern.analog out.analog \
    --method line_shuffle --blocks 20

# Line inversion (flip brightness)
uv run analog_scrambler.py test_pattern.analog out.analog \
    --method line_inversion --pattern alternating

# Combo (multiple techniques)
uv run analog_scrambler.py test_pattern.analog out.analog \
    --method combo
```

## 🔬 Advanced: View with Waveform

```bash
# See the actual analog waveform
uv run analog_to_video.py test_pattern.analog \
    --display --show-waveform --analyze
```

This shows:
- Video display window
- Waveform plot (voltage vs time)
- Sync pulse detection
- Signal quality metrics

## 📹 Use Your Own Video

```bash
# From file
uv run video_to_analog.py your_video.mp4 output.analog

# From webcam (10 seconds)
uv run video_to_analog.py 0 webcam.analog --max-frames 300 --preview
```

## 💡 Key Concepts

### .analog File Format
- Binary file with voltage samples
- 10 MHz sampling rate (10 million samples/second)
- Float32 values (-0.3V to 0.7V range)
- Includes metadata (resolution, frame rate, etc.)

### Signal Structure
- **1D temporal waveform** (like oscilloscope view)
- H-sync pulses every 63.5 microseconds
- 525 lines per frame (NTSC)
- Bandwidth limited to 4.2 MHz

### File Sizes
- 3 seconds video ≈ 114 MB analog file
- 1 minute video ≈ 2.4 GB analog file
- **Tip**: Use shorter clips for iteration!

## 🎓 Next Steps

1. **Read** `README_ANALOG.md` for complete documentation
2. **Modify** `analog_scrambler.py` to add your own methods
3. **Build** a descrambler to reverse your scrambling
4. **Test** recovery quality with different techniques

## 🆘 Need Help?

Check these files:
- `README_ANALOG.md` - Full documentation
- `ANALOG_PIPELINE.md` - Technical details
- All scripts have `--help` flags

## ✅ You're Ready!

Everything is set up for analog scrambling experiments:
- ✅ Preprocessing pipeline complete
- ✅ Viewer/decoder working
- ✅ Scrambler template with examples
- ✅ Test suite ready

**Focus on scrambling algorithms - the hard part is done!** 🚀

