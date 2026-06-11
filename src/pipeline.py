"""
pipeline.py — Orchestrates the full creator vetting pipeline.

Flow per creator:
  1. Resolve username from URL or username column
  2. Fetch Modash profile + reel video URLs
  3. Download reel videos to temp/ (parallel)
  4. Transcribe each reel with faster-whisper (local)
  5. Analyze frames with CLIP + OpenCV (local)
  6. Fuse transcript + visual → niche scores (analyzer)
  7. Score engagement + audience quality (scorer)
  8. Clean up temp video files
  9. Write enriched CSV row (incremental) + full JSON profile

Videos in temp/ are always deleted in a finally block — even on error.
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

from .analyzer import NicheAnalyzer
from .downloader import VideoDownloader
from .fetcher import ModashFetcher, extract_username
from .quality_gate import evaluate as gate_evaluate
from .scorer import score_profile
from .transcriber import Transcriber
from .visual import VisualAnalyzer

logger = logging.getLogger(__name__)


class Pipeline:
    """End-to-end creator vetting pipeline."""

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        load_dotenv()
        modash_key = os.getenv("MODASH_API_KEY")
        if not modash_key:
            raise ValueError(
                "MODASH_API_KEY is not set. Create a .env file with MODASH_API_KEY=your_key"
            )

        modash_cfg = self.config.get("modash", {})
        whisper_cfg = self.config.get("whisper", {})
        clip_cfg = self.config.get("clip", {})

        self.reels_per_creator: int = modash_cfg.get("reels_per_creator", 3)
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
        self.visual_analyzer = VisualAnalyzer(
            clip_prompts=self.config.get("clip_prompts", {}),
            model_name=clip_cfg.get("model", "ViT-B-32"),
            pretrained=clip_cfg.get("pretrained", "openai"),
            frames_per_second=clip_cfg.get("frames_per_second", 0.5),
        )
        self.niche_analyzer = NicheAnalyzer(
            niches=list(self.config.get("clip_prompts", {}).keys()),
            target_niches=self.config.get("target_niches", []),
            niche_keywords=self.config.get("niche_keywords", {}),
            visual_weight=self.config.get("analysis_weights", {}).get("visual", 0.6),
        )

        # Optional LLM analysis — enabled in config + ANTHROPIC_API_KEY must be set
        self.llm_analyzer = None
        llm_cfg = self.config.get("llm_analysis", {})
        if llm_cfg.get("enabled", False):
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                from .llm_analyzer import LLMAnalyzer
                from .llm_client import AnthropicClient
                llm_model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
                self.llm_analyzer = LLMAnalyzer(
                    llm_client=AnthropicClient(model=llm_model),
                    config=llm_cfg,
                )
                logger.info("LLM analysis enabled (%s)", llm_model)
            else:
                logger.warning(
                    "llm_analysis.enabled=true but ANTHROPIC_API_KEY not set — skipping LLM analysis"
                )

    def _resolve_username(self, row: pd.Series, col_config: dict) -> Optional[str]:
        """Try URL column first, then username column."""
        for col_key in ("url", "username"):
            col_name = col_config.get(col_key)
            if col_name and col_name in row.index:
                val = str(row[col_name]) if pd.notna(row[col_name]) else ""
                username = extract_username(val)
                if username:
                    return username
        return None

    def _process_creator(
        self, profile: dict, creator_idx: int = 0, creator_total: int = 0
    ) -> tuple[dict, dict]:
        """
        Run the full video analysis pipeline for a single creator.

        Returns (summary_dict, full_profile_dict).
        summary_dict  — goes into the enriched CSV (compact)
        full_profile  — written to output/profiles/<username>.json (complete raw data)
        Videos are deleted in a finally block regardless of outcome.

        creator_idx / creator_total are used to emit STEP|N/M|@user|label log lines
        that the Streamlit page parses for live progress. They default to 0 so the
        method still works when called outside of a pipeline run.
        """
        video_urls = self.fetcher.extract_reel_urls(profile, max_reels=self.reels_per_creator)
        username = profile.get("username", "unknown")
        n, m = creator_idx, creator_total

        empty_summary = {
            "reels_analyzed": 0,
            "transcript_sample": "",
            "primary_niche": "Unknown",
            "secondary_niche": None,
            "niche_confidence": 0,
            "brand_fit_score": 0,
            "content_summary": "No reels available",
            "detected_scenes": "",
            "production_quality": "unknown",
        }
        empty_profile = {
            "username": username,
            "reels_analyzed": 0,
            "transcripts": [],
            "full_transcript": "",
            "visual_results": [],
            "niche_scores": {},
            "analysis": empty_summary,
        }

        if not video_urls:
            logger.info("@%s: no reel URLs found — skipping video analysis", username)
            return empty_summary, empty_profile

        video_paths: list[Path] = []
        try:
            # Download
            logger.info("STEP|%d/%d|@%s|Downloading %d reels", n, m, username, len(video_urls))
            video_paths = self.downloader.download_reels(video_urls, username)
            if not video_paths:
                logger.warning("@%s: all reel downloads failed", username)

            # Transcribe
            logger.info(
                "STEP|%d/%d|@%s|Transcribing %d reel(s) with Whisper",
                n, m, username, len(video_paths),
            )
            transcripts = self.transcriber.transcribe_batch(video_paths)
            full_transcript = " ".join(t for t in transcripts if t)

            # Visual analysis
            logger.info(
                "STEP|%d/%d|@%s|Classifying scenes with CLIP",
                n, m, username,
            )
            visual_results = self.visual_analyzer.analyze_batch(video_paths)

            # Fuse into niche scores
            logger.info("STEP|%d/%d|@%s|Fusing niche scores", n, m, username)
            analysis = self.niche_analyzer.analyze(transcripts, visual_results)
            analysis["reels_analyzed"] = len(video_paths)
            analysis["transcript_sample"] = full_transcript[:300]

            # Build full profile (all raw data, unlimited)
            full_profile = {
                "username": username,
                "reels_analyzed": len(video_paths),
                "transcripts": transcripts,
                "full_transcript": full_transcript,
                "visual_results": [
                    {
                        "reel_index": i,
                        "clip_scores": r.get("clip_scores", {}),
                        "detected_scenes": r.get("detected_scenes", ""),
                        "production_quality": r.get("production_quality", "unknown"),
                        "quality_detail": r.get("quality_detail", {}),
                    }
                    for i, r in enumerate(visual_results)
                ],
                "niche_scores": analysis.get("_niche_scores", {}),
                "analysis": analysis,
            }

            return analysis, full_profile

        finally:
            self.downloader.cleanup(video_paths)

    def run(self, input_path: str, output_path: Optional[str] = None) -> Path:
        """
        Run the pipeline on an input CSV.

        Writes each row incrementally to the output CSV as it is processed.
        Also writes a full JSON profile per creator to output/profiles/.
        Returns the path of the written output CSV.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Resolve output path
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path("output") / f"enriched_{timestamp}.csv"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Load input
        df = pd.read_csv(input_path)
        logger.info("Loaded %d rows from %s", len(df), input_path)

        col_config = self.config.get("input_columns", {})

        # Resolve usernames
        df["_username"] = df.apply(
            lambda row: self._resolve_username(row, col_config), axis=1
        )
        missing = df["_username"].isna().sum()
        if missing:
            logger.warning(
                "%d rows had no resolvable username — they will be skipped", missing
            )

        valid_df = df[df["_username"].notna()].copy()
        usernames = valid_df["_username"].tolist()
        logger.info("%d valid creators to process", len(usernames))

        # Fetch all profiles from Modash
        logger.info("Fetching Instagram profiles via Modash...")
        profiles = self.fetcher.fetch_profiles(usernames)

        # Process each creator — write output incrementally
        csv_writer = None
        csv_file = None
        enriched_rows = []
        skipped = 0

        try:
            csv_file = open(output_path, "w", newline="", encoding="utf-8")

            total_creators = len(valid_df)
            for creator_idx, (_, row) in enumerate(
                tqdm(valid_df.iterrows(), total=total_creators, desc="Processing creators"),
                start=1,
            ):
                username = row["_username"]
                profile = profiles.get(username)

                logger.info(
                    "STEP|%d/%d|@%s|Starting",
                    creator_idx, total_creators, username,
                )

                if not profile:
                    logger.warning("@%s: no Modash data — skipping", username)
                    skipped += 1
                    continue

                # Engagement / audience scores
                logger.info(
                    "STEP|%d/%d|@%s|Computing engagement and audience scores",
                    creator_idx, total_creators, username,
                )
                engagement_data = score_profile(profile, self.config)

                # Video analysis (download → transcribe → visual → fuse)
                video_data, full_profile = self._process_creator(
                    profile, creator_idx=creator_idx, creator_total=total_creators
                )

                # Optional LLM analysis — adds llm_* columns
                if self.llm_analyzer is not None:
                    logger.info(
                        "STEP|%d/%d|@%s|Scoring against rubric with Claude",
                        creator_idx, total_creators, username,
                    )
                    llm_data = self.llm_analyzer.analyze(
                        username=username,
                        transcript=full_profile.get("full_transcript", ""),
                        detected_scenes=video_data.get("detected_scenes", ""),
                        production_quality=video_data.get("production_quality", "unknown"),
                        followers=engagement_data.get("followers"),
                        engagement_rate=engagement_data.get("avg_engagement_rate"),
                    )
                    video_data.update(llm_data)

                # Merge: original row columns + engagement scores + video analysis
                result = row.drop("_username").to_dict()
                result.update(engagement_data)
                result.update(video_data)

                # Quality gate — decides whether this creator is universally
                # disqualified (don't push to central DB) or only brand-fit
                # mismatched for the current client (do push). Adds three
                # columns: gate_decision, gate_reason, push_to_spine.
                logger.info(
                    "STEP|%d/%d|@%s|Running safety gate",
                    creator_idx, total_creators, username,
                )
                gate_result = gate_evaluate(result, self.config)
                result.update(gate_result)
                if not gate_result.get("push_to_spine", True):
                    logger.info(
                        "@%s: gate=%s — held back from central DB (%s)",
                        username,
                        gate_result.get("gate_decision"),
                        gate_result.get("gate_reason", "")[:120],
                    )

                logger.info(
                    "STEP|%d/%d|@%s|Done",
                    creator_idx, total_creators, username,
                )

                enriched_rows.append(result)

                # Write CSV header on first row
                if csv_writer is None:
                    fieldnames = list(result.keys())
                    csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
                    csv_writer.writeheader()

                csv_writer.writerow(result)
                csv_file.flush()  # ensure it hits disk immediately

        finally:
            if csv_file:
                csv_file.close()

        # Summary
        out_df = pd.DataFrame(enriched_rows)
        total = len(enriched_rows)
        logger.info("\n── Run complete ──────────────────────")
        logger.info("Processed : %d creators", total)
        logger.info("Skipped   : %d creators", skipped)
        logger.info("Output    : %s", output_path)

        if "tier" in out_df.columns and total > 0:
            tier_counts = out_df["tier"].value_counts().to_dict()
            for tier in ["A", "B", "C", "D"]:
                count = tier_counts.get(tier, 0)
                pct = round(count / total * 100)
                logger.info("Tier %s    : %d (%d%%)", tier, count, pct)

        if "primary_niche" in out_df.columns and total > 0:
            logger.info("\nTop niches:\n%s", out_df["primary_niche"].value_counts().head(5).to_string())

        # Quality gate summary — how many we'd push to the central DB
        if "push_to_spine" in out_df.columns and total > 0:
            push_count = int(out_df["push_to_spine"].sum())
            held_count = total - push_count
            logger.info(
                "Gate     : %d would be pushed to central DB, %d held back (%d%% pass)",
                push_count,
                held_count,
                round(push_count / total * 100),
            )
            if held_count > 0 and "gate_decision" in out_df.columns:
                rejected = out_df[~out_df["push_to_spine"]]["gate_decision"].value_counts()
                for decision, count in rejected.items():
                    logger.info("  • %s: %d", decision, count)

        logger.info("──────────────────────────────────────\n")
        return output_path
