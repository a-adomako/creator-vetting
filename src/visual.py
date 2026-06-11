"""
visual.py — CLIP zero-shot scene classification + production quality analysis.

Uses:
  - OpenCV  to extract frames from video at a configured rate
  - CLIP    (open-clip-torch, local, free) for zero-shot scene classification
             Each frame is scored against niche text prompts defined in config.yaml

Production quality is estimated from frame-level signals:
  - Resolution (frame dimensions)
  - Average brightness (exposure quality)
  - Blur score (sharpness via Laplacian variance)

All models run locally. No API calls, no cost.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Production quality thresholds
_MIN_RESOLUTION_PIXELS = 720 * 1280  # HD minimum
_MIN_BRIGHTNESS = 40                  # 0–255 scale, below this = too dark
_MAX_BRIGHTNESS = 220                 # above this = overexposed
_MIN_BLUR_SCORE = 80                  # Laplacian variance; below = blurry


class VisualAnalyzer:
    """
    Analyzes video files for niche classification and production quality.

    clip_prompts: dict mapping niche name → list of text prompts
    frames_per_second: how many frames to sample per second of video
    """

    def __init__(
        self,
        clip_prompts: dict[str, list[str]],
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        frames_per_second: float = 0.5,
    ):
        self._clip_prompts = clip_prompts
        self._model_name = model_name
        self._pretrained = pretrained
        self._frames_per_second = frames_per_second

        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._text_features: Optional[dict[str, "torch.Tensor"]] = None  # pre-encoded prompts
        self._niches: list[str] = list(clip_prompts.keys())

    def _load_model(self):
        """Lazy-load CLIP model and pre-encode all text prompts."""
        if self._model is not None:
            return

        try:
            import open_clip
            import torch

            logger.info("Loading CLIP model %s (%s)...", self._model_name, self._pretrained)
            self._model, _, self._preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained
            )
            self._tokenizer = open_clip.get_tokenizer(self._model_name)
            self._model.eval()

            # Pre-encode all text prompts so we don't re-encode them per frame
            self._text_features = {}
            with torch.no_grad():
                for niche, prompts in self._clip_prompts.items():
                    tokens = self._tokenizer(prompts)
                    features = self._model.encode_text(tokens)
                    features = features / features.norm(dim=-1, keepdim=True)
                    self._text_features[niche] = features.mean(dim=0)  # average over prompts

            logger.info("CLIP model loaded and text prompts encoded.")
        except ImportError:
            logger.error(
                "open-clip-torch or torch is not installed. "
                "Run: pip install open-clip-torch torch"
            )
        except Exception as e:
            logger.error("Failed to load CLIP model: %s", e)

    def _extract_frames(self, video_path: Path) -> list[np.ndarray]:
        """Extract frames from video at the configured sample rate."""
        try:
            import cv2
        except ImportError:
            logger.error("opencv-python not installed. Run: pip install opencv-python")
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Could not open video: %s", video_path.name)
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_interval = max(1, int(fps / self._frames_per_second))

        frames = []
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_interval == 0:
                # Convert BGR (OpenCV default) to RGB
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            frame_idx += 1

        cap.release()
        return frames

    def _clip_scores(self, frames: list[np.ndarray]) -> dict[str, float]:
        """Run CLIP on frames and return average similarity per niche."""
        if not frames or self._model is None or self._text_features is None:
            return {niche: 0.0 for niche in self._niches}

        try:
            import torch
            from PIL import Image

            niche_scores: dict[str, list[float]] = {n: [] for n in self._niches}

            with torch.no_grad():
                for frame in frames:
                    pil_img = Image.fromarray(frame)
                    img_tensor = self._preprocess(pil_img).unsqueeze(0)
                    img_features = self._model.encode_image(img_tensor)
                    img_features = img_features / img_features.norm(dim=-1, keepdim=True)

                    for niche, text_feat in self._text_features.items():
                        similarity = (img_features @ text_feat.unsqueeze(-1)).item()
                        # Cosine similarity is in [-1, 1]; rescale to [0, 1]
                        score = (similarity + 1) / 2
                        niche_scores[niche].append(score)

            return {
                niche: float(np.mean(scores)) if scores else 0.0
                for niche, scores in niche_scores.items()
            }
        except Exception as e:
            logger.warning("CLIP scoring failed: %s", e)
            return {niche: 0.0 for niche in self._niches}

    def _production_quality(self, frames: list[np.ndarray]) -> str:
        """
        Estimate production quality from frame signals.

        Returns: "high", "medium", or "low"
        """
        if not frames:
            return "unknown"

        try:
            import cv2

            brightness_scores = []
            blur_scores = []
            resolutions = []

            for frame in frames:
                # Brightness (mean of grayscale)
                gray = np.mean(frame)
                brightness_scores.append(gray)

                # Blur (Laplacian variance — higher = sharper)
                gray_cv = np.dot(frame[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
                blur = cv2.Laplacian(gray_cv, cv2.CV_64F).var()
                blur_scores.append(blur)

                h, w = frame.shape[:2]
                resolutions.append(h * w)

            avg_brightness = np.mean(brightness_scores)
            avg_blur = np.mean(blur_scores)
            avg_resolution = np.mean(resolutions)

            quality_points = 0

            if avg_resolution >= _MIN_RESOLUTION_PIXELS:
                quality_points += 1
            if _MIN_BRIGHTNESS <= avg_brightness <= _MAX_BRIGHTNESS:
                quality_points += 1
            if avg_blur >= _MIN_BLUR_SCORE:
                quality_points += 1

            if quality_points >= 3:
                return "high"
            elif quality_points >= 2:
                return "medium"
            return "low"

        except Exception as e:
            logger.warning("Production quality check failed: %s", e)
            return "unknown"

    def analyze(self, video_path: Path) -> dict:
        """
        Analyze a single video file.

        Returns:
            clip_scores     dict[str, float]  — per-niche CLIP similarity (0–1)
            detected_scenes str               — top niche scene labels
            production_quality str            — "high" / "medium" / "low"
        """
        self._load_model()
        frames = self._extract_frames(video_path)

        clip_scores = self._clip_scores(frames)
        quality = self._production_quality(frames)

        # Top 3 niches by CLIP score for the detected_scenes field
        sorted_niches = sorted(clip_scores.items(), key=lambda x: x[1], reverse=True)
        detected_scenes = "|".join(n for n, s in sorted_niches[:3] if s > 0.45)

        return {
            "clip_scores": clip_scores,
            "detected_scenes": detected_scenes,
            "production_quality": quality,
        }

    def analyze_batch(self, video_paths: list[Path]) -> list[dict]:
        """Analyze multiple videos and return results in order."""
        return [self.analyze(p) for p in video_paths]
