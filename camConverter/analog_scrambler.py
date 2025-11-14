#!/usr/bin/env python3
"""
Analog Signal Scrambler
=======================

Template for implementing analog video scrambling algorithms.

This reads .analog files, applies scrambling techniques, and outputs
scrambled .analog files for testing.

Common scrambling techniques:
- Line rotation/inversion
- Sync suppression/modification
- Line shuffling
- Amplitude inversion
- Frequency domain scrambling
- Time-base distortion

Author: Your Name
Date: November 2025
"""

import os
import sys
import logging
import argparse
import numpy as np
from pathlib import Path
from typing import Optional, Callable
import struct
import json

try:
    from analog_to_video import AnalogFileReader
except ImportError:
    print("Error: analog_to_video.py must be in the same directory")
    sys.exit(1)


class AnalogFileWriter:
    """Writes analog signal to file with metadata (copied from video_to_analog.py)."""
    
    MAGIC = b'ANLG'
    VERSION = 1
    
    def __init__(self, filename: str, metadata: dict):
        self.filename = filename
        self.metadata = metadata
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
        
        # Ensure timestamp is updated
        from datetime import datetime
        self.metadata['timestamp'] = datetime.now().isoformat()
        if 'scrambled' not in self.metadata:
            self.metadata['scrambled'] = True
        
        # Serialize metadata as JSON
        metadata_json = json.dumps(self.metadata, indent=2)
        metadata_bytes = metadata_json.encode('utf-8')
        
        # Write metadata length and data
        self.file.write(struct.pack('<I', len(metadata_bytes)))
        self.file.write(metadata_bytes)
    
    def write_frame(self, signal: np.ndarray):
        """Write one frame of analog signal."""
        signal_bytes = signal.astype(np.float32).tobytes()
        self.file.write(signal_bytes)
        self.frames_written += 1
    
    def close(self):
        """Close file."""
        if self.file:
            self.file.close()
            logging.info(f"Wrote {self.frames_written} frames")


class Scrambler:
    """Analog signal scrambler with various techniques."""
    
    def __init__(self, metadata: dict):
        self.metadata = metadata
        self.samples_per_line = metadata['samples_per_line']
        self.samples_per_frame = metadata['samples_per_frame']
        self.lines_per_frame = metadata['lines_per_frame']
        
    # ==================== Scrambling Techniques ====================
    
    def line_rotation(self, signal: np.ndarray, shift_samples: int) -> np.ndarray:
        """
        Rotate each line horizontally by a fixed number of samples.
        
        This shifts the active video content but preserves sync pulses.
        """
        lines = signal.reshape(-1, self.samples_per_line)
        scrambled_lines = np.zeros_like(lines)
        
        for i, line in enumerate(lines):
            # Only rotate the active video portion (after sync + back porch)
            # Estimate: first ~100 samples are sync/blanking
            sync_end = 100
            
            sync_portion = line[:sync_end]
            video_portion = line[sync_end:]
            
            # Rotate video
            rotated_video = np.roll(video_portion, shift_samples)
            
            # Combine back
            scrambled_lines[i] = np.concatenate([sync_portion, rotated_video])
        
        return scrambled_lines.flatten()
    
    def line_inversion(self, signal: np.ndarray, invert_pattern: str = "alternating") -> np.ndarray:
        """
        Invert specific lines.
        
        Patterns:
        - "alternating": Invert every other line
        - "random": Randomly invert lines
        - "block": Invert blocks of lines
        """
        lines = signal.reshape(-1, self.samples_per_line)
        scrambled_lines = lines.copy()
        
        black_level = self.metadata['voltage_levels']['black']
        white_level = self.metadata['voltage_levels']['white']
        mid_level = (black_level + white_level) / 2
        
        for i in range(len(lines)):
            should_invert = False
            
            if invert_pattern == "alternating":
                should_invert = (i % 2 == 0)
            elif invert_pattern == "random":
                should_invert = (np.random.random() > 0.5)
            elif invert_pattern == "block":
                should_invert = ((i // 10) % 2 == 0)
            
            if should_invert:
                # Invert only the active video (preserve sync)
                sync_end = 100
                video = lines[i, sync_end:]
                inverted_video = mid_level - (video - mid_level)
                scrambled_lines[i, sync_end:] = inverted_video
        
        return scrambled_lines.flatten()
    
    def sync_suppression(self, signal: np.ndarray, suppression_level: float = 0.5) -> np.ndarray:
        """
        Suppress or modify sync pulses.
        
        suppression_level: 0.0 = no change, 1.0 = complete removal
        """
        sync_threshold = self.metadata['voltage_levels']['sync_tip'] * 0.5
        blanking = self.metadata['voltage_levels']['blanking']
        
        # Find sync pulses
        sync_mask = signal < sync_threshold
        
        # Suppress them
        signal_scrambled = signal.copy()
        signal_scrambled[sync_mask] = (
            signal[sync_mask] * (1 - suppression_level) + 
            blanking * suppression_level
        )
        
        return signal_scrambled
    
    def line_shuffle(self, signal: np.ndarray, shuffle_blocks: int = 10) -> np.ndarray:
        """
        Shuffle lines in blocks.
        
        shuffle_blocks: Number of blocks to divide and shuffle
        """
        lines = signal.reshape(-1, self.samples_per_line)
        num_lines = len(lines)
        
        # Calculate vertical blanking (don't shuffle these)
        active_lines = self.metadata.get('active_lines', 480)
        vblank = num_lines - active_lines
        vblank_top = vblank // 2
        vblank_bottom = vblank - vblank_top
        
        # Extract active lines
        active = lines[vblank_top:vblank_top + active_lines].copy()
        
        # Shuffle in blocks
        block_size = len(active) // shuffle_blocks
        shuffled = np.zeros_like(active)
        
        # Create shuffled indices
        block_indices = np.arange(shuffle_blocks)
        np.random.shuffle(block_indices)
        
        for new_idx, old_idx in enumerate(block_indices):
            old_start = old_idx * block_size
            old_end = old_start + block_size
            new_start = new_idx * block_size
            new_end = new_start + block_size
            
            if old_end <= len(active) and new_end <= len(shuffled):
                shuffled[new_start:new_end] = active[old_start:old_end]
        
        # Reconstruct frame
        scrambled_lines = lines.copy()
        scrambled_lines[vblank_top:vblank_top + active_lines] = shuffled
        
        return scrambled_lines.flatten()
    
    def add_noise(self, signal: np.ndarray, noise_level: float = 0.05) -> np.ndarray:
        """Add random noise to signal."""
        noise = np.random.normal(0, noise_level, len(signal))
        return signal + noise.astype(np.float32)
    
    def time_base_distortion(self, signal: np.ndarray, distortion: float = 0.1) -> np.ndarray:
        """
        Simulate time-base distortion (line length variations).
        
        This creates a jitter effect by stretching/compressing lines.
        """
        lines = signal.reshape(-1, self.samples_per_line)
        scrambled_lines = np.zeros_like(lines)
        
        for i, line in enumerate(lines):
            # Random stretch/compress factor
            factor = 1.0 + np.random.uniform(-distortion, distortion)
            new_length = int(len(line) * factor)
            
            # Resample line
            x_old = np.linspace(0, 1, len(line))
            x_new = np.linspace(0, 1, new_length)
            resampled = np.interp(x_new, x_old, line)
            
            # Fit back to original length (crop or pad)
            if len(resampled) > len(line):
                scrambled_lines[i] = resampled[:len(line)]
            else:
                scrambled_lines[i, :len(resampled)] = resampled
                scrambled_lines[i, len(resampled):] = line[-1]
        
        return scrambled_lines.flatten()


class AnalogScrambler:
    """Main scrambler application."""
    
    def __init__(self, args):
        self.args = args
        self._setup_logging()
        
        # Open input file
        self.reader = AnalogFileReader(args.input)
        if not self.reader.open():
            sys.exit(1)
        
        # Create scrambler
        self.scrambler = Scrambler(self.reader.metadata)
        
        # Create output writer
        output_metadata = self.reader.metadata.copy()
        output_metadata['scrambling_method'] = args.method
        output_metadata['scrambling_params'] = vars(args)
        self.writer = AnalogFileWriter(args.output, output_metadata)
        if not self.writer.open():
            sys.exit(1)
    
    def _setup_logging(self):
        """Setup logging."""
        level = logging.DEBUG if self.args.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    def scramble(self):
        """Main scrambling process."""
        logging.info(f"Starting scrambling with method: {self.args.method}")
        
        frame_count = 0
        
        try:
            while True:
                # Read frame
                signal = self.reader.read_frame()
                if signal is None:
                    break
                
                # Apply scrambling based on method
                if self.args.method == "line_rotation":
                    scrambled = self.scrambler.line_rotation(signal, self.args.shift)
                
                elif self.args.method == "line_inversion":
                    scrambled = self.scrambler.line_inversion(signal, self.args.pattern)
                
                elif self.args.method == "sync_suppression":
                    scrambled = self.scrambler.sync_suppression(signal, self.args.level)
                
                elif self.args.method == "line_shuffle":
                    scrambled = self.scrambler.line_shuffle(signal, self.args.blocks)
                
                elif self.args.method == "noise":
                    scrambled = self.scrambler.add_noise(signal, self.args.noise_level)
                
                elif self.args.method == "time_distortion":
                    scrambled = self.scrambler.time_base_distortion(signal, self.args.distortion)
                
                elif self.args.method == "combo":
                    # Apply multiple techniques
                    scrambled = self.scrambler.line_rotation(signal, 50)
                    scrambled = self.scrambler.line_inversion(scrambled, "alternating")
                    scrambled = self.scrambler.add_noise(scrambled, 0.02)
                
                else:
                    logging.error(f"Unknown method: {self.args.method}")
                    return False
                
                # Write scrambled frame
                self.writer.write_frame(scrambled)
                
                frame_count += 1
                if frame_count % 30 == 0:
                    logging.info(f"Processed {frame_count} frames")
            
            logging.info(f"\nScrambling complete: {frame_count} frames")
            return True
            
        except Exception as e:
            logging.error(f"Scrambling error: {e}", exc_info=True)
            return False
        finally:
            self.reader.close()
            self.writer.close()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Scramble analog video signals",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('input', type=str,
                       help='Input analog signal file (.analog)')
    parser.add_argument('output', type=str,
                       help='Output scrambled signal file (.analog)')
    
    parser.add_argument('--method', type=str, 
                       choices=['line_rotation', 'line_inversion', 'sync_suppression',
                               'line_shuffle', 'noise', 'time_distortion', 'combo'],
                       default='line_rotation',
                       help='Scrambling method to use')
    
    # Method-specific parameters
    parser.add_argument('--shift', type=int, default=100,
                       help='Sample shift for line_rotation')
    parser.add_argument('--pattern', type=str, 
                       choices=['alternating', 'random', 'block'],
                       default='alternating',
                       help='Pattern for line_inversion')
    parser.add_argument('--level', type=float, default=0.7,
                       help='Suppression level for sync_suppression (0-1)')
    parser.add_argument('--blocks', type=int, default=10,
                       help='Number of blocks for line_shuffle')
    parser.add_argument('--noise-level', type=float, default=0.05,
                       help='Noise amplitude for noise method')
    parser.add_argument('--distortion', type=float, default=0.1,
                       help='Distortion factor for time_distortion')
    
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()
    
    scrambler = AnalogScrambler(args)
    success = scrambler.scramble()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

