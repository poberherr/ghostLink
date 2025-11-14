#!/usr/bin/env python3
"""
Camera to Analog Signal Converter
==================================

Captures laptop camera feed, converts frames to analog-like signals,
and streams them to a UNIX FIFO for STM32 emulator integration.

Features:
- Real-time camera capture with OpenCV
- Grayscale to ADC conversion with configurable resolution
- Multi-threaded non-blocking operation
- UNIX FIFO streaming (binary/ASCII formats)
- Live preview window
- Comprehensive logging

Author: GitHub Copilot
Date: November 2025
"""

import os
import sys
import time
import signal
import struct
import logging
import argparse
import threading
from queue import Queue, Empty
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np


@dataclass
class Config:
    """Configuration class for the camera to analog converter."""
    camera_id: int = 0
    fifo_path: str = "/tmp/camera_analog.fifo"
    sample_rate: int = 30  # Hz
    adc_resolution: int = 12  # bits
    channels: int = 4  # number of analog channels
    data_format: str = "binary"  # "binary" or "csv"
    log_file: Optional[str] = None
    preview: bool = True
    downsample_factor: int = 8  # reduce frame resolution for sampling
    voltage_range: float = 3.3  # volts
    test_mode: bool = False  # use synthetic data instead of camera
    
    @property
    def max_adc_value(self) -> int:
        """Maximum ADC value based on resolution."""
        return (2 ** self.adc_resolution) - 1
    
    @property
    def frame_period(self) -> float:
        """Time between frames in seconds."""
        return 1.0 / self.sample_rate


class CameraCapture:
    """Handles camera capture operations."""
    
    def __init__(self, config: Config):
        self.config = config
        self.cap = None
        self.frame_queue = Queue(maxsize=5)
        self.running = False
        
    def initialize_camera(self) -> bool:
        """Initialize the camera."""
        try:
            if self.config.test_mode:
                logging.info("Running in test mode - using synthetic camera data")
                return True
            
            logging.info(f"Attempting to open camera {self.config.camera_id}")
            self.cap = cv2.VideoCapture(self.config.camera_id)
            
            if not self.cap.isOpened():
                logging.error(f"Cannot open camera {self.config.camera_id}")
                logging.error("Possible causes:")
                logging.error("- Camera permissions not granted (check System Preferences -> Security & Privacy -> Camera)")
                logging.error("- Another application is using the camera")
                logging.error("- Camera hardware not available")
                logging.error("\nTry running with --test-mode to use synthetic data")
                return False
                
            # Test frame capture
            ret, test_frame = self.cap.read()
            if not ret:
                logging.error("Camera opened but cannot capture frames")
                logging.error("This usually indicates a permission issue on macOS")
                logging.error("Try running with --test-mode to use synthetic data")
                self.cap.release()
                return False
            
            logging.info(f"Test frame captured successfully: {test_frame.shape}")
                
            # Set camera properties for better performance
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            # Get actual properties
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            logging.info(f"Camera initialized: {self.config.camera_id}")
            logging.info(f"Resolution: {width}x{height}, FPS: {fps}")
            return True
            
        except Exception as e:
            logging.error(f"Camera initialization failed: {e}")
            logging.error("Try running with --test-mode to use synthetic data")
            return False
    
    def capture_loop(self):
        """Main capture loop running in separate thread."""
        self.running = True
        frame_time = self.config.frame_period
        frame_counter = 0
        
        while self.running:
            start_time = time.time()
            
            if self.config.test_mode:
                # Generate synthetic frame for testing
                frame = self.generate_test_frame(frame_counter)
                ret = True
            else:
                ret, frame = self.cap.read()
            
            if not ret:
                logging.warning("Failed to capture frame")
                if self.config.test_mode:
                    break  # Should not happen in test mode
                time.sleep(0.1)  # Wait a bit before retrying
                continue
                
            # Put frame in queue (non-blocking)
            try:
                self.frame_queue.put_nowait(frame)
            except:
                # Queue full, drop oldest frame
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.put_nowait(frame)
                except:
                    pass
            
            frame_counter += 1
            
            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_time - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    def generate_test_frame(self, frame_counter: int) -> np.ndarray:
        """Generate a synthetic test frame."""
        # Create a 640x480 color frame with animated pattern
        height, width = 480, 640
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Create animated gradient pattern
        phase = frame_counter * 0.1
        for y in range(height):
            for x in range(width):
                # Create moving wave pattern
                value = int(128 + 127 * np.sin((x + y + phase * 20) * 0.02))
                frame[y, x] = [value, value//2, (255-value)]
        
        # Add some moving shapes
        center_x = int(width//2 + 100 * np.cos(phase))
        center_y = int(height//2 + 50 * np.sin(phase * 1.5))
        cv2.circle(frame, (center_x, center_y), 50, (255, 255, 255), -1)
        
        return frame
    
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame."""
        try:
            return self.frame_queue.get_nowait()
        except Empty:
            return None
    
    def stop(self):
        """Stop capture."""
        self.running = False
        if self.cap:
            self.cap.release()


class AnalogConverter:
    """Converts image frames to analog signals."""
    
    def __init__(self, config: Config):
        self.config = config
        
    def frame_to_analog(self, frame: np.ndarray) -> List[int]:
        """Convert frame to analog ADC values."""
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Downsample for performance
        height, width = gray.shape
        step_y = max(1, height // self.config.downsample_factor)
        step_x = max(1, width // self.config.downsample_factor)
        downsampled = gray[::step_y, ::step_x]
        
        # Generate multiple channels from different regions
        channels = []
        h, w = downsampled.shape
        
        if self.config.channels == 1:
            # Single channel: average of entire frame
            avg_intensity = np.mean(downsampled)
            adc_value = int((avg_intensity / 255.0) * self.config.max_adc_value)
            channels.append(adc_value)
            
        elif self.config.channels == 4:
            # Four channels: quadrants
            h_mid, w_mid = h // 2, w // 2
            quadrants = [
                downsampled[:h_mid, :w_mid],      # Top-left
                downsampled[:h_mid, w_mid:],      # Top-right
                downsampled[h_mid:, :w_mid],      # Bottom-left
                downsampled[h_mid:, w_mid:]       # Bottom-right
            ]
            
            for quad in quadrants:
                avg_intensity = np.mean(quad)
                adc_value = int((avg_intensity / 255.0) * self.config.max_adc_value)
                channels.append(adc_value)
                
        else:
            # N channels: horizontal strips
            strip_height = h // self.config.channels
            for i in range(self.config.channels):
                start_y = i * strip_height
                end_y = start_y + strip_height if i < self.config.channels - 1 else h
                strip = downsampled[start_y:end_y, :]
                avg_intensity = np.mean(strip)
                adc_value = int((avg_intensity / 255.0) * self.config.max_adc_value)
                channels.append(adc_value)
        
        return channels
    
    def adc_to_voltage(self, adc_value: int) -> float:
        """Convert ADC value to voltage."""
        return (adc_value / self.config.max_adc_value) * self.config.voltage_range


class FIFOStreamer:
    """Handles FIFO streaming operations."""
    
    def __init__(self, config: Config):
        self.config = config
        self.fifo_fd = None
        self.sample_queue = Queue()
        self.running = False
        
    def create_fifo(self) -> bool:
        """Create the FIFO if it doesn't exist."""
        try:
            fifo_path = Path(self.config.fifo_path)
            
            # Remove existing FIFO
            if fifo_path.exists():
                fifo_path.unlink()
                
            # Create new FIFO
            os.mkfifo(str(fifo_path))
            logging.info(f"Created FIFO: {fifo_path}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to create FIFO: {e}")
            return False
    
    def open_fifo(self) -> bool:
        """Open FIFO for writing."""
        try:
            logging.info(f"Waiting for reader on FIFO: {self.config.fifo_path}")
            # This will block until a reader connects
            self.fifo_fd = os.open(self.config.fifo_path, os.O_WRONLY)
            logging.info("FIFO reader connected")
            return True
            
        except Exception as e:
            logging.error(f"Failed to open FIFO: {e}")
            return False
    
    def write_samples(self, samples: List[int], timestamp: float):
        """Write samples to FIFO."""
        try:
            if self.config.data_format == "binary":
                # Pack as little-endian uint16
                data = struct.pack(f"<{len(samples)}H", *samples)
                os.write(self.fifo_fd, data)
                
            elif self.config.data_format == "csv":
                # Write as CSV line
                csv_line = f"{timestamp:.6f}," + ",".join(map(str, samples)) + "\n"
                os.write(self.fifo_fd, csv_line.encode())
                
        except Exception as e:
            logging.error(f"Failed to write to FIFO: {e}")
            raise
    
    def streaming_loop(self):
        """Main streaming loop running in separate thread."""
        self.running = True
        
        while self.running:
            try:
                # Get samples from queue (blocking with timeout)
                samples, timestamp = self.sample_queue.get(timeout=1.0)
                self.write_samples(samples, timestamp)
                
            except Empty:
                continue
            except Exception as e:
                logging.error(f"Streaming error: {e}")
                break
    
    def queue_samples(self, samples: List[int], timestamp: float):
        """Queue samples for writing."""
        try:
            self.sample_queue.put_nowait((samples, timestamp))
        except:
            # Queue full, drop samples
            logging.warning("Sample queue full, dropping samples")
    
    def stop(self):
        """Stop streaming."""
        self.running = False
        if self.fifo_fd:
            os.close(self.fifo_fd)


class CameraToAnalogConverter:
    """Main application class."""
    
    def __init__(self, config: Config):
        self.config = config
        self.camera = CameraCapture(config)
        self.converter = AnalogConverter(config)
        self.streamer = FIFOStreamer(config)
        self.running = False
        
        # Setup logging
        self.setup_logging()
        
        # Signal handling for clean shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def setup_logging(self):
        """Setup logging configuration."""
        log_format = "%(asctime)s - %(levelname)s - %(message)s"
        
        # Console logging
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        
        # File logging if specified
        if self.config.log_file:
            file_handler = logging.FileHandler(self.config.log_file)
            file_handler.setFormatter(logging.Formatter(log_format))
            logging.getLogger().addHandler(file_handler)
    
    def signal_handler(self, sig, frame):
        """Handle shutdown signals."""
        logging.info("Received shutdown signal")
        self.stop()
    
    def initialize(self) -> bool:
        """Initialize all components."""
        logging.info("Initializing Camera to Analog Converter")
        logging.info(f"Configuration: {self.config}")
        
        # Initialize camera
        if not self.camera.initialize_camera():
            return False
        
        # Create FIFO
        if not self.streamer.create_fifo():
            return False
        
        # Open FIFO (blocks until reader connects)
        if not self.streamer.open_fifo():
            return False
        
        return True
    
    def run(self):
        """Main application loop."""
        self.running = True
        
        # Start threads
        camera_thread = threading.Thread(target=self.camera.capture_loop, daemon=True)
        streaming_thread = threading.Thread(target=self.streamer.streaming_loop, daemon=True)
        
        camera_thread.start()
        streaming_thread.start()
        
        logging.info("Started capture and streaming threads")
        
        frame_count = 0
        start_time = time.time()
        
        try:
            while self.running:
                # Get latest frame
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                
                # Convert to analog signals
                timestamp = time.time()
                samples = self.converter.frame_to_analog(frame)
                
                # Queue for FIFO streaming
                self.streamer.queue_samples(samples, timestamp)
                
                # Logging
                frame_count += 1
                if frame_count % 30 == 0:  # Log every 30 frames
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    voltages = [self.converter.adc_to_voltage(s) for s in samples]
                    logging.info(f"FPS: {fps:.1f}, ADC: {samples}, Voltage: {[f'{v:.2f}V' for v in voltages]}")
                
                # Show preview if enabled
                if self.config.preview:
                    cv2.imshow("Camera Feed", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                
        except KeyboardInterrupt:
            logging.info("Interrupted by user")
        except Exception as e:
            logging.error(f"Application error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the application."""
        if not self.running:
            return
            
        logging.info("Stopping application...")
        self.running = False
        
        # Stop components
        self.camera.stop()
        self.streamer.stop()
        
        # Cleanup
        if self.config.preview:
            cv2.destroyAllWindows()
        
        # Remove FIFO
        try:
            os.unlink(self.config.fifo_path)
        except:
            pass
        
        logging.info("Application stopped")


def parse_arguments() -> Config:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Camera to Analog Signal Converter",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("--camera-id", type=int, default=0,
                       help="Camera device ID")
    parser.add_argument("--fifo-path", type=str, default="/tmp/camera_analog.fifo",
                       help="Path to FIFO")
    parser.add_argument("--sample-rate", type=int, default=30,
                       help="Sample rate in Hz")
    parser.add_argument("--adc-resolution", type=int, default=12,
                       help="ADC resolution in bits")
    parser.add_argument("--channels", type=int, default=4,
                       help="Number of analog channels")
    parser.add_argument("--data-format", choices=["binary", "csv"], default="binary",
                       help="FIFO data format")
    parser.add_argument("--log-file", type=str,
                       help="Log file path")
    parser.add_argument("--no-preview", action="store_true",
                       help="Disable camera preview")
    parser.add_argument("--test-mode", action="store_true",
                       help="Use synthetic test data instead of camera")
    parser.add_argument("--downsample-factor", type=int, default=8,
                       help="Frame downsampling factor")
    parser.add_argument("--voltage-range", type=float, default=3.3,
                       help="ADC voltage range")
    
    args = parser.parse_args()
    
    return Config(
        camera_id=args.camera_id,
        fifo_path=args.fifo_path,
        sample_rate=args.sample_rate,
        adc_resolution=args.adc_resolution,
        channels=args.channels,
        data_format=args.data_format,
        log_file=args.log_file,
        preview=not args.no_preview,
        downsample_factor=args.downsample_factor,
        voltage_range=args.voltage_range,
        test_mode=args.test_mode
    )


def main():
    """Main entry point."""
    config = parse_arguments()
    app = CameraToAnalogConverter(config)
    
    if not app.initialize():
        sys.exit(1)
    
    app.run()


if __name__ == "__main__":
    main()