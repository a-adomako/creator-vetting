"""
agent_tools.py — Database query functions exposed as tools to the selection agent.

Each function is called by the Claude API tool-use system during a chat session.
The agent decides when to call these based on the conversation.

Supports two modes:
  - CSV mode (legacy):   CreatorDatabase(csv_path)
  - Store mode (SQLite): CreatorDatabase.from_store(CreatorStore)
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TIER_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1}


class CreatorDatabase:
    """
    Provides agent tool functions over the creator dataset.

    Can be backed by a CSV (legacy) or by a SQLite CreatorStore (preferred).
    Store mode works without loading any CSV — it queries the persistent DB directly.
    """

    def __init__(self, csv_path: str):
        """CSV mode: load a specific enriched CSV file."""
        self.csv_path = Path(csv_path)
        self.profiles_dir = self.csv_path.parent / "profiles"
        self.llm = None
        self.knowledge_dir = Path(__file__).parent.parent / "knowledge"
        self._store = None  # No store in CSV mode

        self.df = pd.read_csv(csv_path)
        # Normalise column types
        for col in ["followers", "following", "total_posts", "posts_last_30_days"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
        for col in ["avg_engagement_rate", "brand_fit_score", "overall_quality_score", "niche_confidence"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

        self.shortlist: list[dict] = []
        logger.info("Database loaded (CSV): %d creators", len(self.df))

    @classmethod
    def from_store(cls, store) -> "CreatorDatabase":
        """
        Store mode: back this database with a SQLite CreatorStore.

        No CSV is loaded. All searches and profile lookups query the store.
        The shortlist is still in-memory (session scope).
        """
        instance = cls.__new__(cls)
        instance._store = store
        instance.csv_path = None
        instance.profiles_dir = store.db_path.parent / "profiles"
        instance.llm = None
        instance.knowledge_dir = Path(__file__).parent.parent / "knowledge"
        instance.df = None  # Not used in store mode
        instance.shortlist = []
        logger.info("Database loaded (SQLite): %d creators total", store.count())
        return instance

    @property
    def total_count(self) -> int:
        """Total creators in this database (CSV row count or SQLite count)."""
        if self._store is not None:
            return self._store.count()
        return len(self.df) if self.df is not None else 0

    def summary_stats(self) -> dict:
        """Return high-level stats about the database for the agent system prompt."""
        if self._store is not None:
            return self._store.summary_stats()

        # CSV mode
        total = len(self.df)
        stats = {"total_creators": total}
        if "tier" in self.df.columns:
            stats["tier_counts"] = self.df["tier"].value_counts().to_dict()
        if "primary_niche" in self.df.columns:
            stats["top_niches"] = self.df["primary_niche"].value_counts().head(8).to_dict()
        if "followers" in self.df.columns:
            _min = self.df["followers"].min()
            _max = self.df["followers"].max()
            _med = self.df["followers"].median()
            if not pd.isna(_min):
                stats["follower_range"] = {
                    "min": int(_min),
                    "max": int(_max),
                    "median": int(_med),
                }
        return stats

    # ── Tool functions ────────────────────────────────────────────────────────

    def search_creators(
        self,
        niches: Optional[list[str]] = None,
        min_followers: Optional[int] = None,
        max_followers: Optional[int] = None,
        min_engagement_rate: Optional[float] = None,
        min_tier: Optional[str] = None,
        min_brand_fit_score: Optional[float] = None,
        keywords: Optional[list[str]] = None,
        exclude_flags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> dict:
        """
        Filter and rank creators from the database.
        Returns top matches with key metrics.
        """
        # ── Store mode: delegate to SQLite ────────────────────────────────────
        if self._store is not None:
            rows = self._store.search(
                niches=niches,
                min_followers=min_followers,
                max_followers=max_followers,
                min_engagement_rate=min_engagement_rate,
                min_tier=min_tier,
                min_brand_fit_score=min_brand_fit_score,
                keywords=keywords,
                exclude_flags=exclude_flags,
                limit=limit,
            )
            return {
                "total_matching": len(rows),
                "returned": len(rows),
                "creators": rows,
            }

        # ── CSV mode: pandas filtering ────────────────────────────────────────
        df = self.df.copy()

        # Niche filter
        if niches:
            niche_lower = [n.lower() for n in niches]
            mask = df["primary_niche"].str.lower().isin(niche_lower)
            if "secondary_niche" in df.columns:
                mask |= df["secondary_niche"].str.lower().isin(niche_lower)
            df = df[mask]

        # Follower range
        if min_followers is not None and "followers" in df.columns:
            df = df[df["followers"] >= min_followers]
        if max_followers is not None and "followers" in df.columns:
            df = df[df["followers"] <= max_followers]

        # Engagement rate
        if min_engagement_rate is not None and "avg_engagement_rate" in df.columns:
            df = df[df["avg_engagement_rate"] >= min_engagement_rate]

        # Tier
        if min_tier and "tier" in df.columns:
            min_val = TIER_ORDER.get(min_tier.upper(), 1)
            df = df[df["tier"].map(lambda t: TIER_ORDER.get(str(t).upper(), 0)) >= min_val]

        # Brand fit score
        if min_brand_fit_score is not None and "brand_fit_score" in df.columns:
            df = df[df["brand_fit_score"] >= min_brand_fit_score]

        # Keyword filter on transcript sample + content summary
        if keywords:
            text_cols = []
            for col in ["transcript_sample", "content_summary", "detected_scenes"]:
                if col in df.columns:
                    text_cols.append(df[col].fillna("").str.lower())
            if text_cols:
                combined = text_cols[0]
                for t in text_cols[1:]:
                    combined = combined + " " + t
                for kw in keywords:
                    df = df[combined.str.contains(kw.lower(), na=False)]

        # Exclude flags
        if exclude_flags and "flags" in df.columns:
            for flag in exclude_flags:
                df = df[~df["flags"].fillna("").str.contains(flag, na=False)]

        # Rank by brand_fit_score then overall_quality_score
        sort_cols = []
        if "brand_fit_score" in df.columns:
            sort_cols.append("brand_fit_score")
        if "overall_quality_score" in df.columns:
            sort_cols.append("overall_quality_score")
        if sort_cols:
            df = df.sort_values(sort_cols, ascending=False)

        df = df.head(limit)

        # Return compact summary per creator
        results = []
        display_cols = [
            "ig_username", "ig_full_name", "followers", "avg_engagement_rate",
            "tier", "primary_niche", "secondary_niche", "brand_fit_score",
            "overall_quality_score", "niche_confidence", "content_summary",
            "transcript_sample", "detected_scenes", "production_quality",
            "posts_last_30_days", "days_since_last_post", "flags",
        ]
        for _, row in df.iterrows():
            rec = {}
            for col in display_cols:
                if col in row.index:
                    val = row[col]
                    rec[col] = None if pd.isna(val) else val
            results.append(rec)

        return {
            "total_matching": len(self.df) if not any([niches, min_followers, max_followers,
                                                        min_engagement_rate, min_tier,
                                                        min_brand_fit_score, keywords,
                                                        exclude_flags]) else "filtered",
            "returned": len(results),
            "creators": results,
        }

    def get_creator_profile(self, username: str) -> dict:
        """
        Load the full JSON profile for a creator (complete transcripts, CLIP scores, etc).

        Priority:
          1. JSON profile file (output/profiles/<username>.json) — richest data
          2. SQLite store row (store mode) or CSV row (CSV mode) — summary data
        """
        username = username.lstrip("@").lower()
        profile_path = self.profiles_dir / f"{username}.json"

        if profile_path.exists():
            with open(profile_path, encoding="utf-8") as f:
                return json.load(f)

        # Store mode: query SQLite
        if self._store is not None:
            row = self._store.get_by_username(username)
            if row:
                return {"username": username, "note": "Full JSON profile not available — database row only", **row}
            return {"error": f"Creator @{username} not found in database"}

        # CSV mode: return CSV row as dict
        if self.df is not None and "ig_username" in self.df.columns:
            matches = self.df[self.df["ig_username"].fillna("").str.lower() == username]
        else:
            matches = pd.DataFrame()
        if not matches.empty:
            row = matches.iloc[0].to_dict()
            return {"username": username, "note": "Full profile not available — CSV data only", **row}

        return {"error": f"Creator @{username} not found in database"}

    def add_to_shortlist(self, username: str, reason: str) -> dict:
        """Add a creator to the session shortlist with a reason."""
        username = username.lstrip("@").lower()

        # Check already on shortlist
        if any(c["username"] == username for c in self.shortlist):
            return {"status": "already_on_shortlist", "username": username}

        # Store mode: look up in SQLite
        if self._store is not None:
            row = self._store.get_by_username(username)
            if row is None:
                return {"status": "not_found", "username": username}
            self.shortlist.append({"username": username, "reason": reason, "data": row})
            return {"status": "added", "username": username, "shortlist_size": len(self.shortlist)}

        # CSV mode: find in DataFrame
        col = "ig_username" if self.df is not None and "ig_username" in self.df.columns else None
        if col:
            matches = self.df[self.df[col].str.lower() == username]
        else:
            matches = pd.DataFrame()

        if matches.empty:
            return {"status": "not_found", "username": username}

        row = matches.iloc[0].to_dict()
        self.shortlist.append({"username": username, "reason": reason, "data": row})
        return {
            "status": "added",
            "username": username,
            "shortlist_size": len(self.shortlist),
        }

    def remove_from_shortlist(self, username: str) -> dict:
        """Remove a creator from the session shortlist."""
        username = username.lstrip("@").lower()
        before = len(self.shortlist)
        self.shortlist = [c for c in self.shortlist if c["username"] != username]
        removed = before - len(self.shortlist)
        return {
            "status": "removed" if removed else "not_found",
            "username": username,
            "shortlist_size": len(self.shortlist),
        }

    def get_shortlist(self) -> dict:
        """Return the current shortlist."""
        return {
            "shortlist_size": len(self.shortlist),
            "creators": [
                {
                    "username": c["username"],
                    "reason": c["reason"],
                    "tier": c["data"].get("tier"),
                    "followers": c["data"].get("followers"),
                    "avg_engagement_rate": c["data"].get("avg_engagement_rate"),
                    "primary_niche": c["data"].get("primary_niche"),
                    "brand_fit_score": c["data"].get("brand_fit_score"),
                }
                for c in self.shortlist
            ],
        }

    def analyze_creator_for_campaign(
        self,
        username: str,
        campaign_brief: str,
        client_dir: "Path | None" = None,
    ) -> dict:
        """
        Use Claude to analyze a specific creator's full profile against a campaign brief.

        Reads the creator's complete transcript, visual scenes, and engagement data,
        then returns qualitative scores, strengths, concerns, and a recommendation.

        If client_dir is provided, loads that client's profile.yaml (for brand_context
        and target_niches) and their calibration files (my_style, corrections, examples).
        Falls back to global knowledge/ calibration if no client is active.
        """
        if self.llm is None:
            return {"error": "LLM client not configured — ANTHROPIC_API_KEY may not be set"}

        profile = self.get_creator_profile(username)
        if "error" in profile:
            return profile

        # Extract content signals
        transcript = profile.get("full_transcript", "") or ""
        analysis_block = profile.get("analysis", {})
        if isinstance(analysis_block, dict):
            detected_scenes = analysis_block.get("detected_scenes", "")
            production_quality = analysis_block.get("production_quality", "unknown")
        else:
            detected_scenes = ""
            production_quality = "unknown"

        engagement = profile.get("engagement", {})
        followers = engagement.get("followers") or profile.get("followers")
        eng_rate = engagement.get("avg_engagement_rate") or profile.get("avg_engagement_rate")

        # Load client profile if provided
        client_brand_context = ""
        client_niches = ""
        if client_dir and (client_dir / "profile.yaml").exists():
            try:
                import yaml
                cp = yaml.safe_load((client_dir / "profile.yaml").read_text(encoding="utf-8"))
                client_brand_context = cp.get("brand_context", "")
                niches = cp.get("target_niches", [])
                client_niches = ", ".join(niches) if niches else ""
            except Exception:
                pass

        # Load calibration context (expertise.md + client-specific files)
        from .llm_analyzer import _load_calibration, _parse_json
        calibration = _load_calibration(self.knowledge_dir, client_dir)

        client_context_block = ""
        if client_brand_context:
            client_context_block = f"\nClient brand context: {client_brand_context}"
        if client_niches:
            client_context_block += f"\nTarget niches for this client: {client_niches}"

        system = f"""You are an experienced influencer selection specialist at an influencer marketing agency.
Your job is to evaluate whether a specific creator is a good fit for a specific campaign brief.

Be honest and direct. Use the full 0–100 range for scores — don't cluster around 50.
A score of 90+ means exceptional. 70–89 is solid. 50–69 is average. Below 50 means real concerns.
{client_context_block}

{calibration}
""".strip()

        prompt = f"""Evaluate this creator for the following campaign.

CAMPAIGN BRIEF: {campaign_brief}

CREATOR: @{username.lstrip('@')}
Followers: {f"{followers:,}" if followers else "unknown"}
Engagement Rate: {f"{eng_rate:.1f}%" if eng_rate is not None else "unknown"}
Production Quality: {production_quality or "unknown"}
Detected Visual Scenes: {detected_scenes or "not available"}

TRANSCRIPT (spoken content from their reels):
{transcript[:3000] if transcript else "No transcript available — analysis based on profile data only."}

Respond with ONLY a valid JSON object — no markdown fences, no explanation, just raw JSON:
{{
  "fit_score": <0-100 — overall fit for this specific campaign>,
  "quality_score": <0-100 — overall creator quality>,
  "authenticity": <0-100>,
  "content_consistency": <0-100>,
  "brand_safety": <0-100>,
  "production_quality_score": <0-100>,
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "concerns": ["concern 1", "concern 2"],
  "recommendation": "yes" | "maybe" | "no",
  "reasoning": "<2-3 sentence explanation referencing specific content from the transcript or scenes>"
}}"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
            )
            result = _parse_json(response.get("content", ""))
            if result is None:
                return {
                    "error": "LLM returned unparseable response",
                    "raw": response.get("content", "")[:500],
                }
            result["username"] = username.lstrip("@").lower()
            result["campaign_brief"] = campaign_brief
            return result
        except Exception as e:
            return {"error": str(e)}

    def export_shortlist(self, campaign_name: str = "shortlist") -> dict:
        """Export the current shortlist to a CSV file with agent rationale."""
        if not self.shortlist:
            return {"status": "empty", "message": "No creators on shortlist to export"}

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in campaign_name)
        base_dir = self.csv_path.parent if self.csv_path else (
            self._store.db_path.parent if self._store else Path("output")
        )
        output_dir = base_dir / "shortlists"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{safe_name}_{timestamp}.csv"

        rows = []
        for creator in self.shortlist:
            row = dict(creator["data"])
            row["agent_rationale"] = creator["reason"]
            rows.append(row)

        import csv as csv_mod
        if rows:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv_mod.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

        return {
            "status": "exported",
            "path": str(out_path),
            "creators_exported": len(rows),
        }

    def discover_creators(
        self,
        platform: str = "instagram",
        filters: Optional[dict] = None,
        limit: int = 20,
        campaign_name: Optional[str] = None,
    ) -> dict:
        """Search influencers.club database for creators matching flexible criteria.

        Use this to discover new creators. Filters are flexible — try any combination:
        followers_min, followers_max, engagement_min, engagement_max, niche,
        category, location, language, etc.

        Discovered creators are automatically added to the SQLite database.
        If campaign_name is set, creators already used in that campaign are excluded.
        """
        from .influencers_club import InfluencersClubAPI

        try:
            api = InfluencersClubAPI()
        except ValueError as e:
            return {"error": str(e)}

        try:
            response = api.discover(platform=platform, filters=filters or {}, limit=limit, page=1)
        except Exception as e:
            logger.error("API discovery failed: %s", e)
            return {"error": f"API call failed: {str(e)}"}

        creators = api.parse_accounts(response)

        if campaign_name:
            excluded_file = Path("output") / "campaigns" / campaign_name / "excluded.txt"
            if excluded_file.exists():
                excluded = set(line.strip() for line in excluded_file.read_text().splitlines() if line.strip())
                creators = [c for c in creators if c["username"].lower() not in excluded]

        # Auto-insert discovered creators into the SQLite database
        if self._store:
            inserted = 0
            for creator in creators:
                try:
                    row = {
                        "ig_username": creator["username"],
                        "ig_full_name": creator.get("full_name", ""),
                        "followers": creator.get("followers", 0),
                        "avg_engagement_rate": creator.get("engagement_percent", 0),
                        "data_source": "influencers_club_api",
                        "discovery_date": json.dumps(__import__("datetime").datetime.now().isoformat()),
                    }
                    self._store.upsert(row)
                    inserted += 1
                except Exception as e:
                    logger.warning("Failed to insert discovered creator %s: %s", creator["username"], e)

            logger.info("Discovered %d creators, inserted %d into database", len(creators), inserted)

        return {
            "total_available": response.get("total", "?"),
            "returned": len(creators),
            "inserted_into_db": inserted if self._store else 0,
            "credits_left": response.get("credits_left", "?"),
            "trial_searches_left": response.get("trial_searches_left", "?"),
            "creators": creators,
            "note": "Call queue_for_vetting with usernames to run them through the full vetting pipeline, or browse them in the Browse page"
        }

    def queue_for_vetting(
        self,
        usernames: list[str],
        campaign_name: Optional[str] = None,
    ) -> dict:
        """Queue usernames to be processed by the vetting pipeline.

        Usernames are written to a CSV file. Go to Pipeline page and select it to run analysis.
        """
        from datetime import datetime

        if not usernames:
            return {"error": "No usernames provided"}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        queue_dir = Path("output") / "queued"
        queue_dir.mkdir(parents=True, exist_ok=True)
        queue_file = queue_dir / f"discovery_{timestamp}.csv"

        with open(queue_file, "w") as f:
            f.write("username\n")
            for username in usernames:
                f.write(f"{username}\n")

        if campaign_name:
            campaign_dir = Path("output") / "campaigns" / campaign_name
            campaign_dir.mkdir(parents=True, exist_ok=True)

        return {
            "status": "queued",
            "count": len(usernames),
            "queue_file": str(queue_file),
            "next_step": "Go to the Pipeline page, select this file, and run it. Analyzed creators will be added to the database."
        }

    def list_briefs(self) -> dict:
        """List all available campaign briefs."""
        briefs_dir = self.knowledge_dir / "briefs"
        if not briefs_dir.exists():
            return {"briefs": [], "note": "No briefs yet. Create one in the Briefs page."}
        files = sorted(p.name for p in briefs_dir.glob("*.md"))
        return {"briefs": files, "count": len(files)}

    def read_brief(self, brief_name: str) -> dict:
        """Read the full content of a campaign brief."""
        briefs_dir = self.knowledge_dir / "briefs"
        path = briefs_dir / brief_name
        if not path.exists():
            path = briefs_dir / f"{brief_name}.md"
        if not path.exists():
            return {"error": f"Brief '{brief_name}' not found. Use list_briefs() to see available briefs."}
        return {"brief_name": brief_name, "content": path.read_text(encoding="utf-8")}

    def discover_via_modash(
        self,
        filters: Optional[dict] = None,
        limit: int = 20,
        campaign_name: Optional[str] = None,
    ) -> dict:
        """Discover creators via Modash API with flexible filters.

        Modash filters:
          followers: {min: int, max: int}
          engagementRate: {min: float, max: float}
          location: {country: [ISO 3166-1 alpha-2 codes]}
          language: [language codes]
          categories: [niche names]
          bio: {keywords: [strings]}
        """
        try:
            from .modash import ModashAPI
        except ImportError as e:
            return {"error": f"Failed to import ModashAPI: {e}"}

        try:
            api = ModashAPI()
        except ValueError as e:
            return {"error": str(e)}

        try:
            response = api.search(filters=filters or {}, limit=limit, page=1)
        except Exception as e:
            logger.error("Modash search failed: %s", e)
            return {"error": f"Modash search failed: {str(e)}"}

        creators = api.parse_accounts(response)

        if campaign_name:
            excluded_file = Path("output") / "campaigns" / campaign_name / "excluded.txt"
            if excluded_file.exists():
                excluded = set(line.strip() for line in excluded_file.read_text().splitlines() if line.strip())
                creators = [c for c in creators if c["username"].lower() not in excluded]

        inserted = 0
        if self._store:
            for creator in creators:
                try:
                    row = {
                        "ig_username": creator["username"],
                        "ig_full_name": creator.get("full_name", ""),
                        "followers": creator.get("followers", 0),
                        "avg_engagement_rate": creator.get("engagement_percent", 0),
                        "data_source": "modash_api",
                        "discovery_date": json.dumps(__import__("datetime").datetime.now().isoformat()),
                    }
                    self._store.upsert(row)
                    inserted += 1
                except Exception as e:
                    logger.warning("Failed to insert discovered creator %s: %s", creator["username"], e)

            logger.info("Discovered %d creators via Modash, inserted %d into database", len(creators), inserted)

        return {
            "total_available": response.get("total", "?"),
            "returned": len(creators),
            "inserted_into_db": inserted if self._store else 0,
            "credits_left": response.get("credits_left", "?"),
            "creators": creators,
            "note": "Call queue_for_vetting with usernames to run them through the full vetting pipeline, or browse them in the Browse page"
        }

    def brief_to_discovery(
        self,
        brief_name: str,
        limit: int = 20,
        campaign_name: Optional[str] = None,
    ) -> dict:
        """Extract Modash filters from a campaign brief, then run discovery.

        Reads a brief file, uses Claude to extract structured Modash API filters,
        then calls discover_via_modash with those filters.
        """
        brief_result = self.read_brief(brief_name)
        if "error" in brief_result:
            return brief_result

        brief_content = brief_result["content"]

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return {"error": "ANTHROPIC_API_KEY not set — cannot extract filters from brief"}

        try:
            from anthropic import Anthropic
        except ImportError as e:
            return {"error": f"Failed to import Anthropic SDK: {e}"}

        try:
            client = Anthropic(api_key=api_key)
        except Exception as e:
            return {"error": f"Failed to initialize Anthropic client: {e}"}

        extraction_prompt = """You are a Modash API search expert. Extract structured filters from this campaign brief.

Your job is to translate the brief's campaign goals, target audience, niche, and brand notes into precise Modash API filters that will find the right creators.

## Field guidance:

**categories** (Modash niche keywords): Match the brief's niche description to Modash category names.
Common categories: fitness, health, wellness, beauty, skincare, fashion, lifestyle, food, beverage, travel, gaming, technology, business, photography, art
- Extract 1-3 primary categories that match the brief's niche
- Think semantically: "skincare expert" → ["beauty", "skincare"]; "workout creator" → ["fitness", "health"]
- Include secondary categories if the brief mentions them (e.g., "sustainable fashion" → ["fashion", "lifestyle"])

**followers** (min/max range): Translate the brief's "Creator Tier" to a follower range.
- nano: {min: 5000, max: 20000}
- micro: {min: 20000, max: 100000}
- macro: {min: 100000, max: 500000}
- mega: {min: 500000} (no max)

**location** (country codes): Translate the brief's Location field to ISO 3166-1 alpha-2 codes.
Examples: GB=United Kingdom, US=United States, CA=Canada, AU=Australia, DE=Germany, FR=France, ES=Spain, IT=Italy
- Extract all mentioned countries/regions

**engagementRate** (minimum engagement %): Use the brief's "Minimum Engagement Rate" (e.g., 2.5% → 2.5)
- If not specified, omit this field

**language** (language codes): Extract from the brief's Location or explicit language mentions.
- Default to ["en"] if not specified
- Common codes: en=English, es=Spanish, fr=French, de=German, it=Italian

**bio** (creator profile keywords): Extract from "Brand Safety Notes", "Content Style", and "Target Audience" descriptions.
- Look for authentic markers the brief values: e.g., "certified nutritionist", "sustainable", "certified organic", "mental health advocate"
- Look for what creators should NOT claim to avoid brand safety issues
- Extract 2-4 keywords that authentic creators in this niche would naturally include in their bio
- Omit if the brief doesn't specify bio requirements

## Example:

Brief: "Health & Wellness brand, micro influencers, UK & US, 2%+ engagement, authentic wellness advocates with certifications"
→ {
  "categories": ["health", "wellness"],
  "followers": {"min": 20000, "max": 100000},
  "location": {"country": ["GB", "US"]},
  "engagementRate": {"min": 2.0},
  "language": ["en"],
  "bio": {"keywords": ["certified", "wellness", "health coach"]}
}

## Output instruction:

Return ONLY a valid JSON object (no markdown fences, no extra text). Include only fields you can determine from the brief."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=extraction_prompt,
                messages=[{"role": "user", "content": brief_content}]
            )
        except Exception as e:
            logger.error("Failed to extract filters via Claude: %s", e)
            return {"error": f"Failed to extract filters from brief: {str(e)}"}

        from .llm_analyzer import _parse_json
        extracted_filters = _parse_json(response.content[0].text)

        if isinstance(extracted_filters, str):
            logger.error("Failed to parse filter JSON: %s", extracted_filters)
            return {"error": f"Failed to parse extracted filters: {extracted_filters}"}

        modash_key = os.getenv("MODASH_API_KEY")
        if not modash_key:
            return {
                "brief_name": brief_name,
                "extracted_filters": extracted_filters,
                "error": "MODASH_API_KEY not set — cannot run discovery. Filters extracted and shown above."
            }

        discovery_result = self.discover_via_modash(
            filters=extracted_filters,
            limit=limit,
            campaign_name=campaign_name
        )

        return {
            "brief_name": brief_name,
            "extracted_filters": extracted_filters,
            "discovery_result": discovery_result
        }
