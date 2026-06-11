"""
quality_gate.py — Universal-disqualifier filter for the central agency database.

Runs after the LLM analyzer and before the row is written. Returns a decision
indicating whether the creator should be pushed to the central spine database
(Supabase `profiles` + `creator_vetting`) or held back locally.

The split this enforces:
  - Universal disqualifiers (this module's job): adult content, MLM,
    pseudo-medical claims, anti-vax, hate speech, political extremism. A creator
    tripping any of these is wrong for the whole agency, not just one client.
    They DO NOT enter the central DB.
  - Brand-fit mismatches (NOT this module's job): wrong niche, wrong age,
    wrong demographic. These are per-client and the creator MAY still be a fit
    for a different brand. They DO enter the central DB; the per-client vetting
    decision is recorded separately.

All patterns and thresholds come from config.yaml -> quality_gate. Editing this
module to change what gets blocked is the wrong move — edit the config.

Returns a dict with three keys:
    gate_decision : "passes" | "rejected_<category>"
    gate_reason   : human-readable explanation
    push_to_spine : bool
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Negation phrases that, if they appear shortly before a pattern match, mean
# the pattern is being described as NOT present rather than detected.
# Keeping the list strict — false negatives here would let real disqualifiers
# through. Lowercased and matched as substrings.
_NEGATION_LOOKBACK_CHARS = 50
_NEGATION_PHRASES = (
    "no ", "not ", "without ", "cannot ", "can't ", "didn't ", "doesn't ",
    "isn't ", "wasn't ", "free of ", "rule out", "ruled out",
    "verify for", "verify any", "assess for", "assess any", "assess authenticity",
    "no evidence of", "no detected", "no obvious", "no visible", "no detectable",
    "no clear", "no apparent", "lacks ", "lacking ", "absent of", "passes ",
    "passed ", "clean ", "screened ", "screening", "rules out",
    "not detected", "not present", "not visible", "no signs of", "no signals of",
    "cannot rule", "could not verify", "could not assess",
)


def _text_haystack(creator: dict) -> str:
    """
    Build the lowercased search blob.

    Scan only fields where Claude lists *detected* issues — not fields where
    Claude describes what was *checked but not found*. `llm_concerns` is the
    discrete-finding field; `llm_reasoning` and `llm_content_summary` discuss
    both presence and absence and trigger many false positives ("no MLM
    detected", "passes hate-speech screening"). `flags` is structured pre-LLM
    output and safe to include.
    """
    parts = []
    for key in ("llm_concerns", "flags"):
        val = creator.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def _is_negated(haystack: str, match_pos: int) -> bool:
    """Check if the substring at match_pos is preceded by a negation phrase."""
    start = max(0, match_pos - _NEGATION_LOOKBACK_CHARS)
    window = haystack[start:match_pos]
    return any(neg in window for neg in _NEGATION_PHRASES)


def _scan_patterns(haystack: str, pattern_dict: dict) -> tuple[Optional[str], list[str]]:
    """
    Walk every category's pattern list, return the first non-negated hit.

    Returns (category, matched_patterns) on hit, (None, []) on clean.
    Stops at the first category that fires — order in config matters for
    reason-attribution but not for the boolean outcome.

    Negation-aware: a substring match preceded by phrases like "cannot
    assess", "no detected", "without", "rule out" is treated as a description
    of an absence (Claude saying the thing is NOT there) rather than a finding.
    """
    if not haystack or not pattern_dict:
        return None, []

    for category, patterns in pattern_dict.items():
        hits = []
        for pattern in patterns or []:
            pattern_lc = str(pattern).lower().strip()
            if not pattern_lc:
                continue
            # Find each occurrence and check it individually for negation —
            # the same pattern may appear multiple times with mixed context.
            start = 0
            while True:
                pos = haystack.find(pattern_lc, start)
                if pos == -1:
                    break
                if not _is_negated(haystack, pos):
                    hits.append(pattern)
                    break  # one positive occurrence is enough for this pattern
                start = pos + 1
        if hits:
            return category, hits

    return None, []


def evaluate(creator: dict, config: dict) -> dict:
    """
    Decide whether this creator passes the universal quality gate.

    `creator` should be the merged dict produced by the pipeline — engagement
    fields, LLM fields, analyzer fields all flat-keyed at top level.

    `config` is the full pipeline config; we read config["quality_gate"].

    Always returns a dict. If the gate is disabled in config, returns
    passes=True with a reason indicating the gate was skipped.
    """
    gate_cfg = (config or {}).get("quality_gate", {}) or {}

    if not gate_cfg.get("enabled", True):
        return {
            "gate_decision": "passes",
            "gate_reason": "Quality gate disabled in config",
            "push_to_spine": True,
        }

    # 1. Hard recommendation exclusions (default: empty list — see config)
    rec = (creator.get("llm_recommendation") or "").strip().lower()
    exclude_recs = [r.lower() for r in gate_cfg.get("exclude_recommendations", [])]
    if rec and rec in exclude_recs:
        return {
            "gate_decision": "rejected_llm_recommendation",
            "gate_reason": f"llm_recommendation='{rec}' is in the universal-reject list",
            "push_to_spine": False,
        }

    # 2. Critical brand-safety floor — Claude saw something bad we didn't list
    safety_floor = gate_cfg.get("min_brand_safety_floor")
    brand_safety = creator.get("llm_brand_safety")
    if (
        safety_floor is not None
        and isinstance(brand_safety, (int, float))
        and brand_safety < safety_floor
    ):
        return {
            "gate_decision": "rejected_brand_safety_critical",
            "gate_reason": (
                f"llm_brand_safety={brand_safety} below universal floor of {safety_floor} — "
                "Claude flagged a serious concern we should not push to the central DB"
            ),
            "push_to_spine": False,
        }

    # 3. Keyword pattern scan across all the text signals
    haystack = _text_haystack(creator)
    category, hits = _scan_patterns(haystack, gate_cfg.get("universal_reject_patterns", {}))
    if category:
        sample = ", ".join(hits[:3])
        return {
            "gate_decision": f"rejected_{category}",
            "gate_reason": (
                f"Universal disqualifier ({category.replace('_', ' ')}) matched in creator signals: {sample}"
            ),
            "push_to_spine": False,
        }

    # 4. Multi-signal floor — catches creators that look bad on every axis
    multi_cfg = gate_cfg.get("multi_signal_floor", {}) or {}
    if multi_cfg.get("enabled"):
        safety_below = multi_cfg.get("brand_safety_below")
        require_d = multi_cfg.get("require_tier_d", False)
        require_no = multi_cfg.get("require_no_recommendation", False)
        tier = str(creator.get("tier") or "").upper()
        conditions = []
        if safety_below is not None and isinstance(brand_safety, (int, float)):
            conditions.append(brand_safety < safety_below)
        if require_d:
            conditions.append(tier == "D")
        if require_no:
            conditions.append(rec == "no")
        if conditions and all(conditions):
            return {
                "gate_decision": "rejected_multi_signal_floor",
                "gate_reason": (
                    f"Failed multi-signal floor: brand_safety={brand_safety}, "
                    f"tier={tier}, recommendation={rec} — unanimously poor"
                ),
                "push_to_spine": False,
            }

    return {
        "gate_decision": "passes",
        "gate_reason": (
            "No universal disqualifiers detected. Brand-fit mismatches are client-specific "
            "and recorded in vetting decision, not blocked at the gate."
        ),
        "push_to_spine": True,
    }
