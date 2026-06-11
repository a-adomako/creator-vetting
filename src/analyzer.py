"""
analyzer.py — Fuses transcript + visual signals into niche classification and brand fit scores.

Two signal sources:
  1. Transcript score  — keyword frequency per niche from spoken words
  2. Visual score      — CLIP cosine similarity per niche from video frames

These are combined with configurable weights (default 60% visual / 40% transcript).

All processing is local. No API calls.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def _score_transcript(text: str, niche_keywords: dict[str, list[str]]) -> dict[str, float]:
    """
    Score transcript text against niche keyword lists.

    Returns a dict of niche → raw score (count of keyword matches).
    Multi-word phrases are matched as substrings.
    """
    if not text:
        return {niche: 0.0 for niche in niche_keywords}

    text_lower = text.lower()
    scores: dict[str, float] = {}

    for niche, keywords in niche_keywords.items():
        count = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            # Whole-word match for single words, substring match for phrases
            if " " in kw_lower:
                count += text_lower.count(kw_lower)
            else:
                count += len(re.findall(r"\b" + re.escape(kw_lower) + r"\b", text_lower))
        scores[niche] = count

    return scores


def _normalise(scores: dict[str, float]) -> dict[str, float]:
    """Normalise a dict of scores so the max value is 1.0."""
    max_val = max(scores.values(), default=0.0)
    if max_val == 0:
        return {k: 0.0 for k in scores}
    return {k: v / max_val for k, v in scores.items()}


def _top_keywords(text: str, niche_keywords: dict[str, list[str]], niche: str, top_n: int = 5) -> list[str]:
    """Return the top N keywords from a given niche that appear in the transcript."""
    if not text or niche not in niche_keywords:
        return []

    text_lower = text.lower()
    found = []
    for kw in niche_keywords[niche]:
        kw_lower = kw.lower()
        if " " in kw_lower:
            if kw_lower in text_lower:
                found.append(kw)
        elif re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower):
            found.append(kw)

    return found[:top_n]


class NicheAnalyzer:
    """
    Combines transcript keyword scores and CLIP visual scores to determine
    a creator's primary niche and brand fit.
    """

    def __init__(
        self,
        niches: list[str],
        target_niches: list[str],
        niche_keywords: dict[str, list[str]],
        visual_weight: float = 0.6,
    ):
        self._niches = niches
        self._target_niches = set(target_niches)
        self._niche_keywords = niche_keywords
        self._visual_weight = visual_weight
        self._transcript_weight = 1.0 - visual_weight

    def analyze(
        self,
        transcripts: list[str],
        visual_results: list[dict],
    ) -> dict:
        """
        Fuse transcript and visual signals from multiple reels into a single result.

        transcripts     — list of transcript strings (one per reel)
        visual_results  — list of dicts from visual.py analyze() (one per reel)

        Returns:
            primary_niche       str
            secondary_niche     str | None
            niche_confidence    int (0–100)
            brand_fit_score     int (0–100)
            content_summary     str
            detected_scenes     str  (pipe-separated from visual)
            production_quality  str  (best quality seen across reels)
        """
        # ── Transcript signal ─────────────────────────────────────
        combined_transcript = " ".join(t for t in transcripts if t)
        raw_transcript_scores = _score_transcript(combined_transcript, self._niche_keywords)
        norm_transcript = _normalise(raw_transcript_scores)

        # ── Visual signal ─────────────────────────────────────────
        # Average CLIP scores across all reels
        if visual_results:
            all_clip: dict[str, list[float]] = {n: [] for n in self._niches}
            for vr in visual_results:
                for niche, score in vr.get("clip_scores", {}).items():
                    if niche in all_clip:
                        all_clip[niche].append(score)
            avg_clip = {
                n: (sum(v) / len(v) if v else 0.0) for n, v in all_clip.items()
            }
            norm_visual = _normalise(avg_clip)
        else:
            norm_visual = {n: 0.0 for n in self._niches}

        # ── Fuse signals ──────────────────────────────────────────
        fused: dict[str, float] = {}
        for niche in self._niches:
            v = norm_visual.get(niche, 0.0)
            t = norm_transcript.get(niche, 0.0)

            # If only one signal is available, use it fully
            if not visual_results:
                fused[niche] = t
            elif not combined_transcript:
                fused[niche] = v
            else:
                fused[niche] = v * self._visual_weight + t * self._transcript_weight

        sorted_niches = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        primary_niche = sorted_niches[0][0] if sorted_niches else "Unknown"
        primary_score = sorted_niches[0][1] if sorted_niches else 0.0
        secondary_niche = sorted_niches[1][0] if len(sorted_niches) > 1 and sorted_niches[1][1] > 0.1 else None

        # ── Confidence ────────────────────────────────────────────
        # Confidence is how dominant the top niche is over the second
        if len(sorted_niches) > 1 and sorted_niches[1][1] > 0:
            gap = primary_score - sorted_niches[1][1]
            confidence = min(100, int(50 + gap * 100))
        elif primary_score > 0:
            confidence = min(100, int(primary_score * 100))
        else:
            confidence = 0

        # ── Brand fit score ───────────────────────────────────────
        # Sum of fused scores for target niches, capped at 100
        target_score = sum(fused.get(n, 0.0) for n in self._target_niches)
        brand_fit = min(100, int(target_score * 80))  # scale factor keeps realistic range

        # ── Content summary ───────────────────────────────────────
        top_kws = _top_keywords(combined_transcript, self._niche_keywords, primary_niche)
        scenes = "|".join(
            {scene for vr in visual_results for scene in vr.get("detected_scenes", "").split("|") if scene}
        )
        summary_parts = []
        if scenes:
            summary_parts.append(f"Scenes: {scenes}")
        if top_kws:
            summary_parts.append(f"Keywords: {', '.join(top_kws)}")
        content_summary = " | ".join(summary_parts) or "No signal detected"

        # ── Production quality (best across reels) ────────────────
        quality_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
        best_quality = max(
            (vr.get("production_quality", "unknown") for vr in visual_results),
            key=lambda q: quality_rank.get(q, 0),
            default="unknown",
        )

        # ── Detected scenes (union across reels) ─────────────────
        all_scenes = "|".join(
            {s for vr in visual_results for s in vr.get("detected_scenes", "").split("|") if s}
        )

        return {
            "primary_niche": primary_niche,
            "secondary_niche": secondary_niche,
            "niche_confidence": confidence,
            "brand_fit_score": brand_fit,
            "content_summary": content_summary,
            "detected_scenes": all_scenes,
            "production_quality": best_quality,
        }
