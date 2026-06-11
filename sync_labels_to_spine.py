#!/usr/bin/env python3
"""
sync_labels_to_spine.py — Backfill locally-saved calibration labels to the spine.

The Calibration Deck records every swipe locally first (jsonl + markdown) and
pushes to the spine best-effort. When the spine was asleep/unreachable during
a session, this script syncs the missed labels: profile upsert + a
human_approved/human_rejected creator_vetting row per label.

Idempotent: synced labels are rewritten with "spine_synced": true and
skipped on later runs.

Usage:
    python sync_labels_to_spine.py            # all clients, dry-run
    python sync_labels_to_spine.py --apply
"""

import argparse
import json
import logging
import sys
from pathlib import Path

CLIENTS_DIR = Path("knowledge/clients")
RUNS_DIR = Path("output/campaigns")


def _find_profile_seed(username: str) -> dict:
    """Best profile data we hold locally for this creator (newest run wins)."""
    best, best_ts = {}, ""
    for pf in RUNS_DIR.glob(f"*/profiles/{username}.json"):
        try:
            rec = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        ts = str(rec.get("vetted_at", ""))
        if ts >= best_ts:
            best, best_ts = rec, ts
    m = best.get("metrics") or {}
    return {
        "biography": best.get("biography", ""),
        "followers": m.get("followers"),
        "ig_full_name": m.get("ig_full_name", ""),
        "platform_user_id": best.get("platform_user_id"),
        "avg_engagement_rate": m.get("avg_engagement_rate"),
        "verdict": best.get("verdict") or {},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write to the spine (default: dry-run)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    log = logging.getLogger("sync")

    from src.spine import record_human_decision, slugify_folder

    total_synced = 0
    for jsonl in CLIENTS_DIR.glob("*/calibration_labels.jsonl"):
        client_folder = jsonl.parent.name
        slug = slugify_folder(client_folder)
        lines = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
        pending = [l for l in lines if not l.get("spine_synced")]
        log.info("%s: %d labels, %d pending sync", client_folder, len(lines), len(pending))

        if not args.apply:
            for l in pending:
                log.info("  [dry-run] @%s → human_%s (%s)",
                         l["username"],
                         "approved" if l["human"] == "approve" else "rejected",
                         l.get("reviewer", "unknown"))
            continue

        changed = False
        for l in lines:
            if l.get("spine_synced"):
                continue
            seed = _find_profile_seed(l["username"])
            result = record_human_decision(
                username=l["username"],
                campaign=l.get("campaign", "unknown"),
                client_slug=slug,
                approved=(l["human"] == "approve"),
                reason=l.get("why") or f"calibration label by {l.get('reviewer', 'unknown')}",
                decided_by=l.get("reviewer", "unknown"),
                verdict=seed.pop("verdict", {}),
                profile_seed=seed,
            )
            if result and result.vetting_rows > 0 and not result.errors:
                l["spine_synced"] = True
                changed = True
                total_synced += 1
                log.info("  ✓ @%s synced", l["username"])
            else:
                errs = result.errors if result else ["spine unreachable"]
                log.warning("  ✗ @%s failed: %s", l["username"], errs)

        if changed:
            jsonl.write_text(
                "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
                encoding="utf-8",
            )

    log.info("Done. %d labels synced.", total_synced)
    return 0


if __name__ == "__main__":
    sys.exit(main())
