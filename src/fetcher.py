"""
fetcher.py — Modash Raw API Instagram profile scraper + username/URL resolution.

Responsibilities:
- Parse Instagram usernames from profile URLs or raw username strings
- Fetch profile metadata and recent reel data via Modash Raw API
- Normalise Modash response fields to internal contract
- Return results keyed by lowercase username
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Instagram URL paths that are not profile pages
_NON_PROFILE_PATHS = {"p", "reel", "reels", "tv", "explore", "accounts", "stories"}


def extract_username(value: str) -> Optional[str]:
	"""
	Extract an Instagram username from a profile URL or a plain username string.

	Handles:
	- https://www.instagram.com/username/
	- https://instagram.com/username
	- @username
	- username

	Returns lowercase username, or None if it cannot be determined.
	"""
	if not value or not isinstance(value, str):
		return None

	value = value.strip()

	# Try URL extraction first
	url_match = re.search(r'instagram\.com/([^/?#\s]+)', value, re.IGNORECASE)
	if url_match:
		candidate = url_match.group(1).rstrip("/").lower()
		if candidate and candidate not in _NON_PROFILE_PATHS:
			return candidate
		return None

	# Treat as plain username — strip @ and validate
	candidate = value.lstrip("@").strip().lower()
	# Basic Instagram username rules: 1–30 chars, alphanumeric + dots + underscores
	if re.fullmatch(r"[a-z0-9._]{1,30}", candidate):
		return candidate

	return None


class ModashFetcher:
	"""Modash Raw API Instagram profile scraper."""

	BASE_URL = "https://api.modash.io/v1"

	def __init__(
		self,
		api_key: str,
		base_url: str = None,
		requests_per_second: float = 2.0,
	):
		"""
		Initialize Modash fetcher.

		Args:
			api_key: Modash API key (Bearer token)
			base_url: Modash API base URL (default: production)
			requests_per_second: Rate limit for API requests (default: 2 req/sec)
		"""
		self._api_key = api_key
		self._base_url = (base_url or self.BASE_URL).rstrip("/")
		self._delay = 1.0 / requests_per_second if requests_per_second > 0 else 0

		self._session = requests.Session()
		self._session.headers.update({
			"Authorization": f"Bearer {api_key}",
			"User-Agent": "CreatorVetter/1.0",
		})

	def fetch_profiles(
		self,
		usernames: list[str],
		batch_size: int = 100,
	) -> dict[str, dict]:
		"""
		Fetch Instagram profiles for a list of usernames.

		Modash has no batch endpoint — processes one username at a time.
		Skips failed requests with a warning rather than raising.

		Args:
			usernames: List of Instagram usernames
			batch_size: Ignored (kept for API compatibility)

		Returns:
			Dict keyed by lowercase username
		"""
		unique_usernames = list({u.lower() for u in usernames if u})
		results: dict[str, dict] = {}

		for idx, username in enumerate(unique_usernames):
			try:
				logger.info(
					"Modash request %d/%d — fetching %s",
					idx + 1,
					len(unique_usernames),
					username,
				)

				# Fetch profile info
				profile_resp = self._session.get(
					f"{self._base_url}/raw/ig/user-info",
					params={"url": username},
					timeout=10,
				)
				profile_resp.raise_for_status()
				profile_data = profile_resp.json()

				# Fetch reels (first page is enough for up to 12 reels)
				reels_resp = self._session.get(
					f"{self._base_url}/raw/ig/user-reels",
					params={"url": username},
					timeout=10,
				)
				reels_resp.raise_for_status()
				reels_data = reels_resp.json()

				# Normalize and store
				reels = reels_data.get("items", [])
				results[username] = self._normalize_profile(profile_data, reels)

			except requests.HTTPError as e:
				logger.warning("Modash HTTP error for @%s — %s", username, e)
			except requests.RequestException as e:
				logger.warning("Modash request error for @%s — %s", username, e)
			except ValueError as e:
				logger.warning("Modash JSON parse error for @%s — %s", username, e)
			except Exception as e:
				logger.exception("Unexpected error fetching @%s", username)

			# Rate limit
			if self._delay > 0:
				time.sleep(self._delay)

		logger.info("Fetched %d/%d profiles successfully", len(results), len(unique_usernames))
		return results

	def extract_reel_urls(self, profile: dict, max_reels: int = 3) -> list[str]:
		"""
		Pull video URLs from a profile's latestPosts array.

		Modash returns signed video URLs in the videoUrl field for video posts.
		These are downloadable without authentication.
		"""
		urls = []
		for post in profile.get("latestPosts", []):
			if len(urls) >= max_reels:
				break
			if post.get("videoUrl"):
				urls.append(post["videoUrl"])
		return urls

	def _normalize_profile(self, profile: dict, reels: list) -> dict:
		"""
		Normalise Modash profile response to internal contract.

		Maps Modash snake_case fields to camelCase expected by scorer.py.
		"""
		normalized_reels = [self._normalize_post(r) for r in reels]

		return {
			"username": profile.get("username", ""),
			"fullName": profile.get("full_name", ""),
			"verified": bool(profile.get("is_verified", False)),
			"private": bool(profile.get("is_private", False)),
			"followersCount": profile.get("follower_count", 0),
			"followsCount": profile.get("following_count", 0),
			"postsCount": profile.get("media_count", 0),
			"latestPosts": normalized_reels,
		}

	def _normalize_post(self, post: dict) -> dict:
		"""
		Normalise a single post from Modash to internal contract.

		Handles timestamp conversion from Unix epoch to ISO format.
		"""
		# Convert Unix epoch to ISO string (scorer.py expects datetime.fromisoformat format)
		timestamp = None
		taken_at = post.get("taken_at")
		if taken_at:
			try:
				timestamp = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()
			except (ValueError, TypeError):
				logger.warning("Invalid timestamp: %s", taken_at)

		return {
			"videoUrl": post.get("video_url"),
			"likesCount": post.get("like_count", 0),
			"commentsCount": post.get("comment_count", 0),
			"timestamp": timestamp,
		}
