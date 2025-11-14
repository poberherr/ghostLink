#!/usr/bin/env python3
"""Create a test video pattern for testing the analog pipeline."""

import numpy as np
import cv2

def create_test_video(filename, duration_sec=3, fps=30):
    """Create a test video with various patterns."""
    width, height = 640, 480
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    
    num_frames = int(duration_sec * fps)
    
    for frame_num in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Create different patterns
        if frame_num < num_frames // 3:
            # Pattern 1: Moving gradient
            phase = frame_num / num_frames * 4 * np.pi
            for y in range(height):
                value = int(128 + 127 * np.sin(y * 0.05 + phase))
                frame[y, :] = [value, value, value]
        
        elif frame_num < 2 * num_frames // 3:
            # Pattern 2: Checkerboard
            square_size = 40
            for y in range(height):
                for x in range(width):
                    if ((x // square_size) + (y // square_size)) % 2 == 0:
                        frame[y, x] = [255, 255, 255]
        
        else:
            # Pattern 3: Circular gradient
            center_x, center_y = width // 2, height // 2
            phase = (frame_num - 2*num_frames//3) / (num_frames//3) * 2 * np.pi
            for y in range(height):
                for x in range(width):
                    dist = np.sqrt((x - center_x)**2 + (y - center_y)**2)
                    value = int(128 + 127 * np.sin(dist * 0.05 + phase))
                    frame[y, x] = [value, value, value]
        
        # Add frame counter text
        cv2.putText(frame, f"Frame {frame_num}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        
        writer.write(frame)
    
    writer.release()
    print(f"Created test video: {filename} ({num_frames} frames)")

if __name__ == "__main__":
    create_test_video("test_pattern.mp4")


