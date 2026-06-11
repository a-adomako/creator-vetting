"""
spine.py — CreatorVetter → central spine database integration.

"Consolidate forward" (decided 2026-06-11): every freshly v2-vetted creator
with no universal disqualifiers is pushed to the central agency database —
the legacy local creators.db snapshot is never bulk-pushed.

Two write paths, matching the spine's own contracts:

1. PROFILES — REST `POST /upsert` on the deployed FastAPI service
   (UpsertRequest schema: handle, platform, platform_user_id, bio,
   followers_count, display_name, platform_metadata, status). Returns the
   profile UUID we need for vetting rows.

2. VETTING DECISIONS — direct rows in the spine's existing
   `creator_vetting` table (migration 0014), which requires NOT NULL FKs to
   discovery_requests + discovery_runs. We use the documented "phantom
   request" pattern: each push batch opens one synthetic request + run
   marked as CreatorVetter-originated, then hangs vetting rows off it.
   Decision enum mapping:
     LLM approve  → auto_approved      LLM reject → auto_rejected
     needs_review → pending_review
     calibration swipe / human correction → human_approved / human_rejected

Credentials auto-load from Evergreen/augmentum-spine/.env (API_BASE_URL,
API_KEY, DATABASE_URL) unless already present in the environment.
All writes go through push_records(); dry_run=True prints the plan only.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SPINE_ENV = Path(__file__).parent.parent.parent / "augmentum-spine" / ".env"

DECISION_MAP = {
    "approve": "auto_approved",
    "reject": "auto_rejected",
    "needs_review": "pending_review",
}


def slugify_folder(name: str) -> str:
    """knowledge/clients/<folder> → spine clients.slug. One rule, shared
    with sync_brand_context_to_spine.py's behaviour: lowercase, &→and,
    +→-plus, drop apostrophes, dash-collapse non-alphanumerics."""
    s = name.lower().replace("&", "and").replace("+", "-plus")
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _load_spine_env() -> dict:
    """API_BASE_URL / API_KEY / DATABASE_URL from env, else spine .env."""
    vals = {k: os.getenv(k) for k in ("API_BASE_URL", "API_KEY", "DATABASE_URL")}
    if not all(vals.values()) and _SPINE_ENV.exists():
        for line in _SPINE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k in vals and not vals[k]:
                    vals[k] = v
    return vals


def _normalize_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


@dataclass
class PushRecord:
    """One judged creator headed for the spine."""
    username: str
    push_to_spine: bool
    recommendation: str            # approve | reject | needs_review
    reason: str = ""
    niche: Optional[str] = None
    fit_score: Optional[int] = None
    bio: str = ""
    followers: Optional[int] = None
    display_name: str = ""
    platform_user_id: Optional[str] = None
    engagement_rate: Optional[float] = None
    verdict: dict = field(default_factory=dict)
    decided_by: str = "creator_vetter_v2"
    decision_override: Optional[str] = None   # set for human_* rows


@dataclass
class PushResult:
    upserted: int = 0
    vetting_rows: int = 0
    skipped_disqualified: int = 0
    errors: list = field(default_factory=list)
    request_id: Optional[str] = None
    run_id: Optional[str] = None
    profile_ids: dict = field(default_factory=dict)  # username → uuid


class SpineClient:
    """Thin client over the spine REST API + direct Postgres writes."""

    def __init__(self):
        env = _load_spine_env()
        self.api_base = (env.get("API_BASE_URL") or "").rstrip("/")
        self.api_key = env.get("API_KEY")
        self.database_url = env.get("DATABASE_URL")
        if not (self.api_base and self.api_key):
            raise ValueError(
                "Spine API_BASE_URL / API_KEY not found (checked env and "
                f"{_SPINE_ENV})"
            )

    # ── REST ─────────────────────────────────────────────────────────
    def upsert_profile(self, rec: PushRecord) -> dict:
        payload = {
            "handle": rec.username,
            "platform": "instagram",
            "status": "active",
        }
        if rec.platform_user_id:
            payload["platform_user_id"] = str(rec.platform_user_id)
        if rec.bio:
            payload["bio"] = rec.bio[:2000]
        if rec.followers is not None:
            payload["followers_count"] = int(rec.followers)
        if rec.display_name:
            payload["display_name"] = rec.display_name[:255]
        meta = {"source": "creator_vetter_v2"}
        if rec.engagement_rate is not None:
            meta["avg_engagement_rate"] = rec.engagement_rate
        payload["platform_metadata"] = meta

        # The spine runs on Render and cold-starts in ~10–60s after idling.
        # Long timeout + one retry so the first write of a session survives.
        last_err = None
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{self.api_base}/upsert",
                    headers={
                        "X-API-Key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=75,
                )
                resp.raise_for_status()
                return resp.json()   # {id, handle, platform, action}
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                logger.info("Spine cold-start retry for @%s…", rec.username)
        raise last_err

    # ── DB (asyncpg) ─────────────────────────────────────────────────
    async def _db_push_vetting(
        self,
        records: list,
        profile_ids: dict,
        client_slug: Optional[str],
        campaign: str,
        result: PushResult,
    ):
        import asyncpg
        if not self.database_url:
            raise ValueError("DATABASE_URL not available for vetting rows")
        conn = await asyncpg.connect(_normalize_dsn(self.database_url), ssl="require")
        try:
            client_id = None
            if client_slug:
                client_id = await conn.fetchval(
                    "SELECT id FROM clients WHERE slug = $1", client_slug
                )
            if client_id is None:
                logger.warning(
                    "No spine client found for slug %r — vetting rows skipped "
                    "(profiles still upserted)", client_slug,
                )
                return

            # Phantom request + run for this push batch
            request_id = await conn.fetchval(
                """
                INSERT INTO discovery_requests
                    (client_id, client_name_input, creators_needed, region,
                     deadline, status, notes)
                VALUES ($1, $2, $3, 'GLOBAL', $4, 'completed', $5)
                RETURNING id
                """,
                # creators_needed has a 10–5000 portal check; clamp our
                # phantom batches into range (the real count is in the notes)
                client_id, client_slug, min(max(len(records), 10), 5000),
                date.today(),
                f"CreatorVetter v2 push — campaign '{campaign}' "
                f"(synthetic request; not a portal submission)",
            )
            run_id = await conn.fetchval(
                """
                INSERT INTO discovery_runs
                    (request_id, status, vetted_count, completed_at)
                VALUES ($1, 'success', $2, now())
                RETURNING id
                """,
                request_id, len(records),
            )
            result.request_id = str(request_id)
            result.run_id = str(run_id)

            for rec in records:
                profile_id = profile_ids.get(rec.username)
                if not profile_id:
                    continue
                decision = rec.decision_override or DECISION_MAP.get(
                    rec.recommendation, "pending_review"
                )
                raw = {
                    "campaign": campaign,
                    "source": "creator_vetter_v2",
                    "decided_by": rec.decided_by,
                    "verdict": rec.verdict,
                }
                await conn.execute(
                    """
                    INSERT INTO creator_vetting
                        (profile_id, client_id, run_id, request_id,
                         niche_classification, brand_fit_score,
                         decision, decision_reason, raw_scoring_output)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                    """,
                    profile_id, client_id, run_id, request_id,
                    rec.niche, rec.fit_score,
                    decision, rec.reason[:2000] if rec.reason else None,
                    json.dumps(raw, default=str),
                )
                result.vetting_rows += 1
        finally:
            await conn.close()

    # ── Public entry point ───────────────────────────────────────────
    def push_records(
        self,
        records: list,
        campaign: str,
        client_slug: Optional[str],
        dry_run: bool = True,
    ) -> PushResult:
        """
        Push a batch of judged creators: profile upserts for every record
        with push_to_spine=True, then one phantom request/run + a
        creator_vetting row per upserted creator.
        """
        result = PushResult()
        pushable = [r for r in records if r.push_to_spine]
        result.skipped_disqualified = len(records) - len(pushable)

        if dry_run:
            logger.info(
                "[dry-run] Would upsert %d profiles and write %d vetting rows "
                "for client slug %r (campaign %r). %d held back (disqualified).",
                len(pushable), len(pushable), client_slug, campaign,
                result.skipped_disqualified,
            )
            for r in pushable:
                decision = r.decision_override or DECISION_MAP.get(
                    r.recommendation, "pending_review"
                )
                logger.info(
                    "[dry-run]   @%s → upsert (followers=%s, pk=%s) + "
                    "vetting %s (fit=%s)",
                    r.username, r.followers, r.platform_user_id,
                    decision, r.fit_score,
                )
            return result

        for rec in pushable:
            try:
                out = self.upsert_profile(rec)
                result.profile_ids[rec.username] = out["id"]
                result.upserted += 1
                logger.info("@%s → spine profile %s (%s)",
                            rec.username, out["id"], out["action"])
            except Exception as e:
                result.errors.append(f"upsert @{rec.username}: {e}")
                logger.warning("Spine upsert failed for @%s — %s", rec.username, e)

        if result.profile_ids:
            try:
                asyncio.run(self._db_push_vetting(
                    pushable, result.profile_ids, client_slug, campaign, result
                ))
            except Exception as e:
                result.errors.append(f"vetting rows: {e}")
                logger.warning("Spine vetting-row write failed — %s", e)

        return result


def record_human_decision(
    username: str,
    campaign: str,
    client_slug: str,
    approved: bool,
    reason: str,
    decided_by: str,
    verdict: Optional[dict] = None,
    profile_seed: Optional[dict] = None,
) -> Optional[PushResult]:
    """
    One human label (calibration swipe or correction) → spine.

    Upserts the profile if needed and writes a human_approved /
    human_rejected vetting row under a phantom calibration run. Returns the
    PushResult, or None if the spine is unreachable (caller treats spine as
    best-effort — local files are the primary record).
    """
    seed = profile_seed or {}
    rec = PushRecord(
        username=username,
        push_to_spine=True,
        recommendation="approve" if approved else "reject",
        decision_override="human_approved" if approved else "human_rejected",
        reason=reason,
        niche=(verdict or {}).get("primary_niche"),
        fit_score=(verdict or {}).get("campaign_fit_score"),
        bio=seed.get("biography", ""),
        followers=seed.get("followers"),
        display_name=seed.get("ig_full_name", ""),
        platform_user_id=seed.get("platform_user_id"),
        engagement_rate=seed.get("avg_engagement_rate"),
        verdict=verdict or {},
        decided_by=decided_by,
    )
    try:
        client = SpineClient()
        return client.push_records(
            [rec], campaign=f"{campaign} (calibration)",
            client_slug=client_slug, dry_run=False,
        )
    except Exception as e:
        logger.warning("Spine decision record failed for @%s — %s", username, e)
        return None
