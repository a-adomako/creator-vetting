"""
ui_labels.py — Plain-language labels for tier letters and gate decisions.

Display-only. The CSV always stores the structured values (`A`/`B`/`C`/`D` for
tier, `rejected_<category>` for gate decisions) — these helpers translate
them into human sentences for the UI. Downstream tools that read the CSV are
unaffected.
"""

from typing import Optional


# ── Tier letters (A/B/C/D) → plain-language quality label ────────────────────

TIER_LABEL = {
    "A": "Excellent",
    "B": "Good",
    "C": "Borderline",
    "D": "Weak",
}

TIER_DESCRIPTION = {
    "A": "Top quality — strong engagement, posting cadence, and audience signals",
    "B": "Solid — meets bar on most signals, worth shortlisting",
    "C": "Borderline — has some red flags; needs human review",
    "D": "Weak — fails on multiple signals (low engagement, stale, etc.)",
}


def tier_label(tier: Optional[str]) -> str:
    """'B' → 'Good (B)'. Unknown → '—'."""
    if not tier or not str(tier).strip():
        return "—"
    letter = str(tier).strip().upper()
    label = TIER_LABEL.get(letter)
    if not label:
        return letter
    return f"{label} ({letter})"


def tier_description(tier: Optional[str]) -> str:
    if not tier:
        return ""
    return TIER_DESCRIPTION.get(str(tier).strip().upper(), "")


# ── Gate decisions → plain-language label ────────────────────────────────────

GATE_LABEL = {
    "passes": "Cleared for central database",
    "rejected_adult_sexual_content": "Held back — adult or sexual content",
    "rejected_mlm": "Held back — MLM involvement",
    "rejected_eating_disorder_advocacy": "Held back — eating-disorder advocacy",
    "rejected_pseudo_medical": "Held back — pseudo-medical claims",
    "rejected_anti_medical_advocacy": "Held back — anti-medical advocacy",
    "rejected_political_extremism": "Held back — political extremism",
    "rejected_hate_speech": "Held back — hate speech",
    "rejected_harassment_illegal": "Held back — harassment or illegal content",
    "rejected_religious_extremism": "Held back — religious extremism",
    "rejected_brand_safety_critical": "Held back — brand-safety score critically low",
    "rejected_multi_signal_floor": "Held back — multiple poor-quality signals at once",
    "rejected_llm_recommendation": "Held back — LLM recommended a hard no",
}


def gate_label(decision: Optional[str]) -> str:
    """'rejected_mlm' → 'Held back — MLM involvement'. Unknown → echoes input."""
    if not decision:
        return "—"
    return GATE_LABEL.get(str(decision).strip(), str(decision))


# ── LLM recommendation → plain-language label ────────────────────────────────

LLM_RECOMMENDATION_LABEL = {
    "yes": "Yes — recommend",
    "maybe": "Maybe — needs human review",
    "no": "No — do not shortlist",
}


def llm_recommendation_label(rec: Optional[str]) -> str:
    if not rec:
        return "—"
    return LLM_RECOMMENDATION_LABEL.get(str(rec).strip().lower(), str(rec))


# ── Flags (pipe-separated) → friendlier comma-separated list ─────────────────

FLAG_LABEL = {
    "private_account": "Private account",
    "low_engagement": "Low engagement",
    "no_recent_posts": "No recent posts",
    "high_following_ratio": "Follows more than followers",
}


def flags_label(flags: Optional[str]) -> str:
    """'private_account|low_engagement|stale_120d' → friendly comma list."""
    if not flags:
        return ""
    parts = []
    for raw in str(flags).split("|"):
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith("stale_"):
            days = raw.replace("stale_", "").replace("d", "")
            parts.append(f"Stale for {days} days")
        else:
            parts.append(FLAG_LABEL.get(raw, raw.replace("_", " ").capitalize()))
    return ", ".join(parts)


# ── Friendly column display names ────────────────────────────────────────────

COLUMN_FRIENDLY = {
    "ig_username": "Username",
    "ig_full_name": "Display name",
    "ig_verified": "Verified",
    "ig_private": "Private",
    "followers": "Followers",
    "following": "Following",
    "total_posts": "Total posts",
    "follower_following_ratio": "Follower/following ratio",
    "avg_engagement_rate": "Engagement rate (%)",
    "posts_last_30_days": "Posts in last 30 days",
    "days_since_last_post": "Days since last post",
    "audience_quality_score": "Audience quality (0–100)",
    "overall_quality_score": "Overall quality (0–100)",
    "tier": "Quality tier",
    "flags": "Issues flagged",
    "primary_niche": "Primary niche",
    "secondary_niche": "Secondary niche",
    "niche_confidence": "Niche confidence (0–100)",
    "brand_fit_score": "Brand fit (0–100)",
    "content_summary": "What their content looks like",
    "detected_scenes": "Scenes detected in reels",
    "production_quality": "Production quality",
    "reels_analyzed": "Reels analysed",
    "transcript_sample": "Transcript sample",
    "llm_primary_niche": "AI: primary niche",
    "llm_brand_fit_score": "AI: brand fit (0–100)",
    "llm_content_summary": "AI: content summary",
    "llm_authenticity": "AI: authenticity (0–100)",
    "llm_content_consistency": "AI: content consistency (0–100)",
    "llm_brand_safety": "AI: brand safety (0–100)",
    "llm_production_quality_score": "AI: production quality (0–100)",
    "llm_recommendation": "AI: recommendation",
    "llm_reasoning": "AI: reasoning",
    "llm_strengths": "AI: strengths",
    "llm_concerns": "AI: concerns",
    "llm_quality_score": "AI: overall quality (0–100)",
    "gate_decision": "Database gate",
    "gate_reason": "Database gate reason",
    "push_to_spine": "Eligible for central DB",
}


def friendly_column(col: str) -> str:
    return COLUMN_FRIENDLY.get(col, col)


# ── The "essential" columns to surface by default in any table view ──────────

ESSENTIAL_COLUMNS = [
    "ig_username",
    "ig_full_name",
    "followers",
    "avg_engagement_rate",
    "tier",
    "primary_niche",
    "brand_fit_score",
    "llm_recommendation",
    "gate_decision",
]
