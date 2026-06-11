"""
scorer.py — Engagement, audience quality, and overall tier scoring.

All thresholds are read from config.yaml — nothing is hardcoded here.
Input is raw Apify profile data. Output is a flat dict of scored fields
ready to be appended as new columns to the output CSV.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pure calculation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def calculate_engagement_rate(posts: list[dict], followers: int) -> float:
    """
    Average engagement rate across recent posts, expressed as a percentage.

    engagement_rate = mean((likes + comments) / followers) × 100
    """
    if not posts or not followers:
        return 0.0
    rates = [
        _safe_div(p.get("likesCount", 0) + p.get("commentsCount", 0), followers)
        for p in posts
        if isinstance(p, dict)
    ]
    if not rates:
        return 0.0
    return round(sum(rates) / len(rates) * 100, 2)


def posts_in_last_n_days(posts: list[dict], days: int = 30) -> int:
    """Count posts published within the last N days."""
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    count = 0
    for post in posts:
        ts = post.get("timestamp")
        if ts:
            try:
                post_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if post_time >= cutoff:
                    count += 1
            except (ValueError, AttributeError):
                pass
    return count


def days_since_last_post(posts: list[dict]) -> Optional[int]:
    """Return the number of days since the most recent post, or None."""
    latest_ts: Optional[float] = None
    for post in posts:
        ts = post.get("timestamp")
        if ts:
            try:
                post_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if latest_ts is None or post_time > latest_ts:
                    latest_ts = post_time
            except (ValueError, AttributeError):
                pass
    if latest_ts is None:
        return None
    return int((datetime.now(timezone.utc).timestamp() - latest_ts) / 86400)


# ─────────────────────────────────────────────────────────────────────────────
# Component scorers (each returns 0–100)
# ─────────────────────────────────────────────────────────────────────────────

def engagement_score(rate: float, thresholds: dict) -> int:
    excellent = thresholds.get("excellent", 6.0)
    good = thresholds.get("good", 3.0)
    average = thresholds.get("average", 1.0)

    if rate >= excellent:
        return 100
    elif rate >= good:
        return 75
    elif rate >= average:
        return 50
    else:
        return max(0, int(_safe_div(rate, average) * 50))


def audience_quality_score(followers: int, following: int, engagement_rate: float) -> int:
    """
    Composite audience quality signal:
      - Follower/following ratio (fake/follow-back accounts have high following)
      - Engagement relative to followers (bots don't engage)
    """
    score = 50  # neutral baseline

    ratio = _safe_div(followers, max(following, 1))
    if ratio >= 10:
        score += 25
    elif ratio >= 5:
        score += 15
    elif ratio >= 2:
        score += 5
    elif ratio < 0.5:
        score -= 20

    if engagement_rate >= 6:
        score += 25
    elif engagement_rate >= 3:
        score += 15
    elif engagement_rate >= 1:
        score += 5
    elif engagement_rate < 0.5:
        score -= 15

    return max(0, min(100, score))


def frequency_score(posts_30d: int, thresholds: dict) -> int:
    active = thresholds.get("active", 8)
    occasional = thresholds.get("occasional", 3)

    if posts_30d >= active:
        return 100
    elif posts_30d >= occasional:
        return 60
    elif posts_30d >= 1:
        return 30
    return 0


def recency_score(days_since: Optional[int], flag_days: int = 30) -> int:
    if days_since is None:
        return 0
    if days_since <= 7:
        return 100
    elif days_since <= flag_days:
        return 70
    elif days_since <= 90:
        return 30
    return 0


def overall_quality_score(
    eng_score: int,
    aud_score: int,
    freq_score: int,
    rec_score: int,
    weights: dict,
) -> int:
    return round(
        eng_score * weights.get("engagement_rate", 0.40)
        + aud_score * weights.get("audience_quality", 0.30)
        + freq_score * weights.get("posting_frequency", 0.20)
        + rec_score * weights.get("recency", 0.10)
    )


def assign_tier(score: int, thresholds: dict) -> str:
    if score >= thresholds.get("A", 75):
        return "A"
    elif score >= thresholds.get("B", 50):
        return "B"
    elif score >= thresholds.get("C", 25):
        return "C"
    return "D"


def build_flags(
    private: bool,
    engagement_rate: float,
    days_since: Optional[int],
    posts_30d: int,
    followers: int,
    following: int,
    recency_flag_days: int,
) -> list[str]:
    flags = []
    if private:
        flags.append("private_account")
    if engagement_rate < 0.5 and engagement_rate >= 0:
        flags.append("low_engagement")
    if days_since is not None and days_since > recency_flag_days:
        flags.append(f"stale_{days_since}d")
    if posts_30d == 0:
        flags.append("no_recent_posts")
    if following > 0 and _safe_div(followers, following) < 0.5:
        flags.append("high_following_ratio")
    return flags


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def score_profile(profile: dict, config: dict) -> dict:
    """
    Compute all engagement/audience scores for a single Apify profile dict.

    Returns a flat dict of scored fields. Analysis fields (niche, brand_fit, etc.)
    are added separately by the pipeline after analyzer.py runs.
    """
    posts = profile.get("latestPosts", []) or []
    followers = int(profile.get("followersCount", 0) or 0)
    following = int(profile.get("followsCount", 0) or 0)

    eng_rate = calculate_engagement_rate(posts, followers)
    posts_30d = posts_in_last_n_days(posts, 30)
    days_since = days_since_last_post(posts)

    eng_s = engagement_score(eng_rate, config.get("engagement_thresholds", {}))
    aud_s = audience_quality_score(followers, following, eng_rate)
    freq_s = frequency_score(posts_30d, config.get("frequency_thresholds", {}))
    rec_s = recency_score(days_since, config.get("recency_flag_days", 30))

    quality = overall_quality_score(
        eng_s, aud_s, freq_s, rec_s, config.get("quality_weights", {})
    )
    tier = assign_tier(quality, config.get("tier_thresholds", {}))
    flags = build_flags(
        bool(profile.get("private")),
        eng_rate,
        days_since,
        posts_30d,
        followers,
        following,
        config.get("recency_flag_days", 30),
    )

    return {
        "ig_username": profile.get("username", ""),
        "ig_full_name": profile.get("fullName", ""),
        "ig_verified": bool(profile.get("verified", False)),
        "ig_private": bool(profile.get("private", False)),
        "followers": followers,
        "following": following,
        "total_posts": int(profile.get("postsCount", 0) or 0),
        "follower_following_ratio": round(_safe_div(followers, max(following, 1)), 2),
        "avg_engagement_rate": eng_rate,
        "posts_last_30_days": posts_30d,
        "days_since_last_post": days_since,
        "audience_quality_score": aud_s,
        "overall_quality_score": quality,
        "tier": tier,
        "flags": "|".join(flags) if flags else "",
    }
