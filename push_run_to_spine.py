#!/usr/bin/env python3
"""
push_run_to_spine.py — Push an existing v2 run's judged creators to the spine.

The vetter auto-pushes at the end of every run (campaign_vetting.spine_push),
but this CLI covers runs that predate the integration, runs where the push
errored, or re-pushes after a spine outage.

Usage:
    source ../../.venv/bin/activate
    # Dry-run (default) — prints exactly what WOULD be written
    python push_run_to_spine.py --run-dir output/campaigns/thrivin_20260611_xxxx

    # Apply
    python push_run_to_spine.py --run-dir output/campaigns/thrivin_20260611_xxxx --apply

Reads profiles/*.json from the run folder. Creators with universal
disqualifiers (push_to_spine=false) are never pushed.
"""

import argparse
import json
import logging
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Push a v2 campaign run's judged creators to the central spine."
    )
    parser.add_argument("--run-dir", required=True, help="Run folder (contains profiles/)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write (default is dry-run)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(levelname)-7s %(message)s")
    log = logging.getLogger("push")

    from src.campaign import CampaignSpec
    from src.spine import PushRecord, SpineClient, slugify_folder

    run_dir = Path(args.run_dir)
    profile_files = sorted((run_dir / "profiles").glob("*.json"))
    if not profile_files:
        log.error("No profiles/*.json in %s — nothing judged in this run.", run_dir)
        return 1

    records, campaign_name = [], None
    for pf in profile_files:
        fr = json.loads(pf.read_text(encoding="utf-8"))
        campaign_name = campaign_name or fr.get("campaign")
        verdict = fr.get("verdict") or {}
        records.append(PushRecord(
            username=fr["username"],
            push_to_spine=bool(fr.get("push_to_spine")),
            recommendation=verdict.get("recommendation", "needs_review"),
            reason=verdict.get("reason", ""),
            niche=verdict.get("primary_niche"),
            fit_score=verdict.get("campaign_fit_score"),
            bio=fr.get("biography", ""),
            followers=(fr.get("metrics") or {}).get("followers"),
            display_name=(fr.get("metrics") or {}).get("ig_full_name", ""),
            platform_user_id=fr.get("platform_user_id"),
            engagement_rate=(fr.get("metrics") or {}).get("avg_engagement_rate"),
            verdict=verdict,
        ))

    # Resolve client slug from the campaign spec
    slug = None
    if campaign_name:
        spec_path = Path("campaigns") / f"{campaign_name}.yaml"
        if spec_path.exists():
            spec = CampaignSpec.load(spec_path)
            if spec.client_folder:
                slug = slugify_folder(spec.client_folder)
    log.info("Run: %s | campaign: %s | client slug: %s | %d judged creators",
             run_dir.name, campaign_name, slug, len(records))

    result = SpineClient().push_records(
        records, campaign=campaign_name or run_dir.name,
        client_slug=slug, dry_run=not args.apply,
    )
    if args.apply:
        log.info("Upserted %d profiles | %d vetting rows | %d held back | "
                 "request_id=%s", result.upserted, result.vetting_rows,
                 result.skipped_disqualified, result.request_id)
        for err in result.errors:
            log.warning("ERROR: %s", err)
    else:
        log.info("Dry-run complete — re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
