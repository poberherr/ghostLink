#!/usr/bin/env python3
"""
Crypto-Secure Analog Signal Descrambler
========================================

Reverses the scrambling operations from analog_scrambler_crypto.py

Uses the same key/password to:
1. Generate identical keystream
2. Apply inverse operations in reverse order:
   - Undo pixel shifts (negative shifts)
   - Undo inversions (self-inverse)
   - Undo permutations (inverse permutation)
3. Recover original signal perfectly

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
        self.metadata['scrambled'] = False
        self.metadata['descrambled'] = True
        
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
        
        # Generate permutation (same as scrambler)
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


class CryptoDescrambler:
    """Crypto-secure analog video descrambler."""
    
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
        
        # Calculate sync end position (same as scrambler)
        self.sync_end = 94
        
        # Calculate active video region
        self.active_length = self.samples_per_line - self.sync_end - 15
        self.segment_size = self.active_length // segments_per_line
        
        logging.info(f"Crypto descrambler initialized:")
        logging.info(f"  Segments per line: {segments_per_line}")
        logging.info(f"  Segment size: {self.segment_size} samples")
        logging.info(f"  Active region: {self.active_length} samples")
        logging.info(f"  Sync preserved: 0-{self.sync_end} samples")
    
    def descramble_frame(self, signal: np.ndarray, frame_num: int,
                        enable_permutation: bool = True,
                        enable_inversion: bool = True,
                        enable_shift: bool = True) -> np.ndarray:
        """
        Apply inverse operations to descramble frame.
        
        Operations applied in REVERSE order:
        1. Undo pixel shifts (apply negative shifts)
        2. Undo inversions (apply same inversion - self-inverse)
        3. Undo permutations (apply inverse permutation)
        """
        lines = signal.reshape(-1, self.samples_per_line)
        descrambled_lines = np.zeros_like(lines)
        
        # Calculate vertical blanking (same as scrambler)
        active_lines = self.metadata.get('active_lines', 480)
        vblank = len(lines) - active_lines
        vblank_top = vblank // 2
        vblank_bottom = vblank - vblank_top
        
        # Process each line
        for line_idx in range(len(lines)):
            line = lines[line_idx]
            
            # Preserve vertical blanking lines
            if line_idx < vblank_top or line_idx >= (vblank_top + active_lines):
                descrambled_lines[line_idx] = line
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
                descrambled_lines[line_idx] = line
                continue
            
            # ==================== UNDO OPERATION C: PIXEL SHIFT ====================
            if enable_shift:
                # Get SAME shift amounts as scrambler
                shifts = self.keystream.get_shifts(
                    self.segments_per_line, self.segment_size // 4,
                    frame_num, line_idx
                )
                
                # Apply NEGATIVE shifts (undo)
                for i, shift in enumerate(shifts):
                    segments[i] = np.roll(segments[i], -int(shift))  # Negative!
            
            # ==================== UNDO OPERATION B: PER-SEGMENT INVERSION ====================
            if enable_inversion:
                # Get SAME inversion mask as scrambler
                inversions = self.keystream.get_inversions(
                    self.segments_per_line, frame_num, line_idx
                )
                
                # Apply inversions (self-inverse: inverting twice = original)
                mid_level = (self.black + self.white) / 2
                for i, should_invert in enumerate(inversions):
                    if should_invert:
                        segments[i] = mid_level - (segments[i] - mid_level)
            
            # ==================== UNDO OPERATION A: HORIZONTAL PERMUTATION ====================
            if enable_permutation:
                # Get SAME permutation as scrambler
                perm = self.keystream.get_permutation(
                    self.segments_per_line, frame_num, line_idx
                )
                
                # Create INVERSE permutation
                inv_perm = np.argsort(perm)
                
                # Apply inverse permutation
                segments = [segments[i] for i in inv_perm]
            
            # Reconstruct line
            descrambled_active = np.concatenate(segments)
            
            # Ensure correct length
            if len(descrambled_active) > self.active_length:
                descrambled_active = descrambled_active[:self.active_length]
            elif len(descrambled_active) < self.active_length:
                padding = np.full(self.active_length - len(descrambled_active),
                                 descrambled_active[-1], dtype=np.float32)
                descrambled_active = np.concatenate([descrambled_active, padding])
            
            # Combine all regions
            descrambled_line = np.concatenate([
                sync_region,
                descrambled_active,
                tail_region
            ])
            
            # Ensure final line matches expected length
            if len(descrambled_line) != self.samples_per_line:
                if len(descrambled_line) > self.samples_per_line:
                    descrambled_line = descrambled_line[:self.samples_per_line]
                else:
                    padding = np.full(self.samples_per_line - len(descrambled_line),
                                     self.blanking, dtype=np.float32)
                    descrambled_line = np.concatenate([descrambled_line, padding])
            
            descrambled_lines[line_idx] = descrambled_line
        
        return descrambled_lines.flatten()


class AnalogCryptoDescrambler:
    """Main application class."""
    
    def __init__(self, args):
        self.args = args
        self._setup_logging()
        
        # Generate key from password (SAME as scrambler)
        if args.key:
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
        
        # Get segments from metadata if available, otherwise use args
        segments = args.segments
        if 'segments_per_line' in self.reader.metadata:
            segments = self.reader.metadata['segments_per_line']
            logging.info(f"Using segments from metadata: {segments}")
        
        # Create descrambler
        self.descrambler = CryptoDescrambler(
            self.reader.metadata,
            self.key,
            segments_per_line=segments
        )
        
        # Get operations from metadata if available
        enable_perm = args.enable_permutation
        enable_inv = args.enable_inversion
        enable_shift = args.enable_shift
        
        if 'operations' in self.reader.metadata:
            ops = self.reader.metadata['operations']
            enable_perm = ops.get('permutation', enable_perm)
            enable_inv = ops.get('inversion', enable_inv)
            enable_shift = ops.get('shift', enable_shift)
            logging.info(f"Using operations from metadata: perm={enable_perm}, inv={enable_inv}, shift={enable_shift}")
        
        self.enable_permutation = enable_perm
        self.enable_inversion = enable_inv
        self.enable_shift = enable_shift
        
        # Create output writer
        output_metadata = self.reader.metadata.copy()
        output_metadata['descrambling_method'] = 'crypto'
        self.writer = AnalogFileWriter(args.output, output_metadata)
        if not self.writer.open():
            sys.exit(1)
    
    def _derive_key(self, password: str) -> bytes:
        """Derive 32-byte key from password (SAME as scrambler)."""
        return hashlib.sha256(password.encode()).digest()
    
    def _setup_logging(self):
        """Setup logging."""
        level = logging.DEBUG if self.args.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    def descramble(self):
        """Main descrambling process."""
        logging.info("Starting crypto-secure descrambling")
        logging.info(f"Operations: permutation={self.enable_permutation}, "
                    f"inversion={self.enable_inversion}, "
                    f"shift={self.enable_shift}")
        
        frame_count = 0
        
        try:
            while True:
                # Read frame
                signal = self.reader.read_frame()
                if signal is None:
                    break
                
                # Apply crypto descrambling
                descrambled = self.descrambler.descramble_frame(
                    signal, frame_count,
                    enable_permutation=self.enable_permutation,
                    enable_inversion=self.enable_inversion,
                    enable_shift=self.enable_shift
                )
                
                # Write descrambled frame
                self.writer.write_frame(descrambled)
                
                frame_count += 1
                if frame_count % 30 == 0:
                    logging.info(f"Processed {frame_count} frames")
            
            logging.info(f"\nDescrambling complete: {frame_count} frames")
            logging.info(f"Original video should be PERFECTLY RECOVERED")
            return True
            
        except Exception as e:
            logging.error(f"Descrambling error: {e}", exc_info=True)
            return False
        finally:
            self.reader.close()
            self.writer.close()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Crypto-secure analog video descrambler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('input', type=str,
                       help='Input scrambled analog signal file (.analog)')
    parser.add_argument('output', type=str,
                       help='Output descrambled signal file (.analog)')
    
    # Crypto parameters (must match scrambler!)
    parser.add_argument('--password', type=str, default='ghostlink_fpv_2025',
                       help='Password (must match scrambler)')
    parser.add_argument('--key', type=str,
                       help='32-byte key in hex (must match scrambler)')
    
    # Scrambling parameters (must match scrambler!)
    parser.add_argument('--segments', type=int, default=16,
                       help='Number of segments per line (must match scrambler)')
    parser.add_argument('--enable-permutation', action='store_true', default=True,
                       help='Enable permutation descrambling')
    parser.add_argument('--enable-inversion', action='store_true', default=True,
                       help='Enable inversion descrambling')
    parser.add_argument('--enable-shift', action='store_true', default=True,
                       help='Enable shift descrambling')
    parser.add_argument('--disable-permutation', action='store_true',
                       help='Disable permutation')
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
    
    descrambler = AnalogCryptoDescrambler(args)
    success = descrambler.descramble()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

