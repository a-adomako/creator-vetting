import os
import requests
from typing import Optional


BASE_URL = "https://api.modash.io/v1"


class ModashAPI:
    """Wrapper for the Modash creator discovery API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("MODASH_API_KEY")
        if not self.api_key:
            raise ValueError(
                "MODASH_API_KEY not set. Provide it as an env var or pass it directly."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        self.debug = os.getenv("DEBUG_MODASH", "").lower() == "true"

    def search(
        self,
        filters: Optional[dict] = None,
        limit: int = 20,
        page: int = 1
    ) -> dict:
        """Search for creators matching flexible filters.

        Args:
            filters: dict with filter params. Accepted keys:
                     followers {min, max}, engagementRate {min, max},
                     location {country: [...]}, language [...],
                     categories [...], bio {keywords [...]}, etc.
            limit: max results per page (1-100, default 20)
            page: page number for pagination (default 1)

        Returns:
            Raw API response dict with: data.profiles, total, credits_left, etc.
        """
        body = {
            "page": page,
            "limit": min(limit, 100),
            "filter": filters or {}
        }
        r = self.session.post(
            f"{BASE_URL}/instagram/search",
            json=body,
            timeout=30
        )
        r.raise_for_status()
        response = r.json()
        if self.debug:
            import json
            print("DEBUG_MODASH response:", json.dumps(response, indent=2))
        return response

    def parse_accounts(self, response: dict) -> list:
        """Extract clean account list from raw API response.

        Normalizes Modash field names to canonical schema:
        username, full_name, followers, engagement_percent, user_id
        """
        # Modash typically returns: data.profiles as the account list
        accounts = response.get("data", {}).get("profiles", [])

        return [
            {
                "username": a.get("profile", {}).get("username", ""),
                "full_name": a.get("profile", {}).get("fullName", ""),
                "followers": int(a.get("profile", {}).get("followers", 0) or 0),
                "engagement_percent": float(a.get("profile", {}).get("engagementRate", 0.0) or 0.0),
                "user_id": a.get("userId", ""),
            }
            for a in accounts
        ]
