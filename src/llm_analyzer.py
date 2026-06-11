"""
llm_analyzer.py — LLM-based creator analysis for the pipeline.

After transcript + CLIP analysis, this module sends creator data to Claude
for qualitative assessment: niche classification, brand fit, and quality
scoring across 4 dimensions (authenticity, consistency, brand safety,
production quality).

Results are stored as llm_* columns alongside the existing keyword/CLIP
scores — both signal sets are preserved.

Calibration: corrections and approved examples from knowledge/ are injected
into the prompt automatically, so Claude's judgments align with your agency's
taste over time.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_QUALITY_DIMS = (
    "llm_authenticity",
    "llm_content_consistency",
    "llm_brand_safety",
    "llm_production_quality_score",
)

_SYSTEM_TEMPLATE = """\
You are an experienced influencer selection specialist at an influencer marketing agency.
You evaluate Instagram creators for brand campaigns.

Your agency's brand context:
{brand_context}

Target niches: {target_niches}

When scoring, use the full 0–100 range. Do not cluster scores around 50 — differentiate clearly.
A score of 90+ means exceptional. 70–89 is solid. 50–69 is average. Below 50 means concerns.

{calibration}\
"""

_PROMPT_TEMPLATE = """\
Analyze this Instagram creator profile.

Creator: @{username}
Followers: {followers}
Engagement Rate: {engagement_rate}%

--- TRANSCRIPT (spoken content from their reels) ---
{transcript}
---

Detected Visual Scenes: {detected_scenes}
Production Quality (technical signal): {production_quality}

Based on this data, respond with ONLY a valid JSON object — no explanation, no markdown fences, \
just the raw JSON:
{{
  "llm_primary_niche": "<the single best-fitting niche from the target niches list>",
  "llm_brand_fit_score": <0-100 integer — how well this creator fits the brand context>,
  "llm_content_summary": "<1-2 sentence qualitative description of what this creator is about and their style>",
  "llm_authenticity": <0-100 — genuine personal voice vs scripted/salesy>,
  "llm_content_consistency": <0-100 — consistent focused niche vs scattered topics>,
  "llm_brand_safety": <0-100 — 100 = fully brand-safe, lower = red flags present>,
  "llm_production_quality_score": <0-100 — video/audio/editing quality inferred from content>,
  "llm_recommendation": "yes" | "maybe" | "no",
  "llm_reasoning": "<2-3 sentence qualitative explanation referencing specific content — why this score, what stood out, what to watch out for>",
  "llm_strengths": ["strength 1", "strength 2", "strength 3"],
  "llm_concerns": ["concern 1", "concern 2"]
}}\
"""


def _load_calibration(knowledge_dir: Path, client_dir: Path = None) -> str:
    """
    Load agency standards + client-specific training data for prompt injection.

    Load order:
      1. knowledge/expertise.md         — global agency standards (always)
      2. client_dir/my_style.md         — client scoring philosophy (if client active)
      3. client_dir/corrections.md      — past corrections for this client
      4. client_dir/good_examples.md    — approved examples for this client
    """
    parts = []

    # 1. Global agency standards — always first
    expertise = knowledge_dir / "expertise.md"
    if expertise.exists():
        content = expertise.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"=== AGENCY STANDARDS & SELECTION CRITERIA ===\n{content}")

    # 2–5. Client-specific files
    if client_dir and client_dir.exists():
        for fname, header in (
            ("my_style.md",     "=== CLIENT SCORING STYLE ==="),
            ("corrections.md",  "=== PAST CORRECTIONS FOR THIS CLIENT ==="),
            ("good_examples.md","=== APPROVED EXAMPLES FOR THIS CLIENT ==="),
            ("calibration_labels.md", "=== HUMAN-LABELLED EXAMPLES (CALIBRATION DECK) ==="),
        ):
            fpath = client_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"{header}\n{content}")

    if parts:
        return "\n\n".join(parts) + "\n\nUse all of the above to match my judgment exactly."
    return ""


def _parse_json(text: str) -> Optional[dict]:
    """Extract and parse the first JSON object from a string."""
    text = text.strip()
    # Try direct parse first (model returned clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting first {...} block (model wrapped it in text)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


class LLMAnalyzer:
    """
    Sends creator transcript + visual data to Claude for qualitative analysis.
    Results are merged into the pipeline output as llm_* columns.
    """

    def __init__(
        self,
        llm_client,
        config: dict,
        knowledge_dir: Path = None,
        client_dir: Path = None,
    ):
        self.llm = llm_client
        self.brand_context = config.get(
            "brand_context",
            "General lifestyle and wellness brands.",
        )
        self.target_niches = config.get("target_niches", [])
        # Default knowledge_dir: sibling of src/ (project root / knowledge)
        if knowledge_dir is None:
            knowledge_dir = Path(__file__).parent.parent / "knowledge"
        self.knowledge_dir = knowledge_dir
        self.client_dir = client_dir  # Optional: overrides brand_context/niches if set

    def analyze(
        self,
        username: str,
        transcript: str,
        detected_scenes: str,
        production_quality: str,
        followers: Optional[int] = None,
        engagement_rate: Optional[float] = None,
    ) -> dict:
        """
        Run LLM analysis for a single creator.

        Returns a dict of llm_* fields to merge into the pipeline output.
        On any failure returns safe defaults with llm_error set.
        """
        # Use client profile if available, fall back to global config
        brand_context = self.brand_context
        target_niches = self.target_niches
        if self.client_dir and (self.client_dir / "profile.yaml").exists():
            try:
                import yaml
                profile = yaml.safe_load((self.client_dir / "profile.yaml").read_text(encoding="utf-8"))
                brand_context = profile.get("brand_context", brand_context)
                target_niches = profile.get("target_niches", target_niches)
            except Exception:
                pass

        calibration = _load_calibration(self.knowledge_dir, self.client_dir)

        system = _SYSTEM_TEMPLATE.format(
            brand_context=brand_context,
            target_niches=", ".join(target_niches) if target_niches else "any",
            calibration=calibration,
        )

        prompt = _PROMPT_TEMPLATE.format(
            username=username,
            followers=f"{followers:,}" if followers else "unknown",
            engagement_rate=f"{engagement_rate:.1f}" if engagement_rate is not None else "unknown",
            transcript=transcript[:3000] if transcript else "No transcript available",
            detected_scenes=detected_scenes or "No scene data",
            production_quality=production_quality or "unknown",
        )

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
            )
            result = _parse_json(response.get("content", ""))
            if result is None:
                logger.warning("@%s: LLM returned unparseable response", username)
                return self._defaults(error="unparseable_response")

            # Compute quality score as average of 4 dimension scores
            dim_scores = [
                result[d]
                for d in _QUALITY_DIMS
                if isinstance(result.get(d), (int, float))
            ]
            result["llm_quality_score"] = (
                int(sum(dim_scores) / len(dim_scores)) if dim_scores else None
            )

            # Flatten list fields to pipe-separated strings for CSV compatibility
            for list_field in ("llm_strengths", "llm_concerns"):
                val = result.get(list_field)
                if isinstance(val, list):
                    result[list_field] = " | ".join(str(v) for v in val if v)
                elif val is None:
                    result[list_field] = ""

            return result

        except Exception as e:
            logger.warning("@%s: LLM analysis failed — %s", username, e)
            return self._defaults(error=str(e))

    def _defaults(self, error: str = "") -> dict:
        return {
            "llm_primary_niche": None,
            "llm_brand_fit_score": None,
            "llm_content_summary": None,
            "llm_quality_score": None,
            "llm_authenticity": None,
            "llm_content_consistency": None,
            "llm_brand_safety": None,
            "llm_production_quality_score": None,
            "llm_recommendation": None,
            "llm_reasoning": None,
            "llm_strengths": None,
            "llm_concerns": None,
            "llm_error": error or None,
        }
