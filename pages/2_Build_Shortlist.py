"""
pages/2_Build_Shortlist.py — Filter an enriched CSV against a client's brief.

Load the most recent enriched CSV from the Vet Creators run, pick which
client this shortlist is for, and have Claude read every creator's profile,
weigh it against the client's brand context + scoring style + the global
Augmentum vetting rubric, and return approved / soft-reject / hard-reject
groups with per-creator reasoning. Download the filtered shortlist as CSV
or JSON.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd

# How many creators to send to Claude in one filtering request. Smaller chunks
# keep each response well under the 8000-token output limit and let progress
# update mid-filter; larger chunks save API calls but risk truncation.
_CHUNK_SIZE = 25

# Generous output budget per chunk — covers ~25 creators with reasoning, soft
# rejects, hard rejects, and summary, with plenty of headroom.
_MAX_TOKENS_PER_CHUNK = 8000

# ── Paths and imports ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui_styles import inject as inject_styles
from src.ui_labels import (
    tier_label, gate_label, llm_recommendation_label,
    flags_label, friendly_column, ESSENTIAL_COLUMNS,
)

st.set_page_config(page_title="Build Shortlist — CreatorVetter", layout="wide")
inject_styles()

# ── Page header ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="page-header">
  <div class="page-title">Build Shortlist</div>
  <div class="page-subtitle">
    Take the most recent enriched CSV from a Vet Creators run and have Claude
    filter it against a specific client's brief. Approved, soft-reject, and
    hard-reject groups come back with per-creator reasoning, ready to download
    as the final shortlist for the campaign manager.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Pre-flight checks ────────────────────────────────────────────────────────

api_key = os.getenv("ANTHROPIC_API_KEY", "")
if not api_key:
    st.error(
        "**ANTHROPIC_API_KEY is not set.** Claude is what does the filtering on "
        "this page — without an Anthropic API key the page cannot do anything. "
        "Add the key to your `.env` file at the project root "
        "(`ANTHROPIC_API_KEY=sk-ant-...`) and refresh the page."
    )
    st.stop()

if "current_csv" not in st.session_state:
    st.session_state.current_csv = None
if "filtered_results" not in st.session_state:
    st.session_state.filtered_results = None

# ── LLM client ──────────────────────────────────────────────────────────────

try:
    from src.llm_client import AnthropicClient
except ImportError as e:
    st.error(f"Could not import the Claude client: {e}")
    st.stop()


@st.cache_resource
def _get_client():
    model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    return AnthropicClient(model=model)


try:
    llm = _get_client()
except Exception as e:
    st.error(f"Failed to initialise the Claude client: {e}")
    st.stop()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_enriched_csv():
    """Find and load the most recent enriched CSV from output/."""
    output_dir = PROJECT_ROOT / "output"
    if not output_dir.exists():
        return None, None
    enriched_files = sorted(
        output_dir.glob("enriched_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not enriched_files:
        return None, None
    latest = enriched_files[0]
    try:
        df = pd.read_csv(latest)
        return df, latest
    except Exception as e:
        st.error(
            f"Found `{latest.name}` but could not read it: {e}. Try running "
            f"the Vet Creators pipeline again."
        )
        return None, latest


def _load_expertise() -> str:
    path = PROJECT_ROOT / "knowledge" / "expertise.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _list_available_clients() -> list[str]:
    clients_dir = PROJECT_ROOT / "knowledge" / "clients"
    if not clients_dir.exists():
        return []
    return sorted([d.name for d in clients_dir.iterdir() if d.is_dir()])


def _get_client_profile(client_name: str) -> dict:
    client_dir = PROJECT_ROOT / "knowledge" / "clients" / client_name
    if not client_dir.exists():
        return {}
    profile = {}
    for fname, key in (("my_style.md", "style"),
                       ("brief.md", "brief"),
                       ("good_examples.md", "examples")):
        path = client_dir / fname
        if path.exists():
            profile[key] = path.read_text(encoding="utf-8")
    # profile.yaml — read brand_context for the brief if no brief.md
    yaml_path = client_dir / "profile.yaml"
    if yaml_path.exists() and "brief" not in profile:
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            brief_parts = []
            if data.get("brand_context"):
                brief_parts.append(f"BRAND CONTEXT:\n{data['brand_context']}")
            if data.get("target_niches"):
                brief_parts.append(
                    "TARGET NICHES:\n" + ", ".join(data["target_niches"])
                )
            if data.get("scoring_notes"):
                brief_parts.append(f"SPECIAL SCORING NOTES:\n{data['scoring_notes']}")
            if brief_parts:
                profile["brief"] = "\n\n".join(brief_parts)
        except Exception:
            pass
    return profile


def _build_creator_summary(row) -> dict:
    """Compact per-creator summary sent to Claude. ~12 fields per creator."""
    return {
        "username": row.get("ig_username", row.get("username", "unknown")),
        "followers": int(row.get("followers", 0) or 0),
        "verified": bool(row.get("ig_verified", False)),
        "private": bool(row.get("ig_private", False)),
        "engagement_rate": float(row.get("avg_engagement_rate", 0) or 0),
        "primary_niche": str(row.get("primary_niche", "Unknown")),
        "secondary_niche": str(row.get("secondary_niche", "")),
        "niche_confidence": float(row.get("niche_confidence", 0) or 0),
        "production_quality": str(row.get("production_quality", "unknown")),
        "brand_fit_score": float(row.get("brand_fit_score", 0) or 0),
        "tier": str(row.get("tier", "Unknown")),
    }


def _system_prompt(expertise: str) -> str:
    return f"""You are a creator vetting agent for an influencer marketing agency.

Your job is to filter and rank creators from an enriched CSV against a client's brief.

VETTING RUBRIC (apply these standards to every creator):

{expertise}

---

INSTRUCTIONS:
1. Review the client brief below.
2. Analyse each creator against the rubric + the client's specific scoring style.
3. Apply hard rejects, soft rejects, and flag-for-review judgments.
4. Rank remaining creators by brand fit and quality.
5. Return JSON with filtered creators and reasoning.

Output exactly this JSON structure (no markdown, no backticks, no commentary):
{{
  "approved": [
    {{"username": "...", "fit_score": 0-100, "reasoning": "1-2 sentences max", "red_flags": []}}
  ],
  "soft_rejects": [
    {{"username": "...", "reason": "1 sentence", "can_override": true/false}}
  ],
  "hard_rejects": [
    {{"username": "...", "reason": "1 sentence"}}
  ],
  "summary": "1-2 sentences on the batch overall"
}}

Keep reasoning concise — one to two sentences per creator. Long explanations waste tokens and risk response truncation.
"""


def _parse_json_lenient(text: str) -> Optional[dict]:
    """
    Robust JSON extraction.

    Tries: direct parse → strip code fences → first {...} block →
    fall back to None. Tolerates Claude wrapping the response in markdown.
    """
    text = (text or "").strip()
    if not text:
        return None

    # Strip code fences if present
    if "```" in text:
        parts = text.split("```")
        # Pick the first fenced block that looks like JSON
        for p in parts:
            p = p.lstrip()
            if p.startswith("json"):
                p = p[4:].lstrip()
            if p.startswith("{"):
                text = p
                break

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract the first complete top-level {...}
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _run_one_chunk(
    chunk: list[dict], brief_context: str, expertise: str
) -> tuple[Optional[dict], str]:
    """Send one chunk of creator summaries to Claude. Returns (parsed_json, raw_text)."""
    user_message = (
        f"CLIENT BRIEF:\n{brief_context}\n\n"
        f"CREATORS TO EVALUATE (n={len(chunk)}):\n{json.dumps(chunk, indent=2)}\n\n"
        f"Filter and rank these creators. Only include creators that pass hard "
        f"reject checks. Be concise — short reasoning per creator."
    )
    try:
        response = llm.chat(
            messages=[{"role": "user", "content": user_message}],
            system=_system_prompt(expertise),
            max_tokens=_MAX_TOKENS_PER_CHUNK,
        )
    except Exception as e:
        return None, f"Error calling Claude: {e}"

    raw = response.get("content", "")
    return _parse_json_lenient(raw), raw


def _filter_creators_with_claude(
    df: pd.DataFrame, brief_context: str, expertise: str
) -> tuple[list[dict], dict, list[str]]:
    """
    Send creator summaries to Claude in chunks, merge results.

    Returns:
      approved_rows  — list of full DataFrame row dicts for creators Claude approved
      merged_result  — dict with combined approved/soft_rejects/hard_rejects/summary
      warnings       — list of per-chunk problems (e.g. JSON parse failures)
    """
    # Build all summaries up front
    summaries = [_build_creator_summary(row) for _, row in df.iterrows()]

    # Chunk the work
    chunks = [
        summaries[i : i + _CHUNK_SIZE] for i in range(0, len(summaries), _CHUNK_SIZE)
    ]

    merged_approved: list[dict] = []
    merged_soft: list[dict] = []
    merged_hard: list[dict] = []
    summaries_text: list[str] = []
    warnings: list[str] = []

    progress_placeholder = st.empty()
    for chunk_idx, chunk in enumerate(chunks, start=1):
        progress_placeholder.info(
            f"Filtering batch {chunk_idx} of {len(chunks)} "
            f"({len(chunk)} creators in this batch)…"
        )
        parsed, raw = _run_one_chunk(chunk, brief_context, expertise)
        if parsed is None:
            warnings.append(
                f"Batch {chunk_idx}: Claude returned unparseable output (likely "
                f"truncated). {len(chunk)} creators in this batch were skipped. "
                f"Raw output snippet: {raw[:200]}…"
            )
            continue
        merged_approved.extend(parsed.get("approved", []) or [])
        merged_soft.extend(parsed.get("soft_rejects", []) or [])
        merged_hard.extend(parsed.get("hard_rejects", []) or [])
        if parsed.get("summary"):
            summaries_text.append(f"Batch {chunk_idx}: {parsed['summary']}")

    progress_placeholder.empty()

    # Resolve approved usernames back to full DataFrame rows
    approved_usernames = {
        c.get("username", "").lstrip("@").lower()
        for c in merged_approved
        if c.get("username")
    }
    approved_creators = []
    for _, row in df.iterrows():
        username = (
            row.get("ig_username")
            or row.get("Username")
            or row.get("username")
            or ""
        )
        username = str(username).lstrip("@").lower()
        if username in approved_usernames:
            approved_creators.append(row.to_dict())

    merged_result = {
        "approved": merged_approved,
        "soft_rejects": merged_soft,
        "hard_rejects": merged_hard,
        "summary": " | ".join(summaries_text) if summaries_text else "",
        "batches_processed": len(chunks),
        "batches_with_warnings": len(warnings),
    }
    return approved_creators, merged_result, warnings


# ── Step 1: Load enriched CSV ───────────────────────────────────────────────

st.markdown("""
<div class="step-header">
  <div class="step-number">1</div>
  <div class="step-label">Load the most recent enriched CSV</div>
</div>
<div class="step-desc">
  The page auto-loads the newest <code>enriched_*.csv</code> from the
  <code>output/</code> folder. If you just finished a vetting run, click
  <strong>Reload</strong> to pick it up.
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([3, 1])
with col1:
    auto_csv, csv_path = _load_enriched_csv()
    if auto_csv is not None:
        st.session_state.current_csv = auto_csv
        st.success(
            f"Loaded `{csv_path.name}` — {len(auto_csv):,} creators ready to filter."
        )
    else:
        st.warning(
            "No enriched CSV found in `output/`. Run the **Vet Creators** "
            "page first to produce one."
        )

with col2:
    if st.button(
        "Reload from disk",
        use_container_width=True,
        help="Force re-read the newest enriched CSV from output/",
    ):
        st.rerun()

if st.session_state.current_csv is None:
    st.info(
        "Use the **Vet Creators** page in the sidebar to generate an "
        "enriched CSV first."
    )
    st.stop()

df = st.session_state.current_csv

# ── Step 2: Pick a client ────────────────────────────────────────────────────

st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="step-header">
  <div class="step-number">2</div>
  <div class="step-label">Pick which client this shortlist is for</div>
</div>
<div class="step-desc">
  Trained clients are loaded from <code>knowledge/clients/</code>. Their
  brand context, target niches, and personal scoring style are injected into
  Claude's prompt. If you don't have a trained client yet, you can type a
  one-off brief instead — it won't be saved.
</div>
""", unsafe_allow_html=True)

available_clients = _list_available_clients()
active_client = st.session_state.get("active_client")

brief_source = st.radio(
    "How do you want to define the client brief?",
    options=[
        "Use a client we've trained Claude on (loads their brand context + scoring style)",
        "Type a one-off brief now (won't be saved)",
    ],
    horizontal=False,
    label_visibility="visible",
)

brief_context = ""

if brief_source.startswith("Use a client"):
    if not available_clients:
        st.warning(
            "No trained clients yet. Either type a one-off brief above or "
            "go to the **Train Clients** page to set one up."
        )
        st.stop()

    default_idx = 0
    if active_client in available_clients:
        default_idx = available_clients.index(active_client)

    selected_client = st.selectbox(
        "Which client are we filtering for?",
        options=available_clients,
        index=default_idx,
        help=(
            "Defaults to the active client in the sidebar. Pick a different "
            "one here if this shortlist is for a different campaign."
        ),
    )
    st.session_state["active_client"] = selected_client

    client_profile = _get_client_profile(selected_client)
    if not client_profile:
        st.warning(
            f"`{selected_client}` exists as a folder but has no training data. "
            f"Open the **Train Clients** page to fill in brand context and "
            f"scoring style."
        )
        st.stop()

    if "brief" in client_profile:
        with st.expander(f"View {selected_client}'s brand context and target niches", expanded=False):
            st.markdown(
                f'<div style="font-size:0.875rem;color:#1D1D1F;line-height:1.65;white-space:pre-wrap;">'
                f'{client_profile["brief"]}</div>',
                unsafe_allow_html=True,
            )
    if "style" in client_profile:
        with st.expander(f"View {selected_client}'s personal scoring style", expanded=False):
            st.markdown(
                f'<div style="font-size:0.875rem;color:#1D1D1F;line-height:1.65;white-space:pre-wrap;">'
                f'{client_profile["style"]}</div>',
                unsafe_allow_html=True,
            )

    brief_context = client_profile.get("brief", "")
    if "style" in client_profile:
        brief_context += f"\n\nSCORING STYLE:\n{client_profile['style']}"

else:
    brief_context = st.text_area(
        "Describe the campaign brief and your scoring requirements in plain English",
        placeholder=(
            "Example: Looking for UK-based women 35+ in the menopause, sleep, "
            "and recovery niches for a premium wellness brand. Engaged audiences "
            "with disposable income. No deal-led creators or product-review-only "
            "accounts. 5k–150k followers, 1.5%+ engagement rate."
        ),
        height=160,
    )

if not brief_context.strip():
    st.info("Provide a brief above (or pick a trained client) to continue.")
    st.stop()

# ── Step 3: Filter ───────────────────────────────────────────────────────────

st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="step-header">
  <div class="step-number">3</div>
  <div class="step-label">Filter and rank the creators with Claude</div>
</div>
<div class="step-desc">
  Claude reads every creator's summary fields and the brief above, then groups
  them into approved, soft-reject (can be overridden), and hard-reject
  (cannot). The longer the CSV, the longer this takes — typically 30–90 seconds.
</div>
""", unsafe_allow_html=True)

active_client_label = (
    st.session_state.get("active_client") if brief_source.startswith("Use a client")
    else "this one-off brief"
)

if st.button(
    f"Filter all {len(df):,} creators against {active_client_label}'s brief",
    type="primary",
    use_container_width=True,
):
    expertise = _load_expertise()
    n_chunks = max(1, (len(df) + _CHUNK_SIZE - 1) // _CHUNK_SIZE)
    with st.spinner(
        f"Claude is reading {len(df):,} creator summaries in {n_chunks} batch"
        f"{'es' if n_chunks != 1 else ''} of up to {_CHUNK_SIZE} and weighing "
        f"each against the brief…"
    ):
        approved_creators, merged_analysis, warnings = _filter_creators_with_claude(
            df, brief_context, expertise
        )
    st.session_state.filtered_results = {
        "creators": approved_creators,
        "analysis": merged_analysis,
        "warnings": warnings,
        "timestamp": datetime.now().isoformat(),
        "client_label": active_client_label,
    }
    st.success(
        f"Filtering complete — {len(approved_creators)} creators approved for "
        f"{active_client_label} across "
        f"{merged_analysis.get('batches_processed', 1)} batch"
        f"{'es' if merged_analysis.get('batches_processed', 1) != 1 else ''}."
    )
    if warnings:
        for w in warnings:
            st.warning(w)

    with st.expander("View Claude's full reasoning (approved / soft-reject / hard-reject)", expanded=True):
        analysis = st.session_state.filtered_results["analysis"]

        if analysis.get("approved"):
            st.markdown("### Approved creators (recommended for shortlist)")
            approved_data = [
                {
                    "Username": f"@{c.get('username', '')}",
                    "Fit score": f"{c.get('fit_score', '—')}/100",
                    "Why Claude approved": (
                        c.get("reasoning", "")[:200]
                        + ("…" if len(c.get("reasoning", "")) > 200 else "")
                    ),
                }
                for c in analysis["approved"]
            ]
            st.dataframe(pd.DataFrame(approved_data), use_container_width=True)

        if analysis.get("soft_rejects"):
            st.markdown("### Soft rejects (campaign manager can override)")
            soft_data = [
                {
                    "Username": f"@{c.get('username', '')}",
                    "Reason for soft reject": c.get("reason", ""),
                    "Can be overridden": "Yes" if c.get("can_override") else "No",
                }
                for c in analysis["soft_rejects"]
            ]
            st.dataframe(pd.DataFrame(soft_data), use_container_width=True)

        if analysis.get("hard_rejects"):
            st.markdown("### Hard rejects (cannot enter the shortlist)")
            hard_data = [
                {
                    "Username": f"@{c.get('username', '')}",
                    "Reason for hard reject": c.get("reason", ""),
                }
                for c in analysis["hard_rejects"]
            ]
            st.dataframe(pd.DataFrame(hard_data), use_container_width=True)

        if analysis.get("summary"):
            st.markdown("### Claude's overall summary across all batches")
            st.info(analysis["summary"])

# ── Step 4: Download ─────────────────────────────────────────────────────────

if st.session_state.filtered_results:
    st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="step-header">
      <div class="step-number">4</div>
      <div class="step-label">Download the shortlist (approved) or the full vetted list (all creators with pass/fail)</div>
    </div>
    <div class="step-desc">
      Two downloads on offer. The <strong>shortlist</strong> is just the
      creators Claude approved, with every column from the enriched CSV.
      The <strong>full vetted list</strong> is every creator from the original
      CSV plus three new columns — <code>vetting_status</code>
      (Approved / Soft reject / Hard reject / Not evaluated),
      <code>vetting_reason</code>, and <code>vetting_fit_score</code> — so the
      CM can see why each one passed or failed in a single file.
    </div>
    """, unsafe_allow_html=True)

    filtered_df = pd.DataFrame(st.session_state.filtered_results["creators"])

    if not filtered_df.empty:
        # Apply plain-language transforms for display only
        preview_cols = [c for c in ESSENTIAL_COLUMNS if c in filtered_df.columns]
        preview = filtered_df[preview_cols].copy()
        if "tier" in preview.columns:
            preview["tier"] = preview["tier"].apply(tier_label)
        if "llm_recommendation" in preview.columns:
            preview["llm_recommendation"] = preview["llm_recommendation"].apply(llm_recommendation_label)
        if "gate_decision" in preview.columns:
            preview["gate_decision"] = preview["gate_decision"].apply(gate_label)
        preview.columns = [friendly_column(c) for c in preview.columns]

        st.dataframe(preview, use_container_width=True)

        with st.expander("Show every column in the shortlist (full enriched data)", expanded=False):
            full_preview = filtered_df.copy()
            if "tier" in full_preview.columns:
                full_preview["tier_display"] = full_preview["tier"].apply(tier_label)
            if "gate_decision" in full_preview.columns:
                full_preview["gate_decision_display"] = full_preview["gate_decision"].apply(gate_label)
            if "flags" in full_preview.columns:
                full_preview["flags_display"] = full_preview["flags"].apply(flags_label)
            st.dataframe(full_preview, use_container_width=True)
    else:
        st.warning(
            "Claude approved zero creators for this brief. The full reasoning is "
            "in the expander above — usually this means the CSV is too far off-niche, "
            "or the brief is too strict. Try loosening one constraint at a time."
        )

    # Build a "full vetted list" — original CSV + per-creator vetting status
    # from Claude. This is what the CM actually wants to audit: every row
    # they submitted with a clear approved / soft-reject / hard-reject /
    # not-evaluated label and Claude's one-line reason. Not-evaluated covers
    # the chunk-truncation edge case where Claude's JSON failed to parse.
    analysis = st.session_state.filtered_results["analysis"]
    _approved_lookup = {
        str(a.get("username", "")).lstrip("@").lower(): a
        for a in (analysis.get("approved") or [])
        if a.get("username")
    }
    _soft_lookup = {
        str(a.get("username", "")).lstrip("@").lower(): a
        for a in (analysis.get("soft_rejects") or [])
        if a.get("username")
    }
    _hard_lookup = {
        str(a.get("username", "")).lstrip("@").lower(): a
        for a in (analysis.get("hard_rejects") or [])
        if a.get("username")
    }

    def _vet_row(row):
        handle = str(
            row.get("ig_username")
            or row.get("Username")
            or row.get("username")
            or ""
        ).lstrip("@").lower()
        if handle in _approved_lookup:
            a = _approved_lookup[handle]
            return pd.Series({
                "vetting_status": "Approved",
                "vetting_reason": str(a.get("reasoning", "")),
                "vetting_fit_score": a.get("fit_score", ""),
            })
        if handle in _soft_lookup:
            return pd.Series({
                "vetting_status": "Soft reject",
                "vetting_reason": str(_soft_lookup[handle].get("reason", "")),
                "vetting_fit_score": "",
            })
        if handle in _hard_lookup:
            return pd.Series({
                "vetting_status": "Hard reject",
                "vetting_reason": str(_hard_lookup[handle].get("reason", "")),
                "vetting_fit_score": "",
            })
        return pd.Series({
            "vetting_status": "Not evaluated",
            "vetting_reason": "",
            "vetting_fit_score": "",
        })

    _vet_cols = df.apply(_vet_row, axis=1)
    full_vetted_df = pd.concat([df.reset_index(drop=True), _vet_cols.reset_index(drop=True)], axis=1)
    _status_counts = full_vetted_df["vetting_status"].value_counts().to_dict()
    _summary_bits = " · ".join(
        f"{k.lower()}: {_status_counts.get(k, 0)}"
        for k in ("Approved", "Soft reject", "Hard reject", "Not evaluated")
    )

    dl_col1, dl_col2, dl_col3 = st.columns(3)
    with dl_col1:
        csv_bytes = filtered_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"Shortlist CSV (approved only — {len(filtered_df)})",
            data=csv_bytes,
            file_name=f"shortlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            help=(
                "Just the creators Claude approved for this client. "
                "Every column from the enriched CSV is preserved."
            ),
        )
    with dl_col2:
        json_bytes = filtered_df.to_json(orient="records").encode("utf-8")
        st.download_button(
            label=f"Shortlist JSON (approved only — {len(filtered_df)})",
            data=json_bytes,
            file_name=f"shortlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
            help="Same data as the shortlist CSV but as JSON records.",
        )
    with dl_col3:
        full_csv_bytes = full_vetted_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"Full vetted list ({len(full_vetted_df)} with pass/fail)",
            data=full_csv_bytes,
            file_name=f"full_vetted_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary",
            help=(
                "Every creator from the original CSV with a vetting_status column "
                "(Approved / Soft reject / Hard reject / Not evaluated) plus "
                "Claude's one-line reason and fit score. This is the file to "
                "send the campaign manager for sign-off."
            ),
        )
    st.caption(f"Full vetted list breakdown — {_summary_bits}")

    st.markdown('<div style="height:1rem;"></div>', unsafe_allow_html=True)
    if st.button(
        "Clear filtered results and start a new shortlist",
        type="secondary",
        use_container_width=False,
    ):
        st.session_state.filtered_results = None
        st.session_state.current_csv = None
        st.rerun()

# ── Navigation footer ───────────────────────────────────────────────────────

st.markdown('<div style="height:2.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="border-top:1px solid #E5E5EA;padding-top:1.25rem;">
  <span style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Go to</span>
</div>
""", unsafe_allow_html=True)
_nc1, _nc2 = st.columns(2)
with _nc1:
    st.page_link(
        "pages/1_Vet_Creators.py",
        label="Vet Creators — score a new CSV before filtering",
        icon="▶",
    )
with _nc2:
    st.page_link(
        "pages/3_Train_Clients.py",
        label="Train Clients — refine brand context or scoring style",
        icon="✏️",
    )
