"""
corrections.py — Persist human corrections so the next run learns from them.

When a pod member marks a vetting decision as wrong, two things happen:

1. The correction is appended to the client's `corrections.md` — which
   `_load_calibration()` already injects into every future judgment prompt
   for that client, so the model sees exactly where its judgment diverged
   from the human's.
2. The creator's cached verdict for that campaign is invalidated, so the
   next run re-judges them fresh with the correction in context.

This closes the feedback loop: correct a call once, and every later run
inherits the lesson.
"""

import logging
from datetime import date
from pathlib import Path

from .vetting_cache import VettingCache

logger = logging.getLogger(__name__)


def record_correction(
    client_dir: Path,
    username: str,
    campaign: str,
    our_call: str,
    correct_call: str,
    reason: str,
) -> Path:
    """
    Append one correction to <client_dir>/corrections.md and invalidate the
    creator's cached verdict for the campaign. Returns the corrections path.
    """
    client_dir = Path(client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)
    path = client_dir / "corrections.md"

    if not path.exists():
        path.write_text(
            "# Past corrections\n\n"
            "Human overrides of vetting decisions. Each entry is injected "
            "into future judgment prompts for this client — explain the WHY "
            "so the model can generalise it.\n",
            encoding="utf-8",
        )

    entry = (
        f"\n### @{username} — {date.today().isoformat()} ({campaign} campaign)\n"
        f"- Our call: {our_call}\n"
        f"- Correct call: {correct_call}\n"
        f"- Why: {reason.strip()}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)

    try:
        cache = VettingCache(seed_dir=None)
        cache.delete(username, campaign)
        cache.close()
    except Exception as e:
        logger.warning("Could not invalidate cache for @%s: %s", username, e)

    logger.info("Correction recorded for @%s → %s", username, path)
    return path
