"""
campaign.py — Campaign spec loading + deterministic hard filters.

A campaign spec is a YAML file in campaigns/ that describes one client
campaign: the brief, target niches, and the measurable criteria that can be
checked with arithmetic alone (follower band, engagement floor, recency).

Hard filters run BEFORE any reel download or LLM call. A creator failing on
metrics costs one Modash request, not a video download + transcription +
Claude call. Creators above the VIP ceiling are routed to review, not
rejected — they need bespoke handling, not a "no".
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class HardFilterResult:
    """Outcome of the deterministic pre-checks for one creator."""
    passed: bool
    bucket: str = ""        # "" | "rejected" | "review"
    category: str = ""      # machine-readable reason code
    reason: str = ""        # one-line human explanation


@dataclass
class CampaignSpec:
    """One client campaign: brief + measurable criteria."""
    name: str
    brief: str = ""
    target_niches: list = field(default_factory=list)
    judgment_notes: str = ""
    client_folder: Optional[str] = None   # knowledge/clients/<folder>/ to inject

    # Hard filters — all optional; unset means "don't check"
    min_followers: Optional[int] = None
    vip_review_above: Optional[int] = None
    min_engagement_pct: Optional[float] = None
    max_days_since_last_post: Optional[int] = None
    exclude_private: bool = True

    # Audience check (Modash report, costs credits) — runs ONLY for creators
    # the LLM approves. Below min_pct → demoted to review (not rejected —
    # third-party audience estimates are noisy; a human makes the final call).
    audience_target_country: Optional[str] = None
    audience_min_pct: Optional[float] = None

    @classmethod
    def load(cls, path: str | Path) -> "CampaignSpec":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        hf = raw.get("hard_filters", {}) or {}
        aud = raw.get("audience", {}) or {}
        return cls(
            name=raw.get("name") or path.stem,
            brief=(raw.get("brief") or "").strip(),
            target_niches=raw.get("target_niches") or [],
            judgment_notes=(raw.get("judgment_notes") or "").strip(),
            client_folder=raw.get("client_folder"),
            min_followers=hf.get("min_followers"),
            vip_review_above=hf.get("vip_review_above"),
            min_engagement_pct=hf.get("min_engagement_pct"),
            max_days_since_last_post=hf.get("max_days_since_last_post"),
            exclude_private=bool(hf.get("exclude_private", True)),
            audience_target_country=aud.get("target_country"),
            audience_min_pct=aud.get("min_pct"),
        )

    def apply_hard_filters(self, metrics: dict) -> HardFilterResult:
        """
        Check one creator's scored metrics (output of scorer.score_profile)
        against the campaign's measurable criteria.

        Check order matters: VIP routing comes before engagement/recency so
        a mega-account with collapsed engagement still goes to bespoke review
        (matching how the human team treats them) rather than a metric reject.
        """
        followers = int(metrics.get("followers") or 0)
        eng_rate = float(metrics.get("avg_engagement_rate") or 0.0)
        days_since = metrics.get("days_since_last_post")

        if self.exclude_private and metrics.get("ig_private"):
            return HardFilterResult(
                False, "rejected", "private_account",
                "Account is private — cannot be vetted or seeded.",
            )

        if self.min_followers is not None and followers < self.min_followers:
            return HardFilterResult(
                False, "rejected", "below_follower_min",
                f"{followers:,} followers is below the campaign minimum of "
                f"{self.min_followers:,}.",
            )

        if self.vip_review_above is not None and followers > self.vip_review_above:
            return HardFilterResult(
                False, "review", "vip_tier",
                f"{followers:,} followers is above the {self.vip_review_above:,} "
                f"VIP ceiling — route to bespoke review, not the standard pipeline.",
            )

        if self.min_engagement_pct is not None and eng_rate < self.min_engagement_pct:
            return HardFilterResult(
                False, "rejected", "low_engagement",
                f"Engagement rate {eng_rate}% is below the campaign floor of "
                f"{self.min_engagement_pct}% — signals inauthentic growth or a "
                f"dormant audience.",
            )

        if self.max_days_since_last_post is not None:
            if days_since is None:
                return HardFilterResult(
                    False, "rejected", "no_recent_posts",
                    "No datable posts found — account appears inactive.",
                )
            if days_since > self.max_days_since_last_post:
                return HardFilterResult(
                    False, "rejected", "dormant",
                    f"Last post was {days_since} days ago — over the campaign "
                    f"limit of {self.max_days_since_last_post} days.",
                )

        return HardFilterResult(True)
