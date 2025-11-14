#!/usr/bin/env python3
"""
Video to Analog Signal Converter
=================================

Converts video input (file or webcam) to simulated composite analog signals
(NTSC or PAL format) for use in scrambling/descrambling experiments.

This generates a 1D temporal waveform that mimics real composite video:
- Horizontal and vertical sync pulses
- Blanking intervals
- Bandwidth-limited luminance signal
- Proper voltage levels (sync tip to peak white)

Output format is a binary file containing the continuous analog waveform
with metadata for frame/line boundaries.

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
from dataclasses import dataclass, asdict
from datetime import datetime
import json

try:
    import cv2
except ImportError:
    print("Error: opencv-python is required. Install with: uv add opencv-python")
    sys.exit(1)


@dataclass
class AnalogStandard:
    """Defines the analog video standard (NTSC or PAL)."""
    name: str
    lines_per_frame: int
    fps: float
    line_duration_us: float  # microseconds
    h_sync_duration_us: float
    front_porch_us: float
    back_porch_us: float
    active_video_us: float
    
    # Voltage levels (normalized 0-1 scale)
    sync_tip: float = -0.3
    blanking_level: float = 0.0
    black_level: float = 0.05
    white_level: float = 0.7
    
    @property
    def frame_duration(self) -> float:
        """Duration of one frame in seconds."""
        return 1.0 / self.fps
    
    @property
    def line_duration(self) -> float:
        """Duration of one line in seconds."""
        return self.line_duration_us * 1e-6


# Standard definitions
NTSC = AnalogStandard(
    name="NTSC",
    lines_per_frame=525,
    fps=29.97,
    line_duration_us=63.556,
    h_sync_duration_us=4.7,
    front_porch_us=1.5,
    back_porch_us=4.7,
    active_video_us=52.656
)

PAL = AnalogStandard(
    name="PAL",
    lines_per_frame=625,
    fps=25.0,
    line_duration_us=64.0,
    h_sync_duration_us=4.7,
    front_porch_us=1.65,
    back_porch_us=5.7,
    active_video_us=51.95
)


@dataclass
class AnalogConfig:
    """Configuration for analog signal generation."""
    standard: AnalogStandard
    sample_rate: int = 10_000_000  # 10 MHz sampling
    resolution: Tuple[int, int] = (640, 480)  # Source video resolution
    active_lines: int = 480  # Lines containing actual video
    bandwidth_mhz: float = 4.2  # Luminance bandwidth (NTSC ~4.2 MHz)
    add_noise: bool = False
    noise_amplitude: float = 0.02
    
    @property
    def samples_per_line(self) -> int:
        """Number of samples in one horizontal line."""
        return int(self.standard.line_duration * self.sample_rate)
    
    @property
    def samples_per_frame(self) -> int:
        """Number of samples in one complete frame."""
        return self.samples_per_line * self.standard.lines_per_frame
    
    @property
    def active_samples_per_line(self) -> int:
        """Number of samples containing active video per line."""
        return int(self.standard.active_video_us * 1e-6 * self.sample_rate)


class CompositeEncoder:
    """Encodes video frames into composite analog waveform."""
    
    def __init__(self, config: AnalogConfig):
        self.config = config
        self.std = config.standard
        
        # Pre-calculate timing positions
        self._calculate_timing()
        
        # Pre-generate line template
        self._line_template = self._create_line_template()
        
        # Create low-pass filter for bandwidth limiting
        self._lpf_kernel = self._create_lpf_kernel()
        
    def _calculate_timing(self):
        """Calculate sample positions for different line segments."""
        sr = self.config.sample_rate
        
        # Convert durations to sample counts
        self.h_sync_samples = int(self.std.h_sync_duration_us * 1e-6 * sr)
        self.back_porch_samples = int(self.std.back_porch_us * 1e-6 * sr)
        self.front_porch_samples = int(self.std.front_porch_us * 1e-6 * sr)
        self.active_samples = self.config.active_samples_per_line
        
        # Calculate start positions
        self.sync_start = 0
        self.back_porch_start = self.h_sync_samples
        self.active_start = self.back_porch_start + self.back_porch_samples
        self.front_porch_start = self.active_start + self.active_samples
        
        logging.debug(f"Line timing: sync={self.h_sync_samples}, "
                     f"back={self.back_porch_samples}, "
                     f"active={self.active_samples}, "
                     f"front={self.front_porch_samples}")
    
    def _create_line_template(self) -> np.ndarray:
        """Create a template for one horizontal line with sync and blanking."""
        samples_per_line = self.config.samples_per_line
        line = np.full(samples_per_line, self.std.blanking_level, dtype=np.float32)
        
        # H-sync pulse
        line[self.sync_start:self.back_porch_start] = self.std.sync_tip
        
        # Back porch (blanking level)
        line[self.back_porch_start:self.active_start] = self.std.blanking_level
        
        # Front porch (blanking level)
        line[self.front_porch_start:] = self.std.blanking_level
        
        return line
    
    def _create_lpf_kernel(self) -> np.ndarray:
        """Create low-pass filter kernel for bandwidth limiting."""
        # Sinc filter for bandwidth limiting
        bandwidth = self.config.bandwidth_mhz * 1e6
        cutoff_normalized = bandwidth / self.config.sample_rate
        
        # Kernel size (must be odd)
        kernel_size = 31
        center = kernel_size // 2
        
        # Generate sinc kernel
        t = np.arange(kernel_size) - center
        kernel = np.sinc(2 * cutoff_normalized * t)
        
        # Apply Hamming window
        window = np.hamming(kernel_size)
        kernel *= window
        
        # Normalize
        kernel /= np.sum(kernel)
        
        return kernel.astype(np.float32)
    
    def frame_to_luminance(self, frame: np.ndarray) -> np.ndarray:
        """Convert BGR frame to luminance values."""
        # Convert to grayscale using proper luminance weights
        # Y = 0.299*R + 0.587*G + 0.114*B
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        
        # Resize to active line resolution
        height = self.config.active_lines
        width = self.config.resolution[0]
        
        if gray.shape != (height, width):
            gray = cv2.resize(gray, (width, height), interpolation=cv2.INTER_LINEAR)
        
        # Normalize to video range (black_level to white_level)
        normalized = gray.astype(np.float32) / 255.0
        scaled = (self.std.black_level + 
                 normalized * (self.std.white_level - self.std.black_level))
        
        return scaled
    
    def apply_bandwidth_limiting(self, signal: np.ndarray) -> np.ndarray:
        """Apply low-pass filter to simulate bandwidth limitations."""
        # Convolve with LPF kernel
        filtered = np.convolve(signal, self._lpf_kernel, mode='same')
        return filtered.astype(np.float32)
    
    def encode_line(self, line_pixels: Optional[np.ndarray] = None) -> np.ndarray:
        """Encode one horizontal line with sync, blanking, and video."""
        # Start with template (sync + blanking)
        line = self._line_template.copy()
        
        if line_pixels is not None:
            # Resample pixels to fit active video samples
            if len(line_pixels) != self.active_samples:
                # Use linear interpolation to resample
                x_old = np.linspace(0, 1, len(line_pixels))
                x_new = np.linspace(0, 1, self.active_samples)
                line_pixels = np.interp(x_new, x_old, line_pixels)
            
            # Insert video into active region
            line[self.active_start:self.active_start + self.active_samples] = line_pixels
        
        return line
    
    def encode_frame(self, frame: np.ndarray) -> np.ndarray:
        """Encode complete frame with vertical blanking."""
        lines_per_frame = self.std.lines_per_frame
        active_lines = self.config.active_lines
        
        # Calculate vertical blanking
        vblank_lines = lines_per_frame - active_lines
        vblank_top = vblank_lines // 2
        vblank_bottom = vblank_lines - vblank_top
        
        # Convert frame to luminance
        luma = self.frame_to_luminance(frame)
        
        # Allocate output
        output = np.zeros(self.config.samples_per_frame, dtype=np.float32)
        
        line_idx = 0
        
        # Top vertical blanking (with V-sync)
        for i in range(vblank_top):
            line_data = self.encode_line(None)  # Blank line
            start = line_idx * self.config.samples_per_line
            end = start + len(line_data)
            output[start:end] = line_data
            line_idx += 1
        
        # Active video lines
        for i in range(active_lines):
            line_pixels = luma[i, :]
            line_data = self.encode_line(line_pixels)
            start = line_idx * self.config.samples_per_line
            end = start + len(line_data)
            output[start:end] = line_data
            line_idx += 1
        
        # Bottom vertical blanking
        for i in range(vblank_bottom):
            line_data = self.encode_line(None)
            start = line_idx * self.config.samples_per_line
            end = start + len(line_data)
            output[start:end] = line_data
            line_idx += 1
        
        # Apply bandwidth limiting to entire frame
        output = self.apply_bandwidth_limiting(output)
        
        # Add noise if enabled
        if self.config.add_noise:
            noise = np.random.normal(0, self.config.noise_amplitude, len(output))
            output += noise.astype(np.float32)
        
        # Clip to valid range
        output = np.clip(output, self.std.sync_tip, self.std.white_level)
        
        return output


class VideoSource:
    """Handles video input from file or webcam."""
    
    def __init__(self, source: str, target_fps: float):
        self.source = source
        self.target_fps = target_fps
        self.cap = None
        
    def open(self) -> bool:
        """Open video source."""
        if self.source.isdigit():
            # Camera ID
            camera_id = int(self.source)
            self.cap = cv2.VideoCapture(camera_id)
            logging.info(f"Opening camera {camera_id}")
        else:
            # Video file
            if not Path(self.source).exists():
                logging.error(f"Video file not found: {self.source}")
                return False
            self.cap = cv2.VideoCapture(self.source)
            logging.info(f"Opening video file: {self.source}")
        
        if not self.cap.isOpened():
            logging.error("Failed to open video source")
            return False
        
        # Get properties
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        logging.info(f"Video source: {width}x{height} @ {fps:.2f} fps")
        return True
    
    def read_frame(self) -> Optional[np.ndarray]:
        """Read one frame."""
        ret, frame = self.cap.read()
        return frame if ret else None
    
    def close(self):
        """Close video source."""
        if self.cap:
            self.cap.release()


class AnalogFileWriter:
    """Writes analog signal to file with metadata."""
    
    MAGIC = b'ANLG'
    VERSION = 1
    
    def __init__(self, filename: str, config: AnalogConfig):
        self.filename = filename
        self.config = config
        self.file = None
        self.frames_written = 0
        
    def open(self) -> bool:
        """Open file and write header."""
        try:
            self.file = open(self.filename, 'wb')
            self._write_header()
            logging.info(f"Created analog signal file: {self.filename}")
            return True
        except Exception as e:
            logging.error(f"Failed to create file: {e}")
            return False
    
    def _write_header(self):
        """Write file header with metadata."""
        # Magic number and version
        self.file.write(self.MAGIC)
        self.file.write(struct.pack('<I', self.VERSION))
        
        # Create metadata dictionary
        metadata = {
            'standard': self.config.standard.name,
            'sample_rate': self.config.sample_rate,
            'resolution': list(self.config.resolution),
            'lines_per_frame': self.config.standard.lines_per_frame,
            'fps': self.config.standard.fps,
            'samples_per_line': self.config.samples_per_line,
            'samples_per_frame': self.config.samples_per_frame,
            'active_lines': self.config.active_lines,
            'bandwidth_mhz': self.config.bandwidth_mhz,
            'voltage_levels': {
                'sync_tip': self.config.standard.sync_tip,
                'blanking': self.config.standard.blanking_level,
                'black': self.config.standard.black_level,
                'white': self.config.standard.white_level
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Serialize metadata as JSON
        metadata_json = json.dumps(metadata, indent=2)
        metadata_bytes = metadata_json.encode('utf-8')
        
        # Write metadata length and data
        self.file.write(struct.pack('<I', len(metadata_bytes)))
        self.file.write(metadata_bytes)
        
        logging.debug(f"Wrote header with metadata: {len(metadata_bytes)} bytes")
    
    def write_frame(self, signal: np.ndarray):
        """Write one frame of analog signal."""
        # Convert to float32 and write
        signal_bytes = signal.astype(np.float32).tobytes()
        self.file.write(signal_bytes)
        self.frames_written += 1
    
    def close(self):
        """Close file."""
        if self.file:
            self.file.close()
            logging.info(f"Wrote {self.frames_written} frames")


class VideoToAnalogConverter:
    """Main application class."""
    
    def __init__(self, args):
        self.args = args
        
        # Setup logging
        self._setup_logging()
        
        # Create configuration
        standard = NTSC if args.standard == 'ntsc' else PAL
        self.config = AnalogConfig(
            standard=standard,
            sample_rate=args.sample_rate,
            resolution=(args.width, args.height),
            active_lines=args.height,
            bandwidth_mhz=args.bandwidth,
            add_noise=args.add_noise,
            noise_amplitude=args.noise_level
        )
        
        logging.info(f"Configuration: {args.standard.upper()}, "
                    f"{args.width}x{args.height}, "
                    f"{self.config.sample_rate/1e6:.1f} MHz sampling")
        
        # Create components
        self.encoder = CompositeEncoder(self.config)
        self.video_source = VideoSource(args.input, self.config.standard.fps)
        self.writer = AnalogFileWriter(args.output, self.config)
        
    def _setup_logging(self):
        """Setup logging."""
        level = logging.DEBUG if self.args.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    def convert(self) -> bool:
        """Main conversion process."""
        logging.info("Starting video to analog conversion")
        
        # Open video source
        if not self.video_source.open():
            return False
        
        # Open output file
        if not self.writer.open():
            return False
        
        # Process frames
        frame_count = 0
        max_frames = self.args.max_frames if self.args.max_frames > 0 else float('inf')
        start_time = time.time()
        
        try:
            while frame_count < max_frames:
                # Read frame
                frame = self.video_source.read_frame()
                if frame is None:
                    logging.info("End of video source")
                    break
                
                # Encode to analog
                analog_signal = self.encoder.encode_frame(frame)
                
                # Write to file
                self.writer.write_frame(analog_signal)
                
                frame_count += 1
                
                # Progress logging
                if frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    duration = frame_count / self.config.standard.fps
                    logging.info(f"Processed {frame_count} frames "
                               f"({duration:.1f}s video) @ {fps:.1f} fps")
                
                # Preview if enabled
                if self.args.preview:
                    cv2.imshow("Video Source", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        logging.info("Preview closed by user")
                        break
            
            # Summary
            elapsed = time.time() - start_time
            total_samples = frame_count * self.config.samples_per_frame
            file_size_mb = (total_samples * 4) / (1024 * 1024)  # float32 = 4 bytes
            
            logging.info(f"\nConversion complete:")
            logging.info(f"  Frames: {frame_count}")
            logging.info(f"  Duration: {frame_count / self.config.standard.fps:.2f}s")
            logging.info(f"  Samples: {total_samples:,}")
            logging.info(f"  File size: {file_size_mb:.1f} MB")
            logging.info(f"  Processing time: {elapsed:.1f}s")
            
            return True
            
        except KeyboardInterrupt:
            logging.info("\nInterrupted by user")
            return False
        except Exception as e:
            logging.error(f"Conversion error: {e}", exc_info=True)
            return False
        finally:
            self.video_source.close()
            self.writer.close()
            if self.args.preview:
                cv2.destroyAllWindows()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert video to analog composite signal",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('input', type=str,
                       help='Input video file path or camera ID (0, 1, etc.)')
    parser.add_argument('output', type=str,
                       help='Output analog signal file (.analog)')
    
    parser.add_argument('--standard', choices=['ntsc', 'pal'], default='ntsc',
                       help='Video standard')
    parser.add_argument('--sample-rate', type=int, default=10_000_000,
                       help='Sample rate in Hz (e.g., 10000000 = 10 MHz)')
    parser.add_argument('--width', type=int, default=640,
                       help='Video width in pixels')
    parser.add_argument('--height', type=int, default=480,
                       help='Video height in pixels')
    parser.add_argument('--bandwidth', type=float, default=4.2,
                       help='Luminance bandwidth in MHz')
    parser.add_argument('--max-frames', type=int, default=0,
                       help='Maximum frames to process (0 = all)')
    parser.add_argument('--add-noise', action='store_true',
                       help='Add analog noise to signal')
    parser.add_argument('--noise-level', type=float, default=0.02,
                       help='Noise amplitude (0.0-0.1)')
    parser.add_argument('--preview', action='store_true',
                       help='Show video preview during conversion')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Validate output extension
    if not args.output.endswith('.analog'):
        logging.warning("Output file doesn't have .analog extension, adding it")
        args.output += '.analog'
    
    # Create converter and run
    converter = VideoToAnalogConverter(args)
    success = converter.convert()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()


