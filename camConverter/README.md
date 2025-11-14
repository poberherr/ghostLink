# Camera to Analog Signal Converter

A real-time Python application that captures laptop camera feed, converts frames to analog-like signals, and streams them through UNIX FIFOs for STM32 emulator integration.

## Features

### Core Functionality
- **Real-time camera capture** using OpenCV with configurable frame rates
- **Image to analog conversion** with multi-channel support and configurable ADC resolution
- **UNIX FIFO streaming** for inter-process communication with emulators
- **Multi-threaded architecture** for non-blocking operation
- **Live camera preview** with OpenCV display window
- **Comprehensive logging** to console and optional log files

### Data Processing
- **Grayscale conversion** with configurable downsampling for performance
- **Multiple channel mapping** strategies:
  - Single channel (frame average)
  - 4-channel quadrants (default)
  - N-channel horizontal strips
- **Configurable ADC resolution** (8-16 bits)
- **Voltage scaling** (0-3.3V or custom range)

### Communication Formats
- **Binary format**: Little-endian uint16 (default, optimal for performance)
- **ASCII CSV format**: Human-readable with timestamps
- **UNIX FIFO**: Named pipes for reliable inter-process streaming

## Installation

### Prerequisites
- Python 3.10 or higher
- macOS or Linux (UNIX FIFO support required)
- Camera access permissions

### Setup
```bash
# Clone or download the project
cd /path/to/project

# Install dependencies
pip install -r requirements.txt

# Make scripts executable
chmod +x camera_to_analog.py
chmod +x stm32_emulator_reader.py
```

### Verify Installation
```bash
python3 -c "import cv2, numpy, matplotlib; print('All dependencies installed')"
```

## Usage

### Basic Usage

1. **Start the camera capture and streaming**:
   ```bash
   python3 camera_to_analog.py
   ```

2. **In another terminal, start the emulator reader**:
   ```bash
   python3 stm32_emulator_reader.py
   ```

3. **Stop with Ctrl+C** in either terminal

### Advanced Usage

#### Camera Capture with Custom Settings
```bash
# High resolution, 8 channels, CSV format
python3 camera_to_analog.py \
    --sample-rate 60 \
    --adc-resolution 14 \
    --channels 8 \
    --data-format csv \
    --log-file capture.log

# Different camera, custom FIFO location
python3 camera_to_analog.py \
    --camera-id 1 \
    --fifo-path /tmp/my_analog.fifo \
    --voltage-range 5.0 \
    --no-preview
```

#### Emulator Reader with Plotting
```bash
# Real-time plotting with data logging
python3 stm32_emulator_reader.py \
    --plot \
    --output-file adc_data.csv \
    --log-interval 50

# Different FIFO, CSV format
python3 stm32_emulator_reader.py \
    --fifo-path /tmp/my_analog.fifo \
    --data-format csv \
    --channels 8 \
    --adc-resolution 14
```

## Command Line Options

### camera_to_analog.py

| Option | Default | Description |
|--------|---------|-------------|
| `--camera-id` | 0 | Camera device ID |
| `--fifo-path` | `/tmp/camera_analog.fifo` | Path to FIFO |
| `--sample-rate` | 30 | Sample rate in Hz |
| `--adc-resolution` | 12 | ADC resolution in bits (8-16) |
| `--channels` | 4 | Number of analog channels |
| `--data-format` | binary | Data format: `binary` or `csv` |
| `--log-file` | None | Log file path |
| `--no-preview` | False | Disable camera preview |
| `--downsample-factor` | 8 | Frame downsampling factor |
| `--voltage-range` | 3.3 | ADC voltage range |

### stm32_emulator_reader.py

| Option | Default | Description |
|--------|---------|-------------|
| `--fifo-path` | `/tmp/camera_analog.fifo` | Path to FIFO |
| `--data-format` | binary | Data format: `binary` or `csv` |
| `--adc-resolution` | 12 | ADC resolution in bits |
| `--voltage-range` | 3.3 | ADC voltage range |
| `--channels` | 4 | Number of analog channels |
| `--plot` | False | Enable real-time plotting |
| `--plot-window-size` | 300 | Samples to display in plot |
| `--sample-rate` | 30 | Expected sample rate |
| `--log-interval` | 100 | Samples between log outputs |
| `--output-file` | None | Output CSV file path |

## Technical Details

### Architecture

The system uses a producer-consumer architecture with UNIX FIFOs:

```
Camera → Image Processing → FIFO → STM32 Emulator
  ↓           ↓              ↓         ↓
OpenCV → Grayscale/ADC → Named Pipe → Test Reader
         Multi-channel   (Binary)    Real-time Plot
```

### Threading Model

**Camera Capture Program**:
- **Main thread**: UI, logging, coordination
- **Capture thread**: OpenCV frame capture at target frame rate
- **Streaming thread**: FIFO writing with sample queuing

**Emulator Reader**:
- **Main thread**: Monitoring, statistics, control
- **Reader thread**: FIFO reading and sample buffering
- **Plot thread**: Real-time matplotlib visualization (optional)

### Data Flow

1. **Frame Capture**: OpenCV captures camera frames at specified rate
2. **Image Processing**:
   - Convert BGR → Grayscale
   - Downsample for performance (configurable factor)
   - Extract multiple channels based on strategy
3. **ADC Conversion**:
   - Map pixel intensity (0-255) → ADC counts (0 to 2^resolution-1)
   - Apply voltage scaling
4. **FIFO Streaming**:
   - Pack as binary uint16 little-endian or CSV
   - Write to named pipe with error handling
5. **Emulator Reading**:
   - Read from FIFO with appropriate format parsing
   - Buffer samples for analysis and plotting
   - Convert back to voltage for verification

### Channel Mapping Strategies

#### 4-Channel Quadrants (Default)
```
┌─────┬─────┐
│ Ch0 │ Ch1 │
├─────┼─────┤
│ Ch2 │ Ch3 │
└─────┴─────┘
```

#### N-Channel Horizontal Strips
```
┌─────────────┐ ← Channel 0
├─────────────┤ ← Channel 1
├─────────────┤ ← Channel 2
└─────────────┘ ← Channel N-1
```

#### Single Channel
- Average of entire frame

### Performance Considerations

- **Frame rate**: 30 Hz default, adjustable up to camera limits
- **Downsampling**: Reduces processing load (8x default)
- **Queue management**: Automatic frame dropping when processing falls behind
- **Memory usage**: Circular buffers with configurable sizes
- **FIFO blocking**: Writer waits for reader connection

## Integration Examples

### STM32CubeIDE Integration

```c
// Example STM32 code to read from external process
// (This would typically use UART, SPI, or other interface)

uint16_t adc_channels[4];
float voltages[4];

// Read ADC values from external interface
void read_analog_samples(void) {
    // Read 4 channels (8 bytes) of uint16 data
    // from UART, SPI, or other interface connected to FIFO
    
    for (int i = 0; i < 4; i++) {
        voltages[i] = (adc_channels[i] / 4095.0f) * 3.3f;
    }
}
```

### socat Integration

Bridge FIFO to virtual serial port:
```bash
# Create virtual serial port pair
socat -d -d pty,raw,echo=0 pty,raw,echo=0

# Bridge FIFO to PTY
socat /tmp/camera_analog.fifo /dev/pts/X
```

### TCP Socket Alternative

Modify the FIFO classes to use TCP sockets for network streaming:
```python
# Replace os.mkfifo() with socket.socket()
# Replace os.open() with socket.accept()
# Allows remote emulator connections
```

## Troubleshooting

### Common Issues

1. **Permission Denied on FIFO**:
   ```bash
   sudo rm /tmp/camera_analog.fifo
   python3 camera_to_analog.py
   ```

2. **Camera Not Found**:
   ```bash
   # List available cameras
   ls /dev/video*
   python3 camera_to_analog.py --camera-id 1
   ```

3. **Import Error (matplotlib)**:
   ```bash
   pip install matplotlib
   # Or run reader without plotting
   python3 stm32_emulator_reader.py --no-plot
   ```

4. **FIFO Blocking**:
   - Always start reader before or simultaneously with capture
   - Use separate terminals for each process

### Debug Mode

Enable verbose logging:
```bash
python3 camera_to_analog.py --log-file debug.log
tail -f debug.log
```

### Performance Monitoring

Check system resources:
```bash
# Monitor CPU usage
top -p $(pgrep python)

# Monitor FIFO
ls -la /tmp/camera_analog.fifo
```

## Sample Output

### Camera Capture Console
```
2025-11-13 14:30:15 - INFO - Initializing Camera to Analog Converter
2025-11-13 14:30:15 - INFO - Camera initialized: 0
2025-11-13 14:30:15 - INFO - Created FIFO: /tmp/camera_analog.fifo
2025-11-13 14:30:16 - INFO - FIFO reader connected
2025-11-13 14:30:16 - INFO - Started capture and streaming threads
2025-11-13 14:30:17 - INFO - FPS: 29.8, ADC: [1823, 1456, 2001, 1678], Voltage: ['1.49V', '1.19V', '1.64V', '1.37V']
```

### Emulator Reader Console
```
Opening FIFO: /tmp/camera_analog.fifo
FIFO opened successfully
Started reading from FIFO (format: binary)
[14:30:17.123] ADC: [1823, 1456, 2001, 1678] | Voltage: ['1.487V', '1.188V', '1.635V', '1.371V'] | Samples: 100 | Errors: 0
```

## License

MIT License - See source files for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test with your specific STM32 setup
4. Submit a pull request with detailed description

## Future Enhancements

- **Network streaming** (TCP/UDP support)
- **Multiple camera support**
- **Custom pixel sampling patterns**
- **Real-time filtering** (low-pass, high-pass)
- **STM32 HAL integration examples**
- **Performance optimization** for higher frame rates
- **Configuration file support** (YAML/JSON)