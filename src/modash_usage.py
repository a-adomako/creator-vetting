"""
modash_usage.py — Track Modash API consumption + read the live balance.

Modash bills the two APIs from SEPARATE pools (confirmed via /v1/user/info
and the #augmentum-modash channel, 2026-06-12):

  • Discovery API — "credits". Full report = 1.0, classic search = 0.15/page,
    AI search = 0.025/result, brand collabs = 0.2.
  • RAW API — a "rawRequests" allotment, decremented per request
    (user-info, user-reels, media-comments each count 1).

The account is SHARED across Augmentum (Aditya's discovery agent, Mark's
tools, CreatorVetter) — so the local log tracks what THIS tool consumed,
while get_balance() reports the account-wide truth.

Every Modash call in ModashFetcher logs one line to
output/modash_usage.jsonl: {ts, api, endpoint, username, credits}.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

USAGE_LOG = Path(__file__).parent.parent / "output" / "modash_usage.jsonl"

# Discovery-API credit costs (from Martynas, #augmentum-modash 2026-05-08)
CREDIT_COSTS = {
    "report": 1.0,
    "search_page": 0.15,
    "ai_search_result": 0.025,
    "brand_collaborations": 0.2,
    "email_lookup": 0.02,
}

_lock = threading.Lock()


def log_request(
    api: str,                     # "raw" | "discovery"
    endpoint: str,                # "user-info" | "user-reels" | "media-comments" | "report" | ...
    username: str = "",
    credits: Optional[float] = None,
    note: str = "",
) -> None:
    """Append one consumption line. raw → counts 1 request; discovery → credits."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "api": api,
        "endpoint": endpoint,
        "username": username,
        "credits": credits,
    }
    if note:
        entry["note"] = note
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.debug("Usage log write failed: %s", e)


def usage_summary(days: int = 7) -> dict:
    """This tool's consumption over the last N days, from the local log."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    raw_requests, credits = 0, 0.0
    by_endpoint: dict[str, int] = {}
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("ts", "") < cutoff:
                continue
            ep = e.get("endpoint", "?")
            by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
            if e.get("api") == "raw":
                raw_requests += 1
            elif e.get("credits"):
                credits += float(e["credits"])
    return {
        "days": days,
        "raw_requests": raw_requests,
        "credits": round(credits, 2),
        "by_endpoint": by_endpoint,
    }


def get_balance(api_key: Optional[str] = None, timeout: int = 15) -> Optional[dict]:
    """
    Live account-wide balance from Modash.

    Returns {"credits": float, "raw_requests": float} or None on failure.
    raw_requests can go NEGATIVE (overdrawn) — Modash lets the last batch
    through, then 403s everything after.
    """
    key = api_key or os.getenv("MODASH_API_KEY")
    if not key:
        return None
    try:
        resp = requests.get(
            "https://api.modash.io/v1/user/info",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        billing = resp.json().get("billing") or {}
        return {
            "credits": billing.get("credits"),
            "raw_requests": billing.get("rawRequests"),
        }
    except Exception as e:
        logger.debug("Modash balance check failed: %s", e)
        return None
