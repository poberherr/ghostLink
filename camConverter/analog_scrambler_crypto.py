#!/usr/bin/env python3
"""
Crypto-Secure Analog Signal Scrambler
======================================

Implements the scrambling techniques from README.md:
- Horizontal line permutation (segment shuffling)
- Per-segment inversion
- Pixel shift within segments
- Crypto-driven with ChaCha20 keystream

This makes the video COMPLETELY UNWATCHABLE without the key,
while preserving sync pulses for analog transmission.

Author: Your Name
Date: November 2025
"""

import os
import sys
import logging
import argparse
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple
import struct
import json
import hashlib

try:
    from analog_to_video import AnalogFileReader
except ImportError:
    print("Error: analog_to_video.py must be in the same directory")
    sys.exit(1)

# Try to use real ChaCha20, fallback to PRNG
try:
    from Crypto.Cipher import ChaCha20
    CHACHA_AVAILABLE = True
except ImportError:
    CHACHA_AVAILABLE = False
    print("Warning: pycryptodome not available, using PRNG fallback")
    print("Install with: uv add pycryptodome")


class AnalogFileWriter:
    """Writes analog signal to file with metadata."""
    
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
        from datetime import datetime
        self.file.write(self.MAGIC)
        self.file.write(struct.pack('<I', self.VERSION))
        
        self.metadata['timestamp'] = datetime.now().isoformat()
        self.metadata['scrambled'] = True
        
        metadata_json = json.dumps(self.metadata, indent=2)
        metadata_bytes = metadata_json.encode('utf-8')
        
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


class CryptoKeystream:
    """Generate cryptographic keystream for scrambling operations."""
    
    def __init__(self, key: bytes, use_chacha: bool = True):
        self.key = key
        self.use_chacha = use_chacha and CHACHA_AVAILABLE
        self.frame_counter = 0
        
        if self.use_chacha:
            logging.info("Using ChaCha20 keystream")
        else:
            logging.info("Using PRNG keystream (fallback)")
            # Seed numpy PRNG with key hash
            seed = int.from_bytes(hashlib.sha256(key).digest()[:4], 'little')
            self.rng = np.random.RandomState(seed)
    
    def generate_keystream(self, length: int, frame_num: int) -> bytes:
        """Generate keystream for a specific frame."""
        if self.use_chacha:
            # Create nonce from frame number
            nonce = frame_num.to_bytes(8, 'little')
            cipher = ChaCha20.new(key=self.key, nonce=nonce)
            return cipher.encrypt(b'\x00' * length)
        else:
            # Use seeded PRNG
            self.rng.seed(int.from_bytes(self.key[:4], 'little') + frame_num)
            return self.rng.bytes(length)
    
    def get_permutation(self, n: int, frame_num: int, line_num: int) -> np.ndarray:
        """Generate a permutation of [0, 1, ..., n-1] from keystream."""
        # Create unique seed for this line
        seed_data = frame_num.to_bytes(4, 'little') + line_num.to_bytes(4, 'little')
        keystream = self.generate_keystream(len(seed_data), frame_num)
        seed = int.from_bytes(bytes(a ^ b for a, b in zip(seed_data, keystream)), 'little')
        
        # Ensure seed fits in uint32
        seed = seed & 0xFFFFFFFF
        
        # Generate permutation
        rng = np.random.RandomState(seed)
        indices = np.arange(n)
        rng.shuffle(indices)
        return indices
    
    def get_inversions(self, n: int, frame_num: int, line_num: int) -> np.ndarray:
        """Generate binary mask for segment inversions."""
        seed_data = (frame_num + 1).to_bytes(4, 'little') + line_num.to_bytes(4, 'little')
        keystream = self.generate_keystream(len(seed_data), frame_num)
        seed = int.from_bytes(bytes(a ^ b for a, b in zip(seed_data, keystream)), 'little')
        
        # Ensure seed fits in uint32
        seed = seed & 0xFFFFFFFF
        
        rng = np.random.RandomState(seed)
        return rng.randint(0, 2, n).astype(bool)
    
    def get_shifts(self, n: int, max_shift: int, frame_num: int, line_num: int) -> np.ndarray:
        """Generate shift amounts for each segment."""
        seed_data = (frame_num + 2).to_bytes(4, 'little') + line_num.to_bytes(4, 'little')
        keystream = self.generate_keystream(len(seed_data), frame_num)
        seed = int.from_bytes(bytes(a ^ b for a, b in zip(seed_data, keystream)), 'little')
        
        # Ensure seed fits in uint32
        seed = seed & 0xFFFFFFFF
        
        rng = np.random.RandomState(seed)
        return rng.randint(0, max_shift, n)


class CryptoScrambler:
    """Crypto-secure analog video scrambler."""
    
    def __init__(self, metadata: dict, key: bytes, segments_per_line: int = 16):
        self.metadata = metadata
        self.keystream = CryptoKeystream(key)
        self.segments_per_line = segments_per_line
        
        self.samples_per_line = metadata['samples_per_line']
        self.samples_per_frame = metadata['samples_per_frame']
        self.lines_per_frame = metadata['lines_per_frame']
        
        # Voltage levels
        self.sync_tip = metadata['voltage_levels']['sync_tip']
        self.blanking = metadata['voltage_levels']['blanking']
        self.black = metadata['voltage_levels']['black']
        self.white = metadata['voltage_levels']['white']
        
        # Calculate sync end position (preserve sync + back porch)
        # Approximately 94 samples at 10 MHz for NTSC
        self.sync_end = 94
        
        # Calculate active video region
        self.active_length = self.samples_per_line - self.sync_end - 15  # -15 for front porch
        self.segment_size = self.active_length // segments_per_line
        
        logging.info(f"Crypto scrambler initialized:")
        logging.info(f"  Segments per line: {segments_per_line}")
        logging.info(f"  Segment size: {self.segment_size} samples")
        logging.info(f"  Active region: {self.active_length} samples")
        logging.info(f"  Sync preserved: 0-{self.sync_end} samples")
    
    def scramble_frame(self, signal: np.ndarray, frame_num: int, 
                      enable_permutation: bool = True,
                      enable_inversion: bool = True,
                      enable_shift: bool = True) -> np.ndarray:
        """
        Apply crypto-secure scrambling to entire frame.
        
        Operations applied (all crypto-driven):
        1. Horizontal segment permutation (strongest)
        2. Per-segment amplitude inversion
        3. Per-segment pixel shift
        """
        lines = signal.reshape(-1, self.samples_per_line)
        scrambled_lines = np.zeros_like(lines)
        
        # Calculate vertical blanking (don't scramble these lines)
        active_lines = self.metadata.get('active_lines', 480)
        vblank = len(lines) - active_lines
        vblank_top = vblank // 2
        vblank_bottom = vblank - vblank_top
        
        # Process each line
        for line_idx in range(len(lines)):
            line = lines[line_idx]
            
            # Preserve vertical blanking lines
            if line_idx < vblank_top or line_idx >= (vblank_top + active_lines):
                scrambled_lines[line_idx] = line
                continue
            
            # Extract regions
            sync_region = line[:self.sync_end].copy()
            active_region = line[self.sync_end:self.sync_end + self.active_length].copy()
            tail_region = line[self.sync_end + self.active_length:].copy()
            
            # Split active region into segments
            segments = []
            for i in range(self.segments_per_line):
                start = i * self.segment_size
                end = start + self.segment_size
                if end <= len(active_region):
                    segments.append(active_region[start:end].copy())
            
            # Ensure we have the right number of segments
            if len(segments) != self.segments_per_line:
                scrambled_lines[line_idx] = line
                continue
            
            # ==================== OPERATION A: HORIZONTAL PERMUTATION ====================
            if enable_permutation:
                # Get crypto-driven permutation for this line
                perm = self.keystream.get_permutation(
                    self.segments_per_line, frame_num, line_idx
                )
                # Apply permutation
                segments = [segments[i] for i in perm]
            
            # ==================== OPERATION B: PER-SEGMENT INVERSION ====================
            if enable_inversion:
                # Get crypto-driven inversion mask
                inversions = self.keystream.get_inversions(
                    self.segments_per_line, frame_num, line_idx
                )
                
                # Apply inversions
                mid_level = (self.black + self.white) / 2
                for i, should_invert in enumerate(inversions):
                    if should_invert:
                        segments[i] = mid_level - (segments[i] - mid_level)
            
            # ==================== OPERATION C: PIXEL SHIFT ====================
            if enable_shift:
                # Get crypto-driven shift amounts
                shifts = self.keystream.get_shifts(
                    self.segments_per_line, self.segment_size // 4, 
                    frame_num, line_idx
                )
                
                # Apply circular shifts
                for i, shift in enumerate(shifts):
                    segments[i] = np.roll(segments[i], int(shift))
            
            # Reconstruct line
            scrambled_active = np.concatenate(segments)
            
            # Ensure correct length (trim or pad if needed)
            if len(scrambled_active) > self.active_length:
                scrambled_active = scrambled_active[:self.active_length]
            elif len(scrambled_active) < self.active_length:
                # Pad with last value
                padding = np.full(self.active_length - len(scrambled_active), 
                                 scrambled_active[-1], dtype=np.float32)
                scrambled_active = np.concatenate([scrambled_active, padding])
            
            # Combine all regions
            scrambled_line = np.concatenate([
                sync_region,
                scrambled_active,
                tail_region
            ])
            
            # Ensure final line matches expected length
            if len(scrambled_line) != self.samples_per_line:
                if len(scrambled_line) > self.samples_per_line:
                    scrambled_line = scrambled_line[:self.samples_per_line]
                else:
                    padding = np.full(self.samples_per_line - len(scrambled_line),
                                     self.blanking, dtype=np.float32)
                    scrambled_line = np.concatenate([scrambled_line, padding])
            
            scrambled_lines[line_idx] = scrambled_line
        
        return scrambled_lines.flatten()


class AnalogCryptoScrambler:
    """Main application class."""
    
    def __init__(self, args):
        self.args = args
        self._setup_logging()
        
        # Generate key from password
        if args.key:
            # Use provided hex key
            try:
                self.key = bytes.fromhex(args.key)
            except:
                logging.error("Invalid hex key, using password instead")
                self.key = self._derive_key(args.password)
        else:
            self.key = self._derive_key(args.password)
        
        logging.info(f"Using key: {self.key.hex()[:16]}... (truncated)")
        
        # Open input file
        self.reader = AnalogFileReader(args.input)
        if not self.reader.open():
            sys.exit(1)
        
        # Create scrambler
        self.scrambler = CryptoScrambler(
            self.reader.metadata, 
            self.key,
            segments_per_line=args.segments
        )
        
        # Create output writer
        output_metadata = self.reader.metadata.copy()
        output_metadata['scrambling_method'] = 'crypto'
        output_metadata['segments_per_line'] = args.segments
        output_metadata['operations'] = {
            'permutation': args.enable_permutation,
            'inversion': args.enable_inversion,
            'shift': args.enable_shift
        }
        self.writer = AnalogFileWriter(args.output, output_metadata)
        if not self.writer.open():
            sys.exit(1)
    
    def _derive_key(self, password: str) -> bytes:
        """Derive 32-byte key from password."""
        return hashlib.sha256(password.encode()).digest()
    
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
        logging.info("Starting crypto-secure scrambling")
        logging.info(f"Operations: permutation={self.args.enable_permutation}, "
                    f"inversion={self.args.enable_inversion}, "
                    f"shift={self.args.enable_shift}")
        
        frame_count = 0
        
        try:
            while True:
                # Read frame
                signal = self.reader.read_frame()
                if signal is None:
                    break
                
                # Apply crypto scrambling
                scrambled = self.scrambler.scramble_frame(
                    signal, frame_count,
                    enable_permutation=self.args.enable_permutation,
                    enable_inversion=self.args.enable_inversion,
                    enable_shift=self.args.enable_shift
                )
                
                # Write scrambled frame
                self.writer.write_frame(scrambled)
                
                frame_count += 1
                if frame_count % 30 == 0:
                    logging.info(f"Processed {frame_count} frames")
            
            logging.info(f"\nScrambling complete: {frame_count} frames")
            logging.info(f"Image should be COMPLETELY UNWATCHABLE without the key")
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
        description="Crypto-secure analog video scrambler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('input', type=str,
                       help='Input analog signal file (.analog)')
    parser.add_argument('output', type=str,
                       help='Output scrambled signal file (.analog)')
    
    # Crypto parameters
    parser.add_argument('--password', type=str, default='ghostlink_fpv_2025',
                       help='Password for key derivation')
    parser.add_argument('--key', type=str,
                       help='32-byte key in hex (overrides password)')
    
    # Scrambling parameters
    parser.add_argument('--segments', type=int, default=16,
                       help='Number of segments per line (more = stronger)')
    parser.add_argument('--enable-permutation', action='store_true', default=True,
                       help='Enable segment permutation (strongest)')
    parser.add_argument('--enable-inversion', action='store_true', default=True,
                       help='Enable per-segment inversion')
    parser.add_argument('--enable-shift', action='store_true', default=True,
                       help='Enable pixel shifts')
    parser.add_argument('--disable-permutation', action='store_true',
                       help='Disable segment permutation')
    parser.add_argument('--disable-inversion', action='store_true',
                       help='Disable inversion')
    parser.add_argument('--disable-shift', action='store_true',
                       help='Disable shifts')
    
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Handle disable flags
    if args.disable_permutation:
        args.enable_permutation = False
    if args.disable_inversion:
        args.enable_inversion = False
    if args.disable_shift:
        args.enable_shift = False
    
    return args


def main():
    """Main entry point."""
    args = parse_arguments()
    
    scrambler = AnalogCryptoScrambler(args)
    success = scrambler.scramble()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

