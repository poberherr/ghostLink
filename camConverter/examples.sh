#!/bin/bash

# Example usage scripts for Camera to Analog System
# Make this executable with: chmod +x examples.sh

echo "Camera to Analog Signal Converter - Usage Examples"
echo "=================================================="

# Example 1: Basic test
echo -e "\n1. BASIC TEST"
echo "Run this to test the system with default settings:"
echo "python3 test_system.py"

# Example 2: Standard operation
echo -e "\n2. STANDARD OPERATION"
echo "Terminal 1 (Camera Capture):"
echo "python3 camera_to_analog.py"
echo ""
echo "Terminal 2 (STM32 Reader):"
echo "python3 stm32_emulator_reader.py"

# Example 3: High performance mode
echo -e "\n3. HIGH PERFORMANCE MODE"
echo "Terminal 1 (60 Hz, 8 channels, no preview):"
echo "python3 camera_to_analog.py --sample-rate 60 --channels 8 --no-preview"
echo ""
echo "Terminal 2 (8 channels):"
echo "python3 stm32_emulator_reader.py --channels 8"

# Example 4: CSV logging mode
echo -e "\n4. CSV LOGGING MODE"
echo "Terminal 1 (CSV format with file logging):"
echo "python3 camera_to_analog.py --data-format csv --log-file capture_$(date +%Y%m%d_%H%M%S).log"
echo ""
echo "Terminal 2 (CSV format with data export):"
echo "python3 stm32_emulator_reader.py --data-format csv --output-file adc_data_$(date +%Y%m%d_%H%M%S).csv"

# Example 5: Real-time plotting
echo -e "\n5. REAL-TIME PLOTTING"
echo "Terminal 1:"
echo "python3 camera_to_analog.py"
echo ""
echo "Terminal 2 (with live plots):"
echo "python3 stm32_emulator_reader.py --plot"

# Example 6: Custom STM32 configuration
echo -e "\n6. CUSTOM STM32 CONFIGURATION"
echo "Terminal 1 (14-bit ADC, 5V range):"
echo "python3 camera_to_analog.py --adc-resolution 14 --voltage-range 5.0"
echo ""
echo "Terminal 2 (matching configuration):"
echo "python3 stm32_emulator_reader.py --adc-resolution 14 --voltage-range 5.0"

# Example 7: Multiple camera setup
echo -e "\n7. MULTIPLE CAMERA SETUP"
echo "Camera 0 -> FIFO 1:"
echo "python3 camera_to_analog.py --camera-id 0 --fifo-path /tmp/camera0.fifo"
echo ""
echo "Camera 1 -> FIFO 2:"
echo "python3 camera_to_analog.py --camera-id 1 --fifo-path /tmp/camera1.fifo"
echo ""
echo "Reader for FIFO 1:"
echo "python3 stm32_emulator_reader.py --fifo-path /tmp/camera0.fifo"

# Example 8: Development/debug mode
echo -e "\n8. DEVELOPMENT/DEBUG MODE"
echo "Terminal 1 (with verbose logging):"
echo "python3 camera_to_analog.py --log-file debug_capture.log --sample-rate 10"
echo ""
echo "Terminal 2 (with frequent logging):"
echo "python3 stm32_emulator_reader.py --log-interval 10 --output-file debug_data.csv"

# Installation reminder
echo -e "\nINSTALLATION REMINDER"
echo "===================="
echo "pip install -r requirements.txt"
echo "chmod +x *.py"

# Troubleshooting
echo -e "\nTROUBLESHOOTING"
echo "==============="
echo "Camera permission issues (macOS):"
echo "  System Preferences → Security & Privacy → Camera → Terminal (or your IDE)"
echo ""
echo "Camera in use error:"
echo "  Close other applications using camera (Zoom, Teams, etc.)"
echo ""
echo "FIFO permission error:"
echo "  sudo rm /tmp/camera_analog.fifo"
echo ""
echo "Import errors:"
echo "  pip install --upgrade opencv-python numpy matplotlib"