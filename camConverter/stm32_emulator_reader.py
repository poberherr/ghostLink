#!/usr/bin/env python3
"""
STM32 Emulator Test Reader
=========================

Reads analog signal samples from FIFO and interprets them as ADC values
for STM32 emulator integration. Supports both binary and CSV formats.

Features:
- Reads from UNIX FIFO (named pipe)
- Interprets samples as 12-bit ADC counts
- Converts to voltage (0-3.3V scale)
- Real-time plotting (optional)
- Statistics and logging
- Configurable sample interpretation

Author: GitHub Copilot
Date: November 2025
"""

import os
import sys
import time
import struct
import signal
import argparse
import threading
from typing import List, Tuple, Optional
from dataclasses import dataclass
from collections import deque
from datetime import datetime

import numpy as np

# Optional plotting support
try:
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False
    print("Warning: matplotlib not available. Real-time plotting disabled.")


@dataclass
class EmulatorConfig:
    """Configuration for the STM32 emulator reader."""
    fifo_path: str = "/tmp/camera_analog.fifo"
    data_format: str = "binary"  # "binary" or "csv"
    adc_resolution: int = 12  # bits
    voltage_range: float = 3.3  # volts
    channels: int = 4
    plot_enabled: bool = False
    plot_window_size: int = 300  # samples to display
    sample_rate: int = 30  # Hz (for timing estimates)
    log_interval: int = 100  # samples between log outputs
    output_file: Optional[str] = None
    
    @property
    def max_adc_value(self) -> int:
        """Maximum ADC value based on resolution."""
        return (2 ** self.adc_resolution) - 1
    
    @property
    def voltage_per_count(self) -> float:
        """Voltage per ADC count."""
        return self.voltage_range / self.max_adc_value


class SampleBuffer:
    """Thread-safe circular buffer for samples."""
    
    def __init__(self, max_size: int = 1000):
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
        
    def add_sample(self, timestamp: float, channels: List[int]):
        """Add a sample to the buffer."""
        with self.lock:
            self.buffer.append((timestamp, channels))
    
    def get_recent_samples(self, count: int) -> List[Tuple[float, List[int]]]:
        """Get the most recent samples."""
        with self.lock:
            if count >= len(self.buffer):
                return list(self.buffer)
            else:
                return list(self.buffer)[-count:]
    
    def get_all_samples(self) -> List[Tuple[float, List[int]]]:
        """Get all samples."""
        with self.lock:
            return list(self.buffer)


class FIFOReader:
    """Reads samples from FIFO."""
    
    def __init__(self, config: EmulatorConfig):
        self.config = config
        self.running = False
        self.fifo_fd = None
        self.sample_buffer = SampleBuffer()
        self.stats = {
            'samples_read': 0,
            'errors': 0,
            'start_time': None
        }
        
    def open_fifo(self) -> bool:
        """Open FIFO for reading."""
        try:
            print(f"Opening FIFO: {self.config.fifo_path}")
            self.fifo_fd = os.open(self.config.fifo_path, os.O_RDONLY)
            print("FIFO opened successfully")
            return True
            
        except Exception as e:
            print(f"Failed to open FIFO: {e}")
            return False
    
    def read_binary_samples(self) -> Optional[List[int]]:
        """Read binary samples from FIFO."""
        try:
            # Read data for all channels (uint16 little-endian)
            data_size = self.config.channels * 2  # 2 bytes per uint16
            data = os.read(self.fifo_fd, data_size)
            
            if len(data) != data_size:
                return None
                
            # Unpack as little-endian uint16
            samples = list(struct.unpack(f"<{self.config.channels}H", data))
            return samples
            
        except Exception as e:
            print(f"Binary read error: {e}")
            self.stats['errors'] += 1
            return None
    
    def read_csv_samples(self) -> Optional[Tuple[float, List[int]]]:
        """Read CSV samples from FIFO."""
        try:
            # Read until newline
            line = b""
            while True:
                char = os.read(self.fifo_fd, 1)
                if not char:
                    return None
                if char == b'\n':
                    break
                line += char
            
            # Parse CSV line: timestamp,ch0,ch1,ch2,...
            parts = line.decode().strip().split(',')
            if len(parts) != self.config.channels + 1:
                return None
                
            timestamp = float(parts[0])
            channels = [int(x) for x in parts[1:]]
            return timestamp, channels
            
        except Exception as e:
            print(f"CSV read error: {e}")
            self.stats['errors'] += 1
            return None
    
    def reading_loop(self):
        """Main reading loop."""
        self.running = True
        self.stats['start_time'] = time.time()
        
        print(f"Started reading from FIFO (format: {self.config.data_format})")
        
        while self.running:
            try:
                if self.config.data_format == "binary":
                    samples = self.read_binary_samples()
                    if samples:
                        timestamp = time.time()
                        self.sample_buffer.add_sample(timestamp, samples)
                        self.stats['samples_read'] += 1
                        
                elif self.config.data_format == "csv":
                    result = self.read_csv_samples()
                    if result:
                        timestamp, samples = result
                        self.sample_buffer.add_sample(timestamp, samples)
                        self.stats['samples_read'] += 1
                        
            except Exception as e:
                print(f"Reading error: {e}")
                self.stats['errors'] += 1
                break
    
    def adc_to_voltage(self, adc_value: int) -> float:
        """Convert ADC value to voltage."""
        # Clamp to valid range
        adc_value = max(0, min(adc_value, self.config.max_adc_value))
        return adc_value * self.config.voltage_per_count
    
    def print_sample_stats(self, timestamp: float, samples: List[int]):
        """Print sample statistics."""
        voltages = [self.adc_to_voltage(s) for s in samples]
        
        print(f"[{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]}] "
              f"ADC: {samples} | "
              f"Voltage: {[f'{v:.3f}V' for v in voltages]} | "
              f"Samples: {self.stats['samples_read']} | "
              f"Errors: {self.stats['errors']}")
    
    def get_statistics(self) -> dict:
        """Get reading statistics."""
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            rate = self.stats['samples_read'] / elapsed if elapsed > 0 else 0
        else:
            elapsed = 0
            rate = 0
            
        return {
            'samples_read': self.stats['samples_read'],
            'errors': self.stats['errors'],
            'elapsed_time': elapsed,
            'sample_rate': rate,
            'error_rate': self.stats['errors'] / max(1, self.stats['samples_read'])
        }
    
    def stop(self):
        """Stop reading."""
        self.running = False
        if self.fifo_fd:
            os.close(self.fifo_fd)


class RealTimePlotter:
    """Real-time sample plotting using matplotlib."""
    
    def __init__(self, config: EmulatorConfig, sample_buffer: SampleBuffer):
        if not PLOT_AVAILABLE:
            raise ImportError("matplotlib not available")
            
        self.config = config
        self.sample_buffer = sample_buffer
        
        # Setup plot
        self.fig, self.axes = plt.subplots(2, 1, figsize=(12, 8))
        self.fig.suptitle("STM32 Emulator - Real-time ADC Monitoring")
        
        # ADC plot
        self.adc_lines = []
        for i in range(self.config.channels):
            line, = self.axes[0].plot([], [], label=f'Channel {i}')
            self.adc_lines.append(line)
            
        self.axes[0].set_title("ADC Values")
        self.axes[0].set_ylabel("ADC Counts")
        self.axes[0].set_ylim(0, self.config.max_adc_value)
        self.axes[0].legend()
        self.axes[0].grid(True)
        
        # Voltage plot
        self.voltage_lines = []
        for i in range(self.config.channels):
            line, = self.axes[1].plot([], [], label=f'Channel {i}')
            self.voltage_lines.append(line)
            
        self.axes[1].set_title("Voltage")
        self.axes[1].set_xlabel("Sample Number")
        self.axes[1].set_ylabel("Voltage (V)")
        self.axes[1].set_ylim(0, self.config.voltage_range)
        self.axes[1].legend()
        self.axes[1].grid(True)
        
        plt.tight_layout()
        
    def update_plot(self, frame):
        """Update plot with latest data."""
        samples = self.sample_buffer.get_recent_samples(self.config.plot_window_size)
        
        if not samples:
            return self.adc_lines + self.voltage_lines
        
        # Extract data
        x_data = list(range(len(samples)))
        adc_data = [[] for _ in range(self.config.channels)]
        voltage_data = [[] for _ in range(self.config.channels)]
        
        for _, channels in samples:
            for i, value in enumerate(channels):
                if i < self.config.channels:
                    adc_data[i].append(value)
                    voltage_data[i].append(value * self.config.voltage_per_count)
        
        # Update ADC lines
        for i, line in enumerate(self.adc_lines):
            if i < len(adc_data) and adc_data[i]:
                line.set_data(x_data, adc_data[i])
                
        # Update voltage lines  
        for i, line in enumerate(self.voltage_lines):
            if i < len(voltage_data) and voltage_data[i]:
                line.set_data(x_data, voltage_data[i])
        
        # Update x-axis
        if x_data:
            for ax in self.axes:
                ax.set_xlim(0, len(x_data))
        
        return self.adc_lines + self.voltage_lines
    
    def start_animation(self):
        """Start the animation."""
        ani = animation.FuncAnimation(
            self.fig, self.update_plot, interval=100, blit=True
        )
        plt.show()
        return ani


class STM32EmulatorReader:
    """Main emulator reader application."""
    
    def __init__(self, config: EmulatorConfig):
        self.config = config
        self.reader = FIFOReader(config)
        self.plotter = None
        self.running = False
        self.output_file = None
        
        # Signal handling
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def signal_handler(self, sig, frame):
        """Handle shutdown signals."""
        print("\nReceived shutdown signal")
        self.stop()
    
    def initialize(self) -> bool:
        """Initialize the reader."""
        print("Initializing STM32 Emulator Reader")
        print(f"Configuration: {self.config}")
        
        # Open output file if specified
        if self.config.output_file:
            try:
                self.output_file = open(self.config.output_file, 'w')
                self.output_file.write("# STM32 Emulator ADC Data\n")
                self.output_file.write("# timestamp,ch0,ch1,ch2,ch3,ch0_voltage,ch1_voltage,ch2_voltage,ch3_voltage\n")
                print(f"Output file: {self.config.output_file}")
            except Exception as e:
                print(f"Failed to open output file: {e}")
                return False
        
        # Open FIFO
        if not self.reader.open_fifo():
            return False
        
        # Initialize plotter if enabled
        if self.config.plot_enabled and PLOT_AVAILABLE:
            try:
                self.plotter = RealTimePlotter(self.config, self.reader.sample_buffer)
                print("Real-time plotting enabled")
            except Exception as e:
                print(f"Failed to initialize plotter: {e}")
                self.config.plot_enabled = False
        
        return True
    
    def run(self):
        """Run the emulator reader."""
        self.running = True
        
        # Start reading thread
        reader_thread = threading.Thread(target=self.reader.reading_loop, daemon=True)
        reader_thread.start()
        
        print("Started reading thread")
        
        # Start plotting if enabled
        if self.config.plot_enabled and self.plotter:
            plot_thread = threading.Thread(target=self.plotter.start_animation, daemon=True)
            plot_thread.start()
        
        # Main monitoring loop
        last_log_count = 0
        
        try:
            while self.running:
                time.sleep(1.0)
                
                # Get latest samples for logging
                recent_samples = self.reader.sample_buffer.get_recent_samples(10)
                if recent_samples:
                    latest_timestamp, latest_channels = recent_samples[-1]
                    
                    # Log at intervals
                    if (self.reader.stats['samples_read'] - last_log_count) >= self.config.log_interval:
                        self.reader.print_sample_stats(latest_timestamp, latest_channels)
                        last_log_count = self.reader.stats['samples_read']
                        
                        # Write to output file
                        if self.output_file:
                            voltages = [self.reader.adc_to_voltage(s) for s in latest_channels]
                            line = f"{latest_timestamp:.6f}," + ",".join(map(str, latest_channels))
                            line += "," + ",".join(f"{v:.6f}" for v in voltages) + "\n"
                            self.output_file.write(line)
                            self.output_file.flush()
                
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"Application error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the application."""
        if not self.running:
            return
            
        print("Stopping emulator reader...")
        self.running = False
        
        # Stop reader
        self.reader.stop()
        
        # Close output file
        if self.output_file:
            self.output_file.close()
        
        # Print final statistics
        stats = self.reader.get_statistics()
        print(f"\nFinal Statistics:")
        print(f"  Samples read: {stats['samples_read']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Elapsed time: {stats['elapsed_time']:.1f}s")
        print(f"  Sample rate: {stats['sample_rate']:.1f} Hz")
        print(f"  Error rate: {stats['error_rate']:.3f}")
        
        print("Emulator reader stopped")


def parse_arguments() -> EmulatorConfig:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="STM32 Emulator Test Reader",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("--fifo-path", type=str, default="/tmp/camera_analog.fifo",
                       help="Path to FIFO")
    parser.add_argument("--data-format", choices=["binary", "csv"], default="binary",
                       help="FIFO data format")
    parser.add_argument("--adc-resolution", type=int, default=12,
                       help="ADC resolution in bits")
    parser.add_argument("--voltage-range", type=float, default=3.3,
                       help="ADC voltage range")
    parser.add_argument("--channels", type=int, default=4,
                       help="Number of analog channels")
    parser.add_argument("--plot", action="store_true",
                       help="Enable real-time plotting")
    parser.add_argument("--plot-window-size", type=int, default=300,
                       help="Number of samples to display in plot")
    parser.add_argument("--sample-rate", type=int, default=30,
                       help="Expected sample rate (for timing estimates)")
    parser.add_argument("--log-interval", type=int, default=100,
                       help="Samples between log outputs")
    parser.add_argument("--output-file", type=str,
                       help="Output CSV file path")
    
    args = parser.parse_args()
    
    return EmulatorConfig(
        fifo_path=args.fifo_path,
        data_format=args.data_format,
        adc_resolution=args.adc_resolution,
        voltage_range=args.voltage_range,
        channels=args.channels,
        plot_enabled=args.plot,
        plot_window_size=args.plot_window_size,
        sample_rate=args.sample_rate,
        log_interval=args.log_interval,
        output_file=args.output_file
    )


def main():
    """Main entry point."""
    config = parse_arguments()
    app = STM32EmulatorReader(config)
    
    if not app.initialize():
        sys.exit(1)
    
    app.run()


if __name__ == "__main__":
    main()