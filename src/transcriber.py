"""
transcriber.py — Local audio transcription using faster-whisper.

faster-whisper is a CPU-optimised reimplementation of OpenAI Whisper.
It runs entirely locally with no API calls or ongoing costs.

Model sizes (trade speed for accuracy):
  tiny   ~5s/reel  on CPU  — fastest, good enough for niche signals
  base   ~15s/reel on CPU  — recommended default
  small  ~30s/reel on CPU  — better accuracy for accented speech
  medium ~60s/reel on CPU  — high accuracy, slow without GPU
  large  ~90s/reel on CPU  — best accuracy, GPU recommended

Audio is extracted from the video file using ffmpeg (must be installed on system).
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


def _extract_audio(video_path: Path, audio_path: Path) -> bool:
    """
    Extract audio from video file to a WAV file using ffmpeg.

    Returns True on success.
    16kHz mono WAV is the format faster-whisper expects.
    """
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-ar", "16000",       # 16kHz sample rate
        "-ac", "1",           # mono
        "-f", "wav",
        str(audio_path),
        "-y",                 # overwrite if exists
        "-loglevel", "error", # suppress ffmpeg output
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("ffmpeg failed: %s", e)
        return False


class Transcriber:
    """
    Transcribes video files to text using faster-whisper (local, free).

    The model is loaded once on init and reused across all calls —
    loading takes 1–5 seconds depending on model size.
    """

    def __init__(self, model_size: str = "base", language: Optional[str] = None, device: str = "auto"):
        self._model_size = model_size
        self._language = language  # None = auto-detect
        self._device = device
        self._model = None  # lazy-loaded on first use
        self._ffmpeg_available = _check_ffmpeg()

        if not self._ffmpeg_available:
            logger.warning(
                "ffmpeg not found on PATH. Transcription will be skipped. "
                "Install ffmpeg: https://ffmpeg.org/download.html"
            )

    def _load_model(self):
        """Lazy-load the Whisper model on first transcription call."""
        if self._model is not None:
            return

        try:
            from faster_whisper import WhisperModel

            # Resolve device
            device = self._device
            compute_type = "int8"  # works on both CPU and GPU, fastest

            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            logger.info("Loading faster-whisper '%s' model on %s...", self._model_size, device)
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute_type,
            )
            logger.info("Whisper model loaded.")
        except ImportError:
            logger.error(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            )
            self._model = None

    def transcribe(self, video_path: Path) -> str:
        """
        Transcribe audio from a video file.

        Returns the full transcript as a single string.
        Returns empty string if ffmpeg is missing, model failed to load,
        or transcription encounters an error.
        """
        return self.transcribe_detailed(video_path)["text"]

    def transcribe_detailed(self, video_path: Path) -> dict:
        """
        Transcribe with quality signals attached.

        Returns:
            text            str   — full transcript ("" on any failure)
            no_speech_prob  float — mean per-segment no-speech probability
                                    (None if unavailable)
            speech_confidence str — "high" / "medium" / "low" / "none"

        Whisper happily transcribes song lyrics from trending audio with the
        same confidence as real speech, so speech_confidence is a hint, not
        a verdict — the LLM judgment prompt carries the real defence (treat
        lyric-like text as ambient audio, not the creator's message).
        """
        empty = {"text": "", "no_speech_prob": None, "speech_confidence": "none"}

        if not self._ffmpeg_available:
            return empty

        self._load_model()
        if self._model is None:
            return empty

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = Path(tmp.name)

        try:
            if not _extract_audio(video_path, audio_path):
                logger.warning("Audio extraction failed for %s", video_path.name)
                return empty

            segments, _info = self._model.transcribe(
                str(audio_path),
                language=self._language,
                beam_size=1,         # faster beam search
                vad_filter=True,     # skip silent segments
            )

            texts: list[str] = []
            no_speech_probs: list[float] = []
            for seg in segments:
                texts.append(seg.text.strip())
                prob = getattr(seg, "no_speech_prob", None)
                if prob is not None:
                    no_speech_probs.append(float(prob))

            transcript = " ".join(t for t in texts if t).strip()
            mean_prob = (
                sum(no_speech_probs) / len(no_speech_probs)
                if no_speech_probs else None
            )

            if not transcript:
                confidence = "none"
            elif mean_prob is None:
                confidence = "medium"
            elif mean_prob > 0.5:
                confidence = "low"
            elif mean_prob > 0.25:
                confidence = "medium"
            else:
                confidence = "high"

            return {
                "text": transcript,
                "no_speech_prob": round(mean_prob, 3) if mean_prob is not None else None,
                "speech_confidence": confidence,
            }

        except Exception as e:
            logger.warning("Transcription failed for %s: %s", video_path.name, e)
            return empty
        finally:
            audio_path.unlink(missing_ok=True)

    def transcribe_batch(self, video_paths: list[Path]) -> list[str]:
        """Transcribe multiple videos, returning a list of transcripts in order."""
        return [self.transcribe(p) for p in video_paths]

    def transcribe_batch_detailed(self, video_paths: list[Path]) -> list[dict]:
        """Detailed transcription for multiple videos, in order."""
        return [self.transcribe_detailed(p) for p in video_paths]
