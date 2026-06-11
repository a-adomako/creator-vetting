"""
frames.py — Sample representative frames from reel videos for LLM vision.

Replaces the CLIP layer in the campaign-vetting flow: instead of zero-shot
classifying every frame locally, we sample a few frames per reel, downscale
them, and send them to Claude alongside the transcript and captions in one
judgment call.

Cost control: frames are resized to max_dim on the long edge and encoded as
JPEG. At 512px / quality 70, a frame is roughly 25–60 KB → a few hundred
vision tokens. 2 frames × 3 reels ≈ 1–2¢ per creator on Haiku.
"""

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def sample_frames(
    video_path: Path,
    frames_per_reel: int = 2,
    max_dim: int = 512,
    jpeg_quality: int = 70,
) -> list[str]:
    """
    Sample evenly-spaced frames from one video.

    Returns a list of base64-encoded JPEG strings (no data: prefix), ready
    to drop into Anthropic image content blocks. Returns [] on any failure —
    the judgment call degrades gracefully to text-only.
    """
    try:
        import cv2
    except ImportError:
        logger.error("opencv-python not installed. Run: pip install opencv-python")
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("Could not open video: %s", video_path.name)
        return []

    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            return []

        # Evenly spaced positions, avoiding the very start/end (intro cards,
        # end freeze-frames): e.g. 2 frames → 30% and 70% through the video.
        n = max(1, frames_per_reel)
        positions = [int(total * (i + 1) / (n + 1)) for i in range(n)]

        encoded: list[str] = []
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret:
                continue

            h, w = frame.shape[:2]
            scale = max_dim / max(h, w)
            if scale < 1.0:
                frame = cv2.resize(
                    frame, (int(w * scale), int(h * scale)),
                    interpolation=cv2.INTER_AREA,
                )

            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            )
            if ok:
                encoded.append(base64.standard_b64encode(buf.tobytes()).decode("ascii"))

        return encoded
    except Exception as e:
        logger.warning("Frame sampling failed for %s: %s", video_path.name, e)
        return []
    finally:
        cap.release()


def sample_frames_batch(
    video_paths: list[Path],
    frames_per_reel: int = 2,
    max_dim: int = 512,
    jpeg_quality: int = 70,
    max_total_frames: int = 8,
) -> list[str]:
    """Sample frames across multiple reels, capped at max_total_frames."""
    frames: list[str] = []
    for path in video_paths:
        if len(frames) >= max_total_frames:
            break
        remaining = max_total_frames - len(frames)
        frames.extend(
            sample_frames(path, min(frames_per_reel, remaining), max_dim, jpeg_quality)
        )
    return frames
