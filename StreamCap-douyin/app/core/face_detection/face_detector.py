import cv2
import numpy as np
from typing import Optional, Tuple
import asyncio
import subprocess
import tempfile
import os
from pathlib import Path

class FaceDetector:
    def __init__(self, min_face_size: Tuple[int, int] = (50, 50), scale_factor: float = 1.1, min_neighbors: int = 5):
        """Initialize face detector with OpenCV's CascadeClassifier.
        
        Args:
            min_face_size: Minimum face size to detect (width, height)
            scale_factor: How much the image size is reduced at each image scale
            min_neighbors: How many neighbors each candidate rectangle should have to retain it
        """
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.min_face_size = min_face_size
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
    
    async def detect_faces(self, frame: np.ndarray) -> int:
        """Detect faces in a single frame.
        
        Args:
            frame: Input frame in BGR format
            
        Returns:
            Number of faces detected
        """
        # Convert to grayscale for face detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=self.min_face_size
        )
        
        return len(faces)
    
    async def check_first_frame_for_face(self, stream_url: str) -> bool:
        """Check if the first frame of a stream contains a face.
        
        Args:
            stream_url: URL of the stream to check
            
        Returns:
            bool: True if at least one face was detected in the first frame, False otherwise
        """
        # Create a temporary directory to store the frame
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = os.path.join(temp_dir, 'first_frame.jpg')
            
            # Use ffmpeg to capture only the first frame
            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-vframes', '1',  # Capture only 1 frame
                '-y',  # Overwrite output files without asking
                output_file
            ]
            
            try:
                # Run ffmpeg to capture the first frame
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
                
                # Check if frame file was created
                if not os.path.exists(output_file):
                    return False
                        
                # Read the frame
                frame = cv2.imread(output_file)
                if frame is None:
                    return False
                        
                # Check for faces
                num_faces = await self.detect_faces(frame)
                return num_faces > 0
                
            except (asyncio.TimeoutError, subprocess.SubprocessError) as e:
                print(f"Error checking first frame for faces: {e}")
                return False
            finally:
                # Clean up temporary files
                try:
                    if os.path.exists(output_file):
                        os.unlink(output_file)
                except OSError:
                    pass
    
    async def check_stream_for_faces(self, stream_url: str, check_duration: int = 10, sample_interval: float = 1.0) -> bool:
        """Check if a stream contains faces by sampling frames.
        
        Args:
            stream_url: URL of the stream to check
            check_duration: How many seconds to check the stream
            sample_interval: Interval in seconds between frame samples
            
        Returns:
            bool: True if at least one face was detected, False otherwise
        """
        # Create a temporary directory to store the stream
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = os.path.join(temp_dir, 'sample_%04d.jpg')
            
            # Use ffmpeg to capture frames from the stream
            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-vf', f'fps=1/{sample_interval}',  # Sample 1 frame per sample_interval seconds
                '-vframes', str(int(check_duration / sample_interval)),  # Total frames to capture
                '-y',  # Overwrite output files without asking
                output_file
            ]
            
            try:
                # Run ffmpeg to capture frames
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                await asyncio.wait_for(process.communicate(), timeout=check_duration * 2)
                
                # Check each captured frame for faces
                for frame_file in sorted(Path(temp_dir).glob('sample_*.jpg')):
                    if not frame_file.exists():
                        continue
                        
                    # Read the frame
                    frame = cv2.imread(str(frame_file))
                    if frame is None:
                        continue
                        
                    # Check for faces
                    num_faces = await self.detect_faces(frame)
                    if num_faces > 0:
                        return True
                
                return False
                
            except (asyncio.TimeoutError, subprocess.SubprocessError) as e:
                print(f"Error checking stream for faces: {e}")
                return False
            finally:
                # Clean up temporary files
                for frame_file in Path(temp_dir).glob('sample_*.jpg'):
                    try:
                        frame_file.unlink()
                    except OSError:
                        pass
