"""
vetter.py — Campaign-aware vetting pipeline (v2).

One motion: CSV + campaign spec → shortlist.csv / rejected.csv / review.csv.

Flow per creator:
  1. Modash fetch (profile + reels, now including bio + captions)
  2. Deterministic metrics scoring (scorer.py — unchanged)
  3. HARD FILTERS from the campaign spec — fails here cost no download/LLM
  4. Download reels → Whisper transcript (with speech-confidence hint)
     + sampled frames for vision
  5. ONE structured Claude call: bio + captions + transcripts + frames +
     campaign brief → verdict via forced tool use (no JSON parsing)
  6. Route to shortlist / rejected / review; full evidence saved per-creator
     as JSON; CSVs stay lean (one-line reasons, no essays)

Design rules this module enforces (see SYSTEM_CONTEXT.md §5a):
  - Audio transcripts are often licensed MUSIC, not the creator speaking.
    The prompt instructs Claude to never attribute lyric content to the
    creator. (April Alexander / Richard Bromilow false rejects, 2026-06.)
  - Universal disqualifiers come back as a structured enum list — the
    keyword-scan gate is not used in this flow. push_to_spine is simply
    "no disqualifiers returned".
  - Missing data is routed to review as no_content / fetch_failed — it is
    never scored, never sent to the LLM, and never recorded as "unsafe".
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

from .campaign import CampaignSpec
from .downloader import VideoDownloader
from .fetcher import ModashFetcher, extract_username
from .frames import sample_frames_batch
from .llm_analyzer import _load_calibration
from .scorer import score_profile
from .transcriber import Transcriber

logger = logging.getLogger(__name__)

# Universal disqualifier vocabulary — mirrors the Hard Reject categories in
# knowledge/expertise.md. The LLM may ONLY use these values; anything else
# is rejected at the API schema layer.
UNIVERSAL_DISQUALIFIERS = [
    "adult_sexual_content",
    "mlm",
    "eating_disorder_advocacy",
    "pseudo_medical_claims",
    "anti_medical_advocacy",
    "political_extremism",
    "hate_speech",
    "harassment_or_illegal",
    "religious_extremism",
]

VERDICT_TOOL = {
    "name": "record_vetting_verdict",
    "description": (
        "Record the structured vetting verdict for this creator against the "
        "campaign brief. This is the only way to respond."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "primary_niche": {
                "type": "string",
                "description": "Single best-fitting content niche for this creator.",
            },
            "campaign_fit_score": {
                "type": "integer", "minimum": 0, "maximum": 100,
                "description": "Fit against THIS campaign brief. Use the full range.",
            },
            "recommendation": {
                "type": "string",
                "enum": ["approve", "reject", "needs_review"],
                "description": (
                    "approve = clearly fits the brief. reject = clearly does not. "
                    "needs_review = genuine ambiguity a human should resolve."
                ),
            },
            "reason": {
                "type": "string",
                "description": "One plain-language sentence, max 30 words.",
            },
            "evidence": {
                "type": "string",
                "description": (
                    "Max 40 words citing what you actually observed: bio text, "
                    "caption content, what the frames show, or clearly-spoken speech."
                ),
            },
            "universal_disqualifiers": {
                "type": "array",
                "items": {"type": "string", "enum": UNIVERSAL_DISQUALIFIERS},
                "description": (
                    "ONLY when the creator themselves exhibits it. Empty list "
                    "if none. Background-music lyrics NEVER count."
                ),
            },
            "visual_flags": {
                "type": "string",
                "enum": ["none", "suggestive", "nsfw"],
                "description": "What the sampled frames show, judged independently of audio.",
            },
            "spoken_content_is_music": {
                "type": "boolean",
                "description": (
                    "True if the reel transcripts read as song lyrics / trending "
                    "audio rather than the creator speaking."
                ),
            },
            "engagement_texture": {
                "type": "string",
                "enum": ["real_conversation", "mixed", "emoji_or_bot", "unknown"],
                "description": (
                    "From the sampled comments: real_conversation = substantive "
                    "replies, named people, questions answered. emoji_or_bot = "
                    "emoji rows, generic praise, repeated spam. unknown if no "
                    "comments were provided."
                ),
            },
        },
        "required": [
            "primary_niche", "campaign_fit_score", "recommendation",
            "reason", "evidence", "universal_disqualifiers",
            "visual_flags", "spoken_content_is_music", "engagement_texture",
        ],
    },
}

_SYSTEM_TEMPLATE = """\
You are an experienced influencer-selection specialist at Augmentum Media,
vetting Instagram creators for one specific client campaign.

{calibration}

=== CAMPAIGN: {campaign_name} ===
{brief}

Target niches: {target_niches}
{judgment_notes}

=== EVIDENCE RULES — READ CAREFULLY ===

1. AUDIO TRANSCRIPTS ARE OFTEN MUSIC, NOT THE CREATOR. Instagram reels
   frequently use licensed/trending songs. Whisper transcribes those lyrics
   exactly like speech. If a transcript reads like song lyrics (rhyming,
   repeated hooks, slang typical of rap/pop, disconnected from the visuals),
   treat it as ambient audio: NEVER attribute its words to the creator,
   NEVER reject for profanity or slurs inside lyrics, NEVER classify the
   creator as a "music creator" because of it. A personal trainer using a
   rap track is still a personal trainer.
2. The creator's OWN words are the bio and captions. First-person
   instructional speech in transcripts (marked higher speech-confidence)
   also counts. Judge their positioning from these, plus what the sampled
   frames actually show.
3. The frames are your visual evidence — judge content type, production
   feel, aesthetic fit, and any NSFW/suggestive content from them directly.
4. Cite concrete observations in `evidence`. No speculation about data you
   were not given.
4b. If SAMPLE COMMENTS are provided, judge engagement texture from them:
   substantive replies and real conversation signal a genuine audience;
   rows of emoji and generic one-word praise signal bought or bot
   engagement. A modest engagement RATE with real conversation beats a
   high rate that reads bot-driven.
5. Universal disqualifiers are for the CREATOR'S OWN conduct/content only
   (their bio, their captions, their visuals, their own speech). When
   uncertain, leave the list empty and use needs_review.
6. Campaign misfit is NOT a disqualifier — a creator wrong for this client
   may be right for another. Keep the two judgments separate.

Respond ONLY by calling record_vetting_verdict.
"""


def _build_user_content(
    metrics: dict,
    biography: str,
    captions: list[str],
    transcripts: list[dict],
    frames_b64: list[str],
    comments: list[str] = None,
) -> list[dict]:
    """Assemble the multimodal content blocks for the judgment call."""
    lines = [
        f"Creator: @{metrics.get('ig_username', 'unknown')}",
        f"Display name: {metrics.get('ig_full_name', '')}",
        f"Verified: {metrics.get('ig_verified', False)}",
        f"Followers: {metrics.get('followers', 0):,} | "
        f"Engagement rate: {metrics.get('avg_engagement_rate', 0)}% | "
        f"Posts in last 30 days: {metrics.get('posts_last_30_days', 0)} | "
        f"Days since last post: {metrics.get('days_since_last_post', 'unknown')}",
        "",
        "--- BIO (creator's own words) ---",
        biography.strip() or "(empty)",
    ]

    real_captions = [c.strip() for c in captions if c and c.strip()]
    lines.append("")
    lines.append("--- RECENT CAPTIONS (creator's own words) ---")
    if real_captions:
        for i, cap in enumerate(real_captions[:10], 1):
            lines.append(f"{i}. {cap[:300]}")
    else:
        lines.append("(no captions available)")

    lines.append("")
    lines.append("--- SAMPLE COMMENTS from recent posts (judge engagement texture) ---")
    real_comments = [c for c in (comments or []) if c.strip()]
    if real_comments:
        for c in real_comments[:20]:
            lines.append(f"• {c}")
    else:
        lines.append("(no comments available — set engagement_texture to unknown)")

    lines.append("")
    lines.append(
        "--- REEL AUDIO TRANSCRIPTS (may be background music — see evidence rules) ---"
    )
    if transcripts:
        for i, t in enumerate(transcripts, 1):
            text = (t.get("text") or "").strip()
            conf = t.get("speech_confidence", "none")
            if text:
                lines.append(f"Reel {i} [speech-confidence: {conf}]: {text[:1500]}")
            else:
                lines.append(f"Reel {i}: (no speech detected)")
    else:
        lines.append("(no transcripts available)")

    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]

    if frames_b64:
        content.append({
            "type": "text",
            "text": (
                f"--- {len(frames_b64)} FRAMES sampled from their recent reels follow ---"
            ),
        })
        for b64 in frames_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })

    return content


# CSV schemas — lean by design. Full evidence lives in profiles/<username>.json.
# "source" is "fresh" or "cached:<date>" when the verdict was reused from a
# previous run within the cache window (see src/vetting_cache.py).
_SHORTLIST_FIELDS = [
    "ig_username", "profile_url", "ig_full_name", "followers",
    "avg_engagement_rate", "engagement_texture", "audience_target_pct",
    "audience_credibility", "audience_top_countries", "posts_last_30_days",
    "primary_niche", "campaign_fit_score", "reason", "evidence",
    "push_to_spine", "source",
]
_REJECTED_FIELDS = [
    "ig_username", "profile_url", "followers", "avg_engagement_rate",
    "stage", "category", "reason", "source",
]
_REVIEW_FIELDS = [
    "ig_username", "profile_url", "followers", "avg_engagement_rate",
    "stage", "category", "reason", "source",
]


class _IncrementalCsv:
    """Header-on-open CSV writer, flushed per row so crashes lose nothing."""

    def __init__(self, path: Path, fieldnames: list[str]):
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=fieldnames, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._file.flush()
        self.count = 0

    def write(self, row: dict):
        self._writer.writerow(row)
        self._file.flush()
        self.count += 1

    def close(self):
        self._file.close()


class CampaignVetter:
    """CSV + campaign spec in → shortlist / rejected / review out."""

    def __init__(
        self,
        campaign: CampaignSpec,
        config_path: str = "config/config.yaml",
        use_cache: bool = True,
    ):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        load_dotenv()
        modash_key = os.getenv("MODASH_API_KEY")
        if not modash_key:
            raise ValueError("MODASH_API_KEY is not set — required for fetching.")
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError(
                "ANTHROPIC_API_KEY is not set — the campaign vetter needs the "
                "LLM judgment call (it has no CLIP fallback)."
            )

        self.campaign = campaign

        modash_cfg = self.config.get("modash", {})
        whisper_cfg = self.config.get("whisper", {})
        cv_cfg = self.config.get("campaign_vetting", {})

        self.reels_per_creator: int = cv_cfg.get(
            "reels_per_creator", modash_cfg.get("reels_per_creator", 3)
        )
        self.frames_per_reel: int = cv_cfg.get("frames_per_reel", 2)
        self.max_total_frames: int = cv_cfg.get("max_total_frames", 8)
        self.max_image_dim: int = cv_cfg.get("max_image_dim", 512)
        self.jpeg_quality: int = cv_cfg.get("jpeg_quality", 70)

        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.fetcher = ModashFetcher(
            api_key=modash_key,
            base_url=modash_cfg.get("base_url"),
            requests_per_second=modash_cfg.get("requests_per_second", 2.0),
        )
        self.downloader = VideoDownloader(temp_dir=self.temp_dir, max_workers=4)
        self.transcriber = Transcriber(
            model_size=whisper_cfg.get("model_size", "base"),
            language=whisper_cfg.get("language"),
            device=whisper_cfg.get("device", "auto"),
        )

        from .llm_client import AnthropicClient
        model = cv_cfg.get("model") or os.getenv(
            "LLM_MODEL", "claude-haiku-4-5-20251001"
        )
        self.llm = AnthropicClient(model=model)
        logger.info("Campaign vetter using %s", self.llm)

        # Cross-run verdict cache — creators already judged for this campaign
        # within the window are reused, skipping fetch/download/LLM entirely.
        self.cache = None
        if use_cache and cv_cfg.get("cache_enabled", True):
            from .vetting_cache import VettingCache
            self.cache = VettingCache(
                max_age_days=cv_cfg.get("cache_max_age_days", 183),
            )

        # System prompt is fixed per run — build it once.
        knowledge_dir = Path(__file__).parent.parent / "knowledge"
        client_dir = (
            knowledge_dir / "clients" / campaign.client_folder
            if campaign.client_folder else None
        )
        calibration = _load_calibration(knowledge_dir, client_dir)
        self.system_prompt = _SYSTEM_TEMPLATE.format(
            calibration=calibration,
            campaign_name=campaign.name,
            brief=campaign.brief or "(no campaign brief provided)",
            target_niches=", ".join(campaign.target_niches) or "any",
            judgment_notes=(
                f"\nAdditional campaign judgment notes:\n{campaign.judgment_notes}"
                if campaign.judgment_notes else ""
            ),
        )

    # ──────────────────────────────────────────────────────────────────
    def _judge(
        self,
        metrics: dict,
        biography: str,
        captions: list[str],
        transcripts: list[dict],
        frames_b64: list[str],
        comments: list[str] = None,
    ) -> Optional[dict]:
        """One structured judgment call. Returns the verdict dict or None."""
        content = _build_user_content(
            metrics, biography, captions, transcripts, frames_b64, comments
        )
        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": content}],
                system=self.system_prompt,
                tools=[VERDICT_TOOL],
                tool_choice={"type": "tool", "name": "record_vetting_verdict"},
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning(
                "@%s: judgment call failed — %s",
                metrics.get("ig_username"), e,
            )
            return None

        for call in response.get("tool_calls", []):
            if call.get("name") == "record_vetting_verdict":
                return call.get("arguments") or None
        logger.warning(
            "@%s: no verdict tool call in response", metrics.get("ig_username")
        )
        return None

    def _gather_content(self, profile: dict) -> tuple[list[dict], list[str]]:
        """Download reels, transcribe, sample frames. Videos always cleaned up."""
        video_urls = self.fetcher.extract_reel_urls(
            profile, max_reels=self.reels_per_creator
        )
        if not video_urls:
            return [], []

        video_paths: list[Path] = []
        try:
            video_paths = self.downloader.download_reels(
                video_urls, profile.get("username", "unknown")
            )
            transcripts = self.transcriber.transcribe_batch_detailed(video_paths)
            frames = sample_frames_batch(
                video_paths,
                frames_per_reel=self.frames_per_reel,
                max_dim=self.max_image_dim,
                jpeg_quality=self.jpeg_quality,
                max_total_frames=self.max_total_frames,
            )
            return transcripts, frames
        finally:
            self.downloader.cleanup(video_paths)

    # ──────────────────────────────────────────────────────────────────
    def run(
        self,
        input_path: str,
        output_dir: Optional[str] = None,
        limit: Optional[int] = None,
        progress_callback=None,
    ) -> Path:
        """
        Vet every creator in the input CSV against the campaign.

        progress_callback, if given, is called as
        callback(done_count, total, username, stage_label) — used by the
        Streamlit page to drive a live progress bar. Must be called from
        this thread (Streamlit widgets are not thread-safe).

        Returns the run output directory containing shortlist.csv,
        rejected.csv, review.csv, and profiles/<username>.json.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path(output_dir) if output_dir else (
            Path("output") / "campaigns" / f"{self.campaign.name}_{timestamp}"
        )
        profiles_dir = run_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        df = pd.read_csv(input_path)
        col_config = self.config.get("input_columns", {})

        def resolve(row) -> Optional[str]:
            for col_key in ("url", "username"):
                col_name = col_config.get(col_key)
                if col_name and col_name in row.index and pd.notna(row[col_name]):
                    username = extract_username(str(row[col_name]))
                    if username:
                        return username
            return None

        df["_username"] = df.apply(resolve, axis=1)
        valid = df[df["_username"].notna()]
        usernames = valid["_username"].tolist()
        if limit:
            usernames = usernames[:limit]
        logger.info(
            "Campaign '%s': %d creators to vet (%d rows had no resolvable username)",
            self.campaign.name, len(usernames), int(df["_username"].isna().sum()),
        )

        # Cache check first — fresh verdicts for this campaign skip Modash,
        # downloads, and the LLM entirely.
        cached_hits: dict[str, dict] = {}
        if self.cache:
            for u in usernames:
                hit = self.cache.get(u, self.campaign.name)
                if hit:
                    cached_hits[u] = hit
            if cached_hits:
                logger.info(
                    "Vetting cache: %d/%d creators already judged for '%s' "
                    "within the freshness window — reusing those verdicts",
                    len(cached_hits), len(usernames), self.campaign.name,
                )

        to_fetch = [u for u in usernames if u not in cached_hits]
        profiles = {}
        if to_fetch:
            if progress_callback:
                progress_callback(
                    0, len(usernames), "",
                    f"Fetching {len(to_fetch)} profiles from Modash…",
                )
            logger.info("Fetching profiles via Modash...")
            profiles = self.fetcher.fetch_profiles(to_fetch)

        shortlist = _IncrementalCsv(run_dir / "shortlist.csv", _SHORTLIST_FIELDS)
        rejected = _IncrementalCsv(run_dir / "rejected.csv", _REJECTED_FIELDS)
        review = _IncrementalCsv(run_dir / "review.csv", _REVIEW_FIELDS)

        llm_calls = 0
        fresh_judged: list[dict] = []   # full records for the spine push
        try:
            for done, username in enumerate(
                tqdm(usernames, desc=f"Vetting for {self.campaign.name}")
            ):
                if progress_callback:
                    progress_callback(
                        done, len(usernames), username,
                        f"Vetting @{username} (downloading reels, transcribing, judging)",
                    )
                profile_url = f"https://www.instagram.com/{username}/"
                base = {
                    "ig_username": username, "profile_url": profile_url,
                    "source": "fresh",
                }

                # Replay cached verdicts unchanged
                hit = cached_hits.get(username)
                if hit:
                    row = dict(hit["row"])
                    row["source"] = f"cached:{hit['vetted_at'][:10]}"
                    target = {
                        "shortlist": shortlist, "rejected": rejected,
                    }.get(hit["bucket"], review)
                    target.write(row)
                    continue

                profile = profiles.get(username)
                if not profile:
                    review.write({
                        **base, "stage": "fetch", "category": "fetch_failed",
                        "reason": "Modash returned no data — profile may be "
                                  "deleted, renamed, or temporarily unavailable.",
                    })
                    continue

                metrics = score_profile(profile, self.config)
                base.update({
                    "followers": metrics.get("followers"),
                    "avg_engagement_rate": metrics.get("avg_engagement_rate"),
                })

                # ── Stage 1: hard filters — free, deterministic ──
                hard = self.campaign.apply_hard_filters(metrics)
                if not hard.passed:
                    target = review if hard.bucket == "review" else rejected
                    target.write({
                        **base, "stage": "hard_filter",
                        "category": hard.category, "reason": hard.reason,
                    })
                    continue

                # ── Stage 2: content gathering ──
                transcripts, frames = self._gather_content(profile)
                captions = [
                    p.get("caption", "") for p in profile.get("latestPosts", [])
                ]
                biography = profile.get("biography", "")

                has_signal = bool(
                    frames or biography.strip()
                    or any(c.strip() for c in captions)
                    or any((t.get("text") or "").strip() for t in transcripts)
                )
                if not has_signal:
                    review.write({
                        **base, "stage": "content", "category": "no_content",
                        "reason": "Passed metric filters but no reels, bio, or "
                                  "captions available to judge — needs a manual look.",
                    })
                    continue

                # Sample comments from the two most recent posts — texture
                # evidence for the judgment (real conversation vs emoji rows)
                comments: list[str] = []
                for post in profile.get("latestPosts", [])[:2]:
                    if post.get("code"):
                        comments.extend(
                            self.fetcher.fetch_post_comments(post["code"])
                        )
                    if len(comments) >= 20:
                        break

                # ── Stage 3: one structured judgment call ──
                verdict = self._judge(
                    metrics, biography, captions, transcripts, frames, comments
                )
                llm_calls += 1
                if verdict is None:
                    review.write({
                        **base, "stage": "llm", "category": "judgment_failed",
                        "reason": "LLM judgment call failed — re-run or review manually.",
                    })
                    continue

                disqualifiers = verdict.get("universal_disqualifiers") or []
                push_to_spine = len(disqualifiers) == 0
                recommendation = verdict.get("recommendation", "needs_review")

                # ── Stage 4: audience check — Modash report (costs credits),
                # fetched ONLY for approvals. Below the campaign floor →
                # demote to review with the numbers attached (estimates are
                # noisy; a human makes the final call).
                audience = None
                audience_target_pct = None
                if (
                    recommendation == "approve"
                    and not disqualifiers
                    and self.campaign.audience_target_country
                ):
                    audience = self.fetcher.fetch_audience_report(username)
                    if audience:
                        target = self.campaign.audience_target_country.lower()
                        audience_target_pct = next(
                            (pct for name, pct in audience["geo_countries"]
                             if name.lower() == target),
                            0.0,
                        )
                        floor = self.campaign.audience_min_pct
                        if floor is not None and audience_target_pct < floor:
                            recommendation = "needs_review"
                            top3 = ", ".join(
                                f"{n} {p}%" for n, p in audience["geo_countries"][:3]
                            )
                            verdict["reason"] = (
                                f"Content approved, but audience is only "
                                f"{audience_target_pct}% "
                                f"{self.campaign.audience_target_country} "
                                f"(floor {floor}%). Top: {top3}."
                            )

                # Persist full evidence per creator (CSV stays lean)
                full_record = {
                    "username": username,
                    "campaign": self.campaign.name,
                    "vetted_at": timestamp,
                    "platform_user_id": profile.get("platformUserId"),
                    "metrics": metrics,
                    "biography": biography,
                    "captions": captions,
                    "transcripts": transcripts,
                    "comments_sampled": comments,
                    "frames_sampled": len(frames),
                    "audience": audience,
                    "verdict": verdict,
                    "push_to_spine": push_to_spine,
                }
                fresh_judged.append(full_record)
                (profiles_dir / f"{username}.json").write_text(
                    json.dumps(full_record, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

                if disqualifiers:
                    row = {
                        **base, "stage": "gate",
                        "category": "|".join(disqualifiers),
                        "reason": verdict.get("reason", ""),
                    }
                    rejected.write(row)
                    bucket = "rejected"
                elif recommendation == "approve":
                    row = {
                        **base,
                        "ig_full_name": metrics.get("ig_full_name", ""),
                        "posts_last_30_days": metrics.get("posts_last_30_days"),
                        "primary_niche": verdict.get("primary_niche", ""),
                        "campaign_fit_score": verdict.get("campaign_fit_score"),
                        "engagement_texture": verdict.get("engagement_texture", ""),
                        "audience_target_pct": audience_target_pct,
                        "audience_credibility": (audience or {}).get("credibility"),
                        "audience_top_countries": ", ".join(
                            f"{n} {p}%"
                            for n, p in (audience or {}).get("geo_countries", [])[:3]
                        ),
                        "reason": verdict.get("reason", ""),
                        "evidence": verdict.get("evidence", ""),
                        "push_to_spine": push_to_spine,
                    }
                    shortlist.write(row)
                    bucket = "shortlist"
                elif recommendation == "reject":
                    row = {
                        **base, "stage": "judgment", "category": "campaign_misfit",
                        "reason": verdict.get("reason", ""),
                    }
                    rejected.write(row)
                    bucket = "rejected"
                else:
                    demoted_on_geo = (
                        audience_target_pct is not None
                        and self.campaign.audience_min_pct is not None
                        and audience_target_pct < self.campaign.audience_min_pct
                    )
                    row = {
                        **base,
                        "stage": "audience" if demoted_on_geo else "judgment",
                        "category": (
                            "audience_geo_mismatch" if demoted_on_geo
                            else "needs_review"
                        ),
                        "reason": verdict.get("reason", ""),
                    }
                    review.write(row)
                    bucket = "review"

                # Judged outcomes feed the cross-run cache (hard-filter
                # outcomes deliberately don't — metrics drift, rechecks are free)
                if self.cache:
                    self.cache.put(username, self.campaign.name, bucket, row, verdict)
        finally:
            shortlist.close()
            rejected.close()
            review.close()

        # ── Spine push (consolidate forward) — best-effort, never fails the run
        cv_cfg = self.config.get("campaign_vetting", {})
        if fresh_judged and cv_cfg.get("spine_push", True):
            try:
                from .spine import PushRecord, SpineClient, slugify_folder
                records = [
                    PushRecord(
                        username=fr["username"],
                        push_to_spine=fr["push_to_spine"],
                        recommendation=(fr["verdict"] or {}).get(
                            "recommendation", "needs_review"
                        ),
                        reason=(fr["verdict"] or {}).get("reason", ""),
                        niche=(fr["verdict"] or {}).get("primary_niche"),
                        fit_score=(fr["verdict"] or {}).get("campaign_fit_score"),
                        bio=fr.get("biography", ""),
                        followers=(fr.get("metrics") or {}).get("followers"),
                        display_name=(fr.get("metrics") or {}).get("ig_full_name", ""),
                        platform_user_id=fr.get("platform_user_id"),
                        engagement_rate=(fr.get("metrics") or {}).get(
                            "avg_engagement_rate"
                        ),
                        verdict=fr.get("verdict") or {},
                    )
                    for fr in fresh_judged
                ]
                slug = (
                    slugify_folder(self.campaign.client_folder)
                    if self.campaign.client_folder else None
                )
                push = SpineClient().push_records(
                    records, campaign=self.campaign.name,
                    client_slug=slug, dry_run=False,
                )
                logger.info(
                    "Spine push : %d profiles upserted, %d vetting rows, "
                    "%d held back (disqualified)%s",
                    push.upserted, push.vetting_rows, push.skipped_disqualified,
                    f", {len(push.errors)} errors" if push.errors else "",
                )
            except Exception as e:
                logger.warning(
                    "Spine push skipped — %s (run output is unaffected; "
                    "push later with push_run_to_spine.py)", e,
                )

        logger.info("\n── Campaign run complete ─────────────────")
        logger.info("Campaign   : %s", self.campaign.name)
        logger.info("Shortlist  : %d creators → %s", shortlist.count, run_dir / "shortlist.csv")
        logger.info("Rejected   : %d creators → %s", rejected.count, run_dir / "rejected.csv")
        logger.info("Review     : %d creators → %s", review.count, run_dir / "review.csv")
        logger.info("LLM calls  : %d", llm_calls)
        logger.info("Evidence   : %s", profiles_dir)
        logger.info("──────────────────────────────────────────\n")
        return run_dir
