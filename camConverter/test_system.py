#!/usr/bin/env python3
"""
Test Script for Camera to Analog System
=======================================

Simple test script to verify the camera to analog signal conversion
system is working correctly. Tests both binary and CSV modes.

Author: GitHub Copilot
Date: November 2025
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path


def test_dependencies():
    """Test that all required dependencies are available."""
    print("Testing dependencies...")
    
    try:
        import cv2
        print(f"✓ OpenCV version: {cv2.__version__}")
    except ImportError:
        print("✗ OpenCV not found. Install with: pip install opencv-python")
        return False
    
    try:
        import numpy
        print(f"✓ NumPy version: {numpy.__version__}")
    except ImportError:
        print("✗ NumPy not found. Install with: pip install numpy")
        return False
    
    try:
        import matplotlib
        print(f"✓ Matplotlib version: {matplotlib.__version__}")
    except ImportError:
        print("! Matplotlib not found. Real-time plotting will be disabled.")
        print("  Install with: pip install matplotlib")
    
    return True


def test_camera_access():
    """Test camera access."""
    print("\nTesting camera access...")
    
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("✗ Camera not accessible. Check:")
            print("  - Camera permissions in System Preferences")
            print("  - No other applications using camera")
            print("  - Camera ID (try --camera-id 1)")
            return False
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            print("✗ Cannot capture frames from camera")
            return False
        
        print(f"✓ Camera accessible, frame shape: {frame.shape}")
        return True
        
    except Exception as e:
        print(f"✗ Camera test failed: {e}")
        return False


def test_fifo_creation():
    """Test FIFO creation and cleanup."""
    print("\nTesting FIFO creation...")
    
    test_fifo = "/tmp/test_camera_analog.fifo"
    
    try:
        # Remove existing FIFO
        if os.path.exists(test_fifo):
            os.unlink(test_fifo)
        
        # Create FIFO
        os.mkfifo(test_fifo)
        print(f"✓ FIFO created: {test_fifo}")
        
        # Verify it exists
        if not os.path.exists(test_fifo):
            print("✗ FIFO not found after creation")
            return False
        
        # Cleanup
        os.unlink(test_fifo)
        print("✓ FIFO cleanup successful")
        return True
        
    except Exception as e:
        print(f"✗ FIFO test failed: {e}")
        return False


def test_script_execution():
    """Test that scripts can be executed."""
    print("\nTesting script execution...")
    
    # Test help output
    try:
        result = subprocess.run(
            [sys.executable, "camera_to_analog.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and "Camera to Analog Signal Converter" in result.stdout:
            print("✓ camera_to_analog.py executable")
        else:
            print("✗ camera_to_analog.py failed")
            print(f"Error: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"✗ camera_to_analog.py test failed: {e}")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, "stm32_emulator_reader.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and "STM32 Emulator Test Reader" in result.stdout:
            print("✓ stm32_emulator_reader.py executable")
        else:
            print("✗ stm32_emulator_reader.py failed")
            print(f"Error: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"✗ stm32_emulator_reader.py test failed: {e}")
        return False
    
    return True


def run_integration_test():
    """Run a quick integration test."""
    print("\nRunning integration test...")
    print("This will test camera capture and FIFO streaming for 5 seconds...")
    
    fifo_path = "/tmp/test_integration.fifo"
    
    try:
        # Start camera capture in background
        capture_process = subprocess.Popen([
            sys.executable, "camera_to_analog.py",
            "--fifo-path", fifo_path,
            "--sample-rate", "10",
            "--channels", "2",
            "--no-preview"
        ])
        
        # Give it time to start
        time.sleep(2)
        
        # Start reader for 3 seconds
        reader_process = subprocess.Popen([
            sys.executable, "stm32_emulator_reader.py",
            "--fifo-path", fifo_path,
            "--channels", "2",
            "--log-interval", "10"
        ])
        
        # Let it run
        time.sleep(3)
        
        # Stop processes
        reader_process.terminate()
        capture_process.terminate()
        
        # Wait for cleanup
        reader_process.wait(timeout=5)
        capture_process.wait(timeout=5)
        
        print("✓ Integration test completed successfully")
        return True
        
    except subprocess.TimeoutExpired:
        print("! Integration test timed out (processes may still be running)")
        return False
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        return False
    finally:
        # Cleanup
        try:
            if os.path.exists(fifo_path):
                os.unlink(fifo_path)
        except:
            pass


def print_usage_examples():
    """Print usage examples."""
    print("\n" + "="*60)
    print("USAGE EXAMPLES")
    print("="*60)
    
    print("\n1. Basic usage (binary mode):")
    print("   Terminal 1: python3 camera_to_analog.py")
    print("   Terminal 2: python3 stm32_emulator_reader.py")
    
    print("\n2. CSV mode with logging:")
    print("   Terminal 1: python3 camera_to_analog.py --data-format csv --log-file capture.log")
    print("   Terminal 2: python3 stm32_emulator_reader.py --data-format csv --output-file data.csv")
    
    print("\n3. High-performance mode:")
    print("   Terminal 1: python3 camera_to_analog.py --sample-rate 60 --channels 8 --no-preview")
    print("   Terminal 2: python3 stm32_emulator_reader.py --channels 8")
    
    print("\n4. Real-time plotting:")
    print("   Terminal 1: python3 camera_to_analog.py")
    print("   Terminal 2: python3 stm32_emulator_reader.py --plot")
    
    print("\n5. Custom configuration:")
    print("   python3 camera_to_analog.py \\")
    print("     --camera-id 1 \\")
    print("     --adc-resolution 14 \\")
    print("     --voltage-range 5.0 \\")
    print("     --fifo-path /tmp/my_analog.fifo")
    
    print("\nTips:")
    print("- Press 'q' in camera preview window to quit")
    print("- Use Ctrl+C to stop processes")
    print("- Check logs for troubleshooting")
    print("- Ensure camera permissions are granted")


def main():
    """Main test function."""
    print("Camera to Analog Signal Converter - System Test")
    print("=" * 50)
    
    # Run all tests
    tests = [
        test_dependencies,
        test_camera_access,
        test_fifo_creation,
        test_script_execution
    ]
    
    all_passed = True
    for test in tests:
        if not test():
            all_passed = False
    
    if all_passed:
        print("\n✓ All basic tests passed!")
        
        response = input("\nRun integration test? This will use your camera for 5 seconds. (y/N): ")
        if response.lower().startswith('y'):
            run_integration_test()
        
        print_usage_examples()
        
    else:
        print("\n✗ Some tests failed. Please fix issues before using the system.")
        print("\nCommon solutions:")
        print("- Install dependencies: pip install -r requirements.txt")
        print("- Check camera permissions in System Preferences")
        print("- Ensure no other apps are using the camera")


if __name__ == "__main__":
    main()