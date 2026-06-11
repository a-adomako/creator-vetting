"""
calibration.py — Candidate loading + label storage for the Calibration Deck.

The deck shows a human profiles Claude has already judged for a campaign and
asks: would YOU approve this creator for this client? Each swipe becomes:

  1. A line in knowledge/clients/<client>/calibration_labels.jsonl —
     the machine-readable label log (agreement stats, future training).
  2. An entry in knowledge/clients/<client>/calibration_labels.md —
     human-readable, injected into every future judgment prompt for the
     client (4th calibration file, alongside my_style / corrections /
     good_examples).
  3. Best-effort: a human_approved / human_rejected row in the spine's
     creator_vetting table (src/spine.record_human_decision).

Candidates are sorted borderline-first (fit score nearest 55): uncertain
cases are where a human label moves the model most.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CAMPAIGN_RUNS_DIR = PROJECT_ROOT / "output" / "campaigns"


def load_candidates(campaign_name: str, client_dir: Path) -> list[dict]:
    """
    All judged creators for a campaign across every run folder, newest
    record per username, minus anyone already labeled. Borderline-first.
    """
    labeled = {lbl["username"] for lbl in load_labels(client_dir)
               if lbl.get("campaign") == campaign_name}

    by_user: dict[str, dict] = {}
    for pf in CAMPAIGN_RUNS_DIR.glob("*/profiles/*.json"):
        try:
            rec = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("campaign") != campaign_name or not rec.get("verdict"):
            continue
        u = rec.get("username", "")
        if not u or u in labeled:
            continue
        prev = by_user.get(u)
        if prev is None or str(rec.get("vetted_at", "")) > str(prev.get("vetted_at", "")):
            by_user[u] = rec

    def borderline_key(rec):
        fit = (rec.get("verdict") or {}).get("campaign_fit_score")
        return abs((fit if fit is not None else 55) - 55)

    return sorted(by_user.values(), key=borderline_key)


def load_labels(client_dir: Path) -> list[dict]:
    path = Path(client_dir) / "calibration_labels.jsonl"
    if not path.exists():
        return []
    labels = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                labels.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return labels


def agreement_stats(labels: list[dict], campaign: Optional[str] = None) -> dict:
    """Human-vs-Claude agreement over decisive labels (skips needs_review)."""
    relevant = [
        l for l in labels
        if (campaign is None or l.get("campaign") == campaign)
        and l.get("claude") in ("approve", "reject")
    ]
    agreed = sum(1 for l in relevant if l["human"] == l["claude"])
    return {
        "labeled": len([l for l in labels
                        if campaign is None or l.get("campaign") == campaign]),
        "decisive": len(relevant),
        "agreed": agreed,
        "rate": round(agreed / len(relevant) * 100) if relevant else None,
    }


def record_label(
    client_dir: Path,
    campaign: str,
    record: dict,
    human_call: str,          # "approve" | "reject"
    why: str,
    reviewer: str,
) -> dict:
    """Persist one swipe locally (jsonl + injected markdown). Returns the label."""
    client_dir = Path(client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)
    verdict = record.get("verdict") or {}
    username = record.get("username", "")

    label = {
        "username": username,
        "campaign": campaign,
        "human": human_call,
        "claude": verdict.get("recommendation"),
        "fit_score": verdict.get("campaign_fit_score"),
        "why": why.strip(),
        "reviewer": reviewer.strip() or "unknown",
        "labeled_at": datetime.now().isoformat(timespec="seconds"),
    }

    # 1. Machine log
    with open(client_dir / "calibration_labels.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(label, ensure_ascii=False) + "\n")

    # 2. Prompt-injected markdown
    md_path = client_dir / "calibration_labels.md"
    if not md_path.exists():
        md_path.write_text(
            "# Human-labelled examples (calibration deck)\n\n"
            "Real accept/reject calls made by the team. Match this judgment.\n",
            encoding="utf-8",
        )
    agree_note = ""
    claude_call = verdict.get("recommendation")
    if claude_call in ("approve", "reject") and claude_call != human_call:
        agree_note = (
            f" (MODEL DISAGREED — it said {claude_call}; "
            f"the human call below is the correct one)"
        )
    entry = (
        f"\n### @{username} — HUMAN: {human_call.upper()}{agree_note}\n"
        f"- Niche: {verdict.get('primary_niche', '?')} | "
        f"fit score at the time: {verdict.get('campaign_fit_score', '?')}\n"
    )
    if why.strip():
        entry += f"- Why: {why.strip()}\n"
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(entry)

    return label
