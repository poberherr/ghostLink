from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import cv2 
import numpy as np


@dataclass(frozen=True)
class AnalogTiming:
    """Defines the canonical NTSC-like timing used to synthesize each scan line."""

    line_duration_us: float = 63.556  # Total time budget per horizontal line.
    sync_pulse_us: float = 4.7  # Duration the signal stays at sync level each line.
    back_porch_us: float = 5.3  # Time between sync and active video (color burst region).
    front_porch_us: float = 1.5  # Time after active video before the next sync pulse.
    vbi_lines: int = 20  # Number of lines reserved for the vertical blanking interval.


class AnalogWaveformArchiver:
    """Converts digital video frames into a serialized analog waveform buffer.

    The class mimics a composite video raster by constructing per-line waveforms that
    include sync pulses, porches, and active video samples. Each processed frame is
    stored as a compressed NumPy archive inside the configured data directory.
    """

    def __init__(
        self,
        output_dir: str | Path = "data/analog_frames",
        active_resolution: tuple[int, int] = (640, 480),
        sample_rate_hz: int = 57_272_720,
        timing: AnalogTiming | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.active_width, self.active_height = active_resolution
        self.sample_rate_hz = sample_rate_hz
        self.timing = timing or AnalogTiming()

        self.sync_level = -0.4  # normalized volts relative to blanking
        self.blanking_level = 0.0
        self.white_level = 0.7

        self.line_samples = self._us_to_samples(self.timing.line_duration_us)
        self.sync_samples = self._us_to_samples(self.timing.sync_pulse_us)
        self.back_porch_samples = self._us_to_samples(self.timing.back_porch_us)
        self.front_porch_samples = self._us_to_samples(self.timing.front_porch_us)

        used = self.sync_samples + self.back_porch_samples + self.front_porch_samples
        self.active_samples = max(1, self.line_samples - used)
        self.samples_per_pixel = max(1, self.active_samples // self.active_width)

        self._sync_segment = np.full(self.sync_samples, self.sync_level, dtype=np.float32)
        self._back_porch_segment = np.full(
            self.back_porch_samples, self.blanking_level, dtype=np.float32
        )
        self._front_porch_segment = np.full(
            self.front_porch_samples, self.blanking_level, dtype=np.float32
        )

    def capture_stream(
        self,
        source: int | str = 1,
        frame_limit: int | None = None,
    ) -> List[Path]:
        """Capture frames from an OpenCV source and persist their analog representation."""
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open video source: {source}")

        saved_paths: List[Path] = []
        frame_counter = 0

        try:
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break

                waveform = self.frame_to_waveform(frame, frame_counter)
                saved_paths.append(self._persist_waveform(waveform, frame_counter))
                frame_counter += 1

                if frame_limit is not None and frame_counter >= frame_limit:
                    break
        finally:
            capture.release()

        if not saved_paths:
            raise RuntimeError("No frames captured from video source.")

        return saved_paths

    def ingest_frames(
        self,
        frames: Iterable[np.ndarray],
        start_frame: int = 0,
    ) -> List[Path]:
        """Persist analog waveforms for an arbitrary iterable of frames."""
        saved_paths: List[Path] = []
        frame_counter = start_frame

        for frame in frames:
            waveform = self.frame_to_waveform(frame, frame_counter)
            saved_paths.append(self._persist_waveform(waveform, frame_counter))
            frame_counter += 1

        if not saved_paths:
            raise RuntimeError("Frame iterable was empty.")

        return saved_paths

    def frame_to_waveform(self, frame: np.ndarray, frame_counter: int) -> np.ndarray:
        """Convert a single frame into a concatenated analog waveform buffer."""
        processed = self._normalize_frame(frame)
        lines = [self._line_waveform(row) for row in processed]
        vbi_lines = self._vbi_lines(frame_counter)

        waveform = np.concatenate(vbi_lines + lines).astype(np.float32, copy=False)
        return waveform

    def _normalize_frame(self, frame: np.ndarray) -> np.ndarray:
        """Resize the frame and produce a luminance-only matrix in [0, 1]."""
        resized = cv2.resize(frame, (self.active_width, self.active_height))
        if resized.ndim == 3 and resized.shape[2] == 3:
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        else:
            gray = resized

        luminance = gray.astype(np.float32) / 255.0
        return luminance

    def _line_waveform(self, row: np.ndarray) -> np.ndarray:
        """Create a full scan-line waveform for a single raster row."""
        video_scale = self.blanking_level + row * (self.white_level - self.blanking_level)
        active = np.repeat(video_scale, self.samples_per_pixel)

        if active.size < self.active_samples:
            pad = self.active_samples - active.size
            active = np.pad(active, (0, pad), constant_values=self.blanking_level)
        else:
            active = active[: self.active_samples]

        return np.concatenate(
            (self._sync_segment, self._back_porch_segment, active, self._front_porch_segment)
        )

    def _vbi_lines(self, frame_counter: int) -> List[np.ndarray]:
        """Simulate the vertical blanking interval with embedded frame counter bits."""
        bits = self._frame_counter_bits(frame_counter)
        lines: List[np.ndarray] = []

        for idx in range(self.timing.vbi_lines):
            line = self._blank_line()
            bit = bits[idx % len(bits)]
            start = self.sync_samples + self.back_porch_samples
            end = min(start + 32, start + self.active_samples)
            if bit == "1":
                line[start:end] = self.white_level
            lines.append(line)

        return lines

    def _blank_line(self) -> np.ndarray:
        """Return a blanking-level line with sync and porch segments."""
        active = np.full(self.active_samples, self.blanking_level, dtype=np.float32)
        return np.concatenate(
            (self._sync_segment, self._back_porch_segment, active, self._front_porch_segment)
        )

    def _frame_counter_bits(self, frame_counter: int) -> str:
        """Return a zero-padded binary string of the frame counter."""
        return format(frame_counter % (1 << 32), "032b")

    def _persist_waveform(self, waveform: np.ndarray, frame_counter: int) -> Path:
        """Persist waveform and metadata as a compressed NumPy archive."""
        target = self.output_dir / f"frame_{frame_counter:06d}.npz"
        np.savez_compressed(
            target,
            waveform=waveform,
            sample_rate=np.array(self.sample_rate_hz, dtype=np.float32),
            line_samples=np.array(self.line_samples, dtype=np.int32),
            frame_counter=np.array(frame_counter, dtype=np.int64),
            active_width=np.array(self.active_width, dtype=np.int32),
            active_height=np.array(self.active_height, dtype=np.int32),
        )
        return target

    def _us_to_samples(self, duration_us: float) -> int:
        """Convert a microsecond duration to integer samples at the configured rate."""
        return max(1, int(round(self.sample_rate_hz * duration_us * 1e-6)))


