#!/usr/bin/env python3
"""
run_campaign.py — Campaign-aware vetting from the command line.

One motion: CSV + campaign spec → shortlist.csv / rejected.csv / review.csv.

Usage:
    source ../../.venv/bin/activate
    python run_campaign.py --input input/creators.csv --campaign campaigns/thrivin.yaml
    python run_campaign.py --input input/creators.csv --campaign campaigns/thrivin.yaml --limit 5
    python run_campaign.py --input input/creators.csv --campaign campaigns/thrivin.yaml \
        --output output/campaigns/my_run --log-level DEBUG

Outputs land in output/campaigns/<name>_<timestamp>/ by default:
    shortlist.csv   — approved creators, lean columns, one-line reasons
    rejected.csv    — every rejection with stage + category + reason
    review.csv      — VIP-tier, no-data, and genuinely-ambiguous creators
    profiles/*.json — full evidence per judged creator (verdict, transcripts,
                      captions, metrics)
"""

import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Vet a CSV of Instagram creators against a campaign spec."
    )
    parser.add_argument(
        "--input", required=True,
        help="Input CSV with Profile URL and/or Username columns",
    )
    parser.add_argument(
        "--campaign", required=True,
        help="Campaign spec YAML (see campaigns/thrivin.yaml)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: output/campaigns/<name>_<timestamp>/)",
    )
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="Pipeline config path (default: config/config.yaml)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only vet the first N creators (for testing)",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Force fresh vetting — ignore verdicts cached from past runs "
             "(default: reuse judgments under 6 months old for this campaign)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    from src.campaign import CampaignSpec
    from src.vetter import CampaignVetter

    campaign = CampaignSpec.load(args.campaign)
    vetter = CampaignVetter(
        campaign, config_path=args.config, use_cache=not args.no_cache
    )
    run_dir = vetter.run(args.input, output_dir=args.output, limit=args.limit)
    print(f"\nDone. Results in: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
