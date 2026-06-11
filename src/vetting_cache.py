"""
vetting_cache.py — Cross-run cache of campaign vetting verdicts.

If a creator was already judged for a campaign within the freshness window
(default 6 months), the v2 flow reuses that verdict instead of re-fetching,
re-downloading, re-transcribing, and re-judging. Cache hits cost zero Modash
quota and zero LLM spend.

What gets cached: only LLM-judged outcomes (approve / reject / needs_review /
disqualified). Hard-filter results are NEVER cached — metrics drift, and
re-checking them is free anyway, so a creator who failed the follower floor
six months ago gets a fresh chance.

Storage: SQLite at output/vetting_cache.db, keyed (username, campaign).
On first open the cache seeds itself from any existing run folders under
output/campaigns/*/profiles/*.json so history is not lost.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_vetting (
    username     TEXT NOT NULL,
    campaign     TEXT NOT NULL,
    vetted_at    TEXT NOT NULL,   -- ISO date/time of the original judgment
    bucket       TEXT NOT NULL,   -- shortlist | rejected | review
    row_json     TEXT NOT NULL,   -- the CSV row as written in the original run
    verdict_json TEXT,            -- full structured verdict
    PRIMARY KEY (username, campaign)
)
"""


def _parse_run_timestamp(ts: str) -> Optional[datetime]:
    """Accept both run-folder stamps (20260611_204144) and ISO strings."""
    for fmt in ("%Y%m%d_%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[: len(datetime.now().strftime(fmt))], fmt)
        except (ValueError, TypeError):
            continue
    return None


class VettingCache:
    """SQLite-backed (username, campaign) → verdict cache with a TTL."""

    def __init__(
        self,
        db_path: Path = Path("output/vetting_cache.db"),
        max_age_days: int = 183,
        seed_dir: Optional[Path] = Path("output/campaigns"),
    ):
        self.max_age = timedelta(days=max_age_days)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        if seed_dir and seed_dir.exists():
            self._seed_from_runs(seed_dir)

    def _seed_from_runs(self, campaigns_dir: Path) -> None:
        """Backfill from existing run folders (insert-if-absent, cheap)."""
        seeded = 0
        for profile_path in campaigns_dir.glob("*/profiles/*.json"):
            try:
                record = json.loads(profile_path.read_text(encoding="utf-8"))
                username = record.get("username")
                campaign = record.get("campaign")
                verdict = record.get("verdict") or {}
                if not (username and campaign and verdict):
                    continue
                vetted = _parse_run_timestamp(str(record.get("vetted_at", "")))
                if vetted is None:
                    continue
                if verdict.get("universal_disqualifiers"):
                    bucket = "rejected"
                else:
                    bucket = {
                        "approve": "shortlist",
                        "reject": "rejected",
                    }.get(verdict.get("recommendation"), "review")
                row = {
                    "ig_username": username,
                    "profile_url": f"https://www.instagram.com/{username}/",
                    "followers": (record.get("metrics") or {}).get("followers"),
                    "avg_engagement_rate": (record.get("metrics") or {}).get(
                        "avg_engagement_rate"
                    ),
                    "ig_full_name": (record.get("metrics") or {}).get("ig_full_name", ""),
                    "posts_last_30_days": (record.get("metrics") or {}).get(
                        "posts_last_30_days"
                    ),
                    "primary_niche": verdict.get("primary_niche", ""),
                    "campaign_fit_score": verdict.get("campaign_fit_score"),
                    "stage": "judgment",
                    "category": "campaign_misfit" if bucket == "rejected" else "needs_review",
                    "reason": verdict.get("reason", ""),
                    "evidence": verdict.get("evidence", ""),
                    "push_to_spine": not verdict.get("universal_disqualifiers"),
                }
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO campaign_vetting VALUES (?,?,?,?,?,?)",
                    (
                        username, campaign, vetted.isoformat(), bucket,
                        json.dumps(row, default=str), json.dumps(verdict, default=str),
                    ),
                )
                seeded += cur.rowcount
            except Exception as e:
                logger.debug("Cache seed skipped %s: %s", profile_path.name, e)
        if seeded:
            self._conn.commit()
            logger.info("Vetting cache: seeded %d verdicts from past runs", seeded)

    def get(self, username: str, campaign: str) -> Optional[dict]:
        """
        Return {"bucket", "row", "verdict", "vetted_at"} if a fresh verdict
        exists for this creator + campaign, else None.
        """
        cur = self._conn.execute(
            "SELECT vetted_at, bucket, row_json, verdict_json "
            "FROM campaign_vetting WHERE username=? AND campaign=?",
            (username.lower(), campaign),
        )
        hit = cur.fetchone()
        if not hit:
            return None
        vetted_at, bucket, row_json, verdict_json = hit
        vetted = _parse_run_timestamp(vetted_at)
        if vetted is None or datetime.now() - vetted > self.max_age:
            return None  # stale — re-vet
        return {
            "bucket": bucket,
            "row": json.loads(row_json),
            "verdict": json.loads(verdict_json) if verdict_json else None,
            "vetted_at": vetted_at,
        }

    def put(
        self,
        username: str,
        campaign: str,
        bucket: str,
        row: dict,
        verdict: Optional[dict],
    ) -> None:
        """Record a fresh judgment (replaces any older entry)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO campaign_vetting VALUES (?,?,?,?,?,?)",
            (
                username.lower(), campaign, datetime.now().isoformat(timespec="seconds"),
                bucket, json.dumps(row, default=str),
                json.dumps(verdict, default=str) if verdict else None,
            ),
        )
        self._conn.commit()

    def delete(self, username: str, campaign: str) -> None:
        """Drop a cached verdict — used when a human corrects a decision so
        the next run re-judges with the correction in the prompt."""
        self._conn.execute(
            "DELETE FROM campaign_vetting WHERE username=? AND campaign=?",
            (username.lower(), campaign),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()
