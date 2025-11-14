#!/usr/bin/env python3
"""
Analog Signal to Video Viewer/Decoder
======================================

Reads analog signal files (.analog) and decodes them back to video for visualization.
Useful for verifying analog signal generation and testing scrambling/descrambling.

Features:
- Reads .analog files with metadata
- Decodes composite signal back to frames
- Real-time or file output
- Waveform visualization
- Signal quality metrics

Author: AI Assistant
Date: November 2025
"""

import os
import sys
import time
import struct
import logging
import argparse
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
import json

try:
    import cv2
except ImportError:
    print("Error: opencv-python is required. Install with: uv add opencv-python")
    sys.exit(1)

try:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available, waveform plotting disabled")


class AnalogFileReader:
    """Reads analog signal files."""
    
    MAGIC = b'ANLG'
    
    def __init__(self, filename: str):
        self.filename = filename
        self.file = None
        self.metadata = None
        self.frames_read = 0
        
    def open(self) -> bool:
        """Open file and read header."""
        try:
            if not Path(self.filename).exists():
                logging.error(f"File not found: {self.filename}")
                return False
            
            self.file = open(self.filename, 'rb')
            
            # Read and verify magic number
            magic = self.file.read(4)
            if magic != self.MAGIC:
                logging.error(f"Invalid file format (magic: {magic})")
                return False
            
            # Read version
            version = struct.unpack('<I', self.file.read(4))[0]
            if version != 1:
                logging.error(f"Unsupported version: {version}")
                return False
            
            # Read metadata
            metadata_len = struct.unpack('<I', self.file.read(4))[0]
            metadata_bytes = self.file.read(metadata_len)
            self.metadata = json.loads(metadata_bytes.decode('utf-8'))
            
            logging.info(f"Opened analog file: {self.filename}")
            logging.info(f"Format: {self.metadata['standard']}, "
                        f"{self.metadata['resolution'][0]}x{self.metadata['resolution'][1]}, "
                        f"{self.metadata['fps']:.2f} fps")
            logging.info(f"Sample rate: {self.metadata['sample_rate']/1e6:.1f} MHz")
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to open file: {e}")
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        """Read one frame of analog signal."""
        if not self.file:
            return None
        
        try:
            samples_per_frame = self.metadata['samples_per_frame']
            bytes_to_read = samples_per_frame * 4  # float32
            
            data = self.file.read(bytes_to_read)
            if len(data) < bytes_to_read:
                return None  # EOF
            
            signal = np.frombuffer(data, dtype=np.float32)
            self.frames_read += 1
            return signal
            
        except Exception as e:
            logging.error(f"Error reading frame: {e}")
            return None
    
    def close(self):
        """Close file."""
        if self.file:
            self.file.close()
            logging.info(f"Read {self.frames_read} frames")


class CompositeDecoder:
    """Decodes composite analog signal back to video frames."""
    
    def __init__(self, metadata: Dict[str, Any]):
        self.metadata = metadata
        self.sample_rate = metadata['sample_rate']
        self.samples_per_line = metadata['samples_per_line']
        self.samples_per_frame = metadata['samples_per_frame']
        self.lines_per_frame = metadata['lines_per_frame']
        self.resolution = tuple(metadata['resolution'])
        self.active_lines = metadata.get('active_lines', self.resolution[1])
        
        # Voltage levels
        self.sync_tip = metadata['voltage_levels']['sync_tip']
        self.blanking = metadata['voltage_levels']['blanking']
        self.black = metadata['voltage_levels']['black']
        self.white = metadata['voltage_levels']['white']
        
        # Calculate timing
        self._calculate_timing()
        
    def _calculate_timing(self):
        """Calculate sample positions for line decoding."""
        # Approximate timing based on standard
        # H-sync is ~4.7μs, back porch ~4.7μs
        h_sync_us = 4.7
        back_porch_us = 4.7
        
        self.h_sync_samples = int(h_sync_us * 1e-6 * self.sample_rate)
        self.back_porch_samples = int(back_porch_us * 1e-6 * self.sample_rate)
        
        # Active video starts after sync + back porch
        self.active_start = self.h_sync_samples + self.back_porch_samples
        
        # Calculate active video length
        total_line = self.samples_per_line
        front_porch_estimate = 50  # rough estimate
        self.active_length = total_line - self.active_start - front_porch_estimate
        
        logging.debug(f"Decode timing: active starts at sample {self.active_start}, "
                     f"length {self.active_length}")
    
    def extract_line(self, signal: np.ndarray, line_num: int) -> np.ndarray:
        """Extract one horizontal line from the signal."""
        start = line_num * self.samples_per_line
        end = start + self.samples_per_line
        
        if end > len(signal):
            return None
        
        line = signal[start:end]
        
        # Extract active video portion
        active = line[self.active_start:self.active_start + self.active_length]
        
        # Normalize from voltage to 0-255
        # Clip to black-white range
        active = np.clip(active, self.black, self.white)
        normalized = (active - self.black) / (self.white - self.black)
        pixels = (normalized * 255).astype(np.uint8)
        
        return pixels
    
    def decode_frame(self, signal: np.ndarray) -> np.ndarray:
        """Decode complete frame from analog signal."""
        width, height = self.resolution
        
        # Calculate vertical blanking
        vblank_lines = self.lines_per_frame - self.active_lines
        vblank_top = vblank_lines // 2
        
        # Allocate output frame
        frame = np.zeros((height, width), dtype=np.uint8)
        
        # Decode active lines
        for i in range(self.active_lines):
            line_num = vblank_top + i
            line_pixels = self.extract_line(signal, line_num)
            
            if line_pixels is None:
                break
            
            # Resample to target width if needed
            if len(line_pixels) != width:
                x_old = np.linspace(0, 1, len(line_pixels))
                x_new = np.linspace(0, 1, width)
                line_pixels = np.interp(x_new, x_old, line_pixels).astype(np.uint8)
            
            frame[i, :] = line_pixels
        
        # Convert to BGR for OpenCV
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        
        return frame_bgr
    
    def analyze_sync(self, signal: np.ndarray) -> Dict[str, Any]:
        """Analyze sync pulse characteristics."""
        # Find sync pulses (values below blanking level)
        sync_threshold = (self.sync_tip + self.blanking) / 2
        sync_mask = signal < sync_threshold
        
        # Count sync pulses (h-syncs)
        sync_edges = np.diff(sync_mask.astype(int))
        sync_count = np.sum(sync_edges > 0)
        
        # Measure sync levels
        sync_values = signal[sync_mask]
        
        stats = {
            'sync_pulses': sync_count,
            'expected_lines': self.lines_per_frame,
            'sync_level_min': float(np.min(sync_values)) if len(sync_values) > 0 else 0,
            'sync_level_mean': float(np.mean(sync_values)) if len(sync_values) > 0 else 0,
            'signal_min': float(np.min(signal)),
            'signal_max': float(np.max(signal)),
        }
        
        return stats


class AnalogViewer:
    """Main viewer application."""
    
    def __init__(self, args):
        self.args = args
        self._setup_logging()
        
        # Open analog file
        self.reader = AnalogFileReader(args.input)
        if not self.reader.open():
            sys.exit(1)
        
        # Create decoder
        self.decoder = CompositeDecoder(self.reader.metadata)
        
        # Video writer if saving
        self.video_writer = None
        if args.output:
            self._setup_video_writer()
        
    def _setup_logging(self):
        """Setup logging."""
        level = logging.DEBUG if self.args.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    def _setup_video_writer(self):
        """Setup video file writer."""
        width, height = self.decoder.resolution
        fps = self.reader.metadata['fps']
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(
            self.args.output, fourcc, fps, (width, height)
        )
        logging.info(f"Saving video to: {self.args.output}")
    
    def view(self):
        """Main viewing loop."""
        logging.info("Starting analog signal viewer")
        
        frame_count = 0
        start_time = time.time()
        fps = self.reader.metadata['fps']
        frame_delay = int(1000 / fps) if not self.args.fast else 1
        
        # Waveform plotting setup
        if self.args.show_waveform and MATPLOTLIB_AVAILABLE:
            self._setup_waveform_plot()
        
        try:
            while True:
                # Read analog frame
                signal = self.reader.read_frame()
                if signal is None:
                    logging.info("End of file")
                    break
                
                # Decode to video frame
                frame = self.decoder.decode_frame(signal)
                
                frame_count += 1
                
                # Show frame
                if self.args.display:
                    cv2.imshow("Decoded Video", frame)
                    key = cv2.waitKey(frame_delay) & 0xFF
                    if key == ord('q'):
                        logging.info("Quit by user")
                        break
                    elif key == ord(' '):
                        logging.info("Paused (press space to continue)")
                        cv2.waitKey(0)
                
                # Save frame
                if self.video_writer:
                    self.video_writer.write(frame)
                
                # Show waveform periodically
                if self.args.show_waveform and MATPLOTLIB_AVAILABLE and frame_count % 30 == 1:
                    self._update_waveform(signal)
                
                # Analyze sync if requested
                if self.args.analyze and frame_count % 30 == 0:
                    stats = self.decoder.analyze_sync(signal)
                    logging.info(f"Frame {frame_count}: {stats}")
                
                # Progress
                if frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    processing_fps = frame_count / elapsed
                    logging.info(f"Processed {frame_count} frames @ {processing_fps:.1f} fps")
            
            # Summary
            elapsed = time.time() - start_time
            logging.info(f"\nPlayback complete:")
            logging.info(f"  Frames: {frame_count}")
            logging.info(f"  Duration: {frame_count / fps:.2f}s")
            logging.info(f"  Processing time: {elapsed:.1f}s")
            
        except KeyboardInterrupt:
            logging.info("\nInterrupted by user")
        except Exception as e:
            logging.error(f"Viewer error: {e}", exc_info=True)
        finally:
            self.reader.close()
            if self.video_writer:
                self.video_writer.release()
            if self.args.display:
                cv2.destroyAllWindows()
    
    def _setup_waveform_plot(self):
        """Setup matplotlib waveform display."""
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(12, 4))
        self.ax.set_xlabel('Sample')
        self.ax.set_ylabel('Voltage')
        self.ax.set_title('Analog Signal Waveform (One Line)')
        self.ax.grid(True, alpha=0.3)
        self.line, = self.ax.plot([], [], 'b-', linewidth=0.5)
        
        # Add voltage level references
        self.ax.axhline(self.decoder.sync_tip, color='r', linestyle='--', 
                       alpha=0.5, label='Sync tip')
        self.ax.axhline(self.decoder.blanking, color='g', linestyle='--', 
                       alpha=0.5, label='Blanking')
        self.ax.axhline(self.decoder.black, color='k', linestyle='--', 
                       alpha=0.5, label='Black')
        self.ax.axhline(self.decoder.white, color='w', linestyle='--', 
                       alpha=0.5, label='White')
        self.ax.legend()
    
    def _update_waveform(self, signal: np.ndarray):
        """Update waveform plot with one line."""
        # Extract first active line for display
        samples_per_line = self.decoder.samples_per_line
        line = signal[:samples_per_line]
        
        # Update plot
        x = np.arange(len(line))
        self.line.set_data(x, line)
        self.ax.relim()
        self.ax.autoscale_view()
        plt.pause(0.001)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="View and decode analog signal files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('input', type=str,
                       help='Input analog signal file (.analog)')
    parser.add_argument('--output', type=str,
                       help='Output video file (optional)')
    parser.add_argument('--display', action='store_true', default=True,
                       help='Display video in window')
    parser.add_argument('--no-display', action='store_true',
                       help='Disable video display (for batch processing)')
    parser.add_argument('--show-waveform', action='store_true',
                       help='Show analog waveform plot (requires matplotlib)')
    parser.add_argument('--analyze', action='store_true',
                       help='Analyze and log signal characteristics')
    parser.add_argument('--fast', action='store_true',
                       help='Play as fast as possible (no frame delay)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Handle no-display flag
    if args.no_display:
        args.display = False
    
    return args


def main():
    """Main entry point."""
    args = parse_arguments()
    
    viewer = AnalogViewer(args)
    viewer.view()


if __name__ == "__main__":
    main()


