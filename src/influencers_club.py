import os
import requests
from typing import Optional


BASE_URL = "https://api-dashboard.influencers.club"


class InfluencersClubAPI:
    """Wrapper for the Influencers.Club creator discovery API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("INFLUENCERS_CLUB_API_KEY")
        if not self.api_key:
            raise ValueError(
                "INFLUENCERS_CLUB_API_KEY not set. Provide it as an env var or pass it directly."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def discover(
        self,
        platform: str = "instagram",
        filters: Optional[dict] = None,
        limit: int = 20,
        page: int = 1
    ) -> dict:
        """Search for creators matching flexible filters.

        Args:
            platform: instagram, tiktok, youtube, twitch, twitter, onlyfans
            filters: dict with filter params (varies by platform). Try:
                     followers_min, followers_max, engagement_min, engagement_max,
                     niche, category, location, language, etc.
            limit: max results per page (1-100, default 20)
            page: page number for pagination (default 1)

        Returns:
            Raw API response dict with: total, limit, accounts, credits_left, trial_searches_left
        """
        body = {
            "platform": platform,
            "paging": {
                "limit": min(limit, 100),
                "page": page
            },
            "filters": filters or {}
        }
        r = self.session.post(
            f"{BASE_URL}/public/v1/discovery/",
            json=body,
            timeout=30
        )
        r.raise_for_status()
        return r.json()

    def parse_accounts(self, response: dict) -> list:
        """Extract clean account list from raw API response."""
        return [
            {
                "username": a["profile"]["username"],
                "full_name": a["profile"].get("full_name", ""),
                "followers": a["profile"].get("followers", 0),
                "engagement_percent": a["profile"].get("engagement_percent", 0.0),
                "user_id": a.get("user_id", ""),
            }
            for a in response.get("accounts", [])
        ]
