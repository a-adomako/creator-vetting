"""
pages/4_Vet_for_Campaign.py — Campaign-aware vetting (v2 flow) in the UI.

Pick a campaign spec, upload a CSV of creators, run. Hard filters reject on
metrics for free; survivors get one structured Claude judgment call (bio +
captions + transcripts + sampled reel frames). Results land in three lean
tables: shortlist, rejected, review.

Same engine as `python run_campaign.py` — see src/vetter.py and
SYSTEM_CONTEXT.md §2a.
"""

import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import os

import pandas as pd
import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui_styles import inject as inject_styles

st.set_page_config(page_title="Vet for Campaign — CreatorVetter", layout="wide")
inject_styles()

CAMPAIGNS_DIR = PROJECT_ROOT / "campaigns"
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output" / "campaigns"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Page header ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="page-header">
  <div class="page-title">Vet for Campaign</div>
  <div class="page-subtitle">
    One motion: pick a campaign, upload a CSV of creators, get back a
    shortlist. Creators failing the campaign's measurable criteria (follower
    band, engagement floor, posting recency) are rejected instantly at no
    cost. Survivors get one AI judgment that reads their bio and captions,
    looks at frames sampled from their recent reels, and weighs them against
    the campaign brief. Song lyrics in reel audio are never attributed to
    the creator.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar settings ─────────────────────────────────────────────────────────

st.sidebar.markdown(
    '<div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.10em;'
    'text-transform:uppercase;color:#686b87;margin-bottom:8px;">'
    'Run settings</div>',
    unsafe_allow_html=True,
)

test_limit = st.sidebar.number_input(
    "Test-run limit (0 = vet everyone)",
    min_value=0, max_value=1000, value=0,
    help=(
        "Vet only the first N creators from the CSV. Useful for a quick "
        "sanity check of a new campaign spec before a full run."
    ),
)

use_cache = st.sidebar.checkbox(
    "Reuse verdicts from the last 6 months",
    value=True,
    help=(
        "Creators already judged for this campaign within the window are "
        "pulled from the local vetting cache instead of being re-fetched and "
        "re-judged — zero API cost. Untick to force fresh vetting for everyone."
    ),
)

st.sidebar.markdown(
    '<p style="font-size:0.75rem;color:#686b87;line-height:1.55;">'
    'Reels per creator, frames per reel, and image size are set in '
    '<strong style="color:#030937;">config/config.yaml → campaign_vetting</strong>. '
    'Hard-filter thresholds live in the campaign YAML itself.'
    '</p>',
    unsafe_allow_html=True,
)

# ── Step 1 — Pick a campaign ─────────────────────────────────────────────────

st.markdown("""
<div class="step-header">
  <span class="step-number">1</span>
  <span class="step-title">Choose the campaign</span>
</div>
""", unsafe_allow_html=True)

campaign_files = sorted(CAMPAIGNS_DIR.glob("*.yaml"))
if not campaign_files:
    st.warning(
        "No campaign specs found in campaigns/. Create one (see "
        "campaigns/thrivin.yaml in the repo for a worked example) and reload."
    )
    st.stop()

campaign_path = st.selectbox(
    "Campaign spec",
    options=campaign_files,
    format_func=lambda p: p.stem,
    help="Campaign specs are YAML files in the campaigns/ folder.",
)

spec_raw = yaml.safe_load(campaign_path.read_text(encoding="utf-8")) or {}
hf = spec_raw.get("hard_filters", {}) or {}

with st.expander("What this campaign checks", expanded=True):
    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown(f"**Brief**\n\n{spec_raw.get('brief', '_none_')}")
        if spec_raw.get("client_folder"):
            st.caption(
                f"Judgment is calibrated with knowledge/clients/"
                f"{spec_raw['client_folder']}/ (brand context + scoring style)."
            )
    with col2:
        st.markdown("**Instant filters (no AI cost)**")
        rows = []
        if hf.get("min_followers"):
            rows.append(f"- Followers below {hf['min_followers']:,} → rejected")
        if hf.get("vip_review_above"):
            rows.append(f"- Followers above {hf['vip_review_above']:,} → VIP review")
        if hf.get("min_engagement_pct") is not None:
            rows.append(f"- Engagement under {hf['min_engagement_pct']}% → rejected")
        if hf.get("max_days_since_last_post"):
            rows.append(f"- Quiet for {hf['max_days_since_last_post']}+ days → rejected")
        if hf.get("exclude_private", True):
            rows.append("- Private accounts → rejected")
        st.markdown("\n".join(rows) or "_none set_")

# ── Step 2 — Upload the CSV ──────────────────────────────────────────────────

st.markdown("""
<div class="step-header">
  <span class="step-number">2</span>
  <span class="step-title">Upload the creator CSV</span>
</div>
""", unsafe_allow_html=True)

uploaded = st.file_uploader(
    "CSV with a Profile URL and/or Username column",
    type=["csv"],
    help="Same format as Vet Creators — extra columns are fine and ignored.",
)

input_path = None
if uploaded is not None:
    input_path = INPUT_DIR / f"campaign_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    input_path.write_bytes(uploaded.getvalue())
    try:
        preview = pd.read_csv(input_path)
        st.caption(f"{len(preview)} rows loaded. First 5:")
        st.dataframe(preview.head(5), use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not read that CSV: {e}")
        input_path = None

# ── Step 3 — Run ─────────────────────────────────────────────────────────────

st.markdown("""
<div class="step-header">
  <span class="step-number">3</span>
  <span class="step-title">Run the vetting</span>
</div>
""", unsafe_allow_html=True)

missing_keys = [
    k for k in ("MODASH_API_KEY", "ANTHROPIC_API_KEY") if not os.getenv(k)
]
if missing_keys:
    st.error(
        f"Missing in .env: {', '.join(missing_keys)}. Both are required — "
        "this flow has no offline fallback."
    )

run_clicked = st.button(
    "Start campaign vetting (fetches profiles, samples reels, judges against the brief)",
    type="primary",
    disabled=(input_path is None or bool(missing_keys)),
)

if run_clicked and input_path is not None:
    from src.campaign import CampaignSpec
    from src.vetter import CampaignVetter

    campaign = CampaignSpec.load(campaign_path)
    progress_bar = st.progress(0.0)
    status_line = st.empty()

    def on_progress(done: int, total: int, username: str, label: str):
        progress_bar.progress(min(done / max(total, 1), 1.0))
        status_line.caption(label)

    try:
        with st.spinner("Setting up (loads the Whisper model on first run)…"):
            vetter = CampaignVetter(
                campaign,
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                use_cache=use_cache,
            )
        run_dir = vetter.run(
            str(input_path),
            limit=int(test_limit) or None,
            progress_callback=on_progress,
        )
        progress_bar.progress(1.0)
        status_line.empty()
        st.session_state["campaign_run_dir"] = str(run_dir)
        st.success(f"Run complete. Results saved to {run_dir}")
    except Exception as e:
        st.error(f"Run failed: {e}")

# ── Step 4 — Results ─────────────────────────────────────────────────────────

run_dir = st.session_state.get("campaign_run_dir")
if run_dir and Path(run_dir).exists():
    st.markdown("""
    <div class="step-header">
      <span class="step-number">4</span>
      <span class="step-title">Results</span>
    </div>
    """, unsafe_allow_html=True)

    run_dir = Path(run_dir)
    frames = {}
    for name in ("shortlist", "rejected", "review"):
        path = run_dir / f"{name}.csv"
        frames[name] = pd.read_csv(path) if path.exists() else pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    c1.metric("Shortlisted", len(frames["shortlist"]))
    c2.metric("Rejected", len(frames["rejected"]))
    c3.metric("Needs review", len(frames["review"]))

    tab_short, tab_rej, tab_rev = st.tabs(
        ["Shortlist", "Rejected", "Needs review"]
    )

    with tab_short:
        if frames["shortlist"].empty:
            st.caption("No creators approved in this run.")
        else:
            st.dataframe(frames["shortlist"], use_container_width=True, hide_index=True)
            st.download_button(
                "Download shortlist.csv",
                frames["shortlist"].to_csv(index=False).encode("utf-8"),
                file_name=f"{run_dir.name}_shortlist.csv",
                mime="text/csv",
            )

    with tab_rej:
        if frames["rejected"].empty:
            st.caption("No rejections in this run.")
        else:
            st.dataframe(frames["rejected"], use_container_width=True, hide_index=True)
            st.download_button(
                "Download rejected.csv",
                frames["rejected"].to_csv(index=False).encode("utf-8"),
                file_name=f"{run_dir.name}_rejected.csv",
                mime="text/csv",
            )

    with tab_rev:
        if frames["review"].empty:
            st.caption("Nothing needs a human look in this run.")
        else:
            st.dataframe(frames["review"], use_container_width=True, hide_index=True)
            st.download_button(
                "Download review.csv",
                frames["review"].to_csv(index=False).encode("utf-8"),
                file_name=f"{run_dir.name}_review.csv",
                mime="text/csv",
            )

    st.caption(
        f"Full per-creator evidence (verdict, transcripts, captions, metrics) "
        f"is in {run_dir / 'profiles'}/<username>.json."
    )

    # ── Correct a decision — closes the feedback loop ────────────────────
    judged = pd.concat(
        [frames["shortlist"], frames["rejected"], frames["review"]],
        ignore_index=True,
    )
    judged_users = (
        sorted(judged["ig_username"].dropna().unique().tolist())
        if not judged.empty else []
    )
    client_folder = spec_raw.get("client_folder")

    with st.expander("Correct a decision (teaches the next run)"):
        if not client_folder:
            st.info(
                "This campaign has no client_folder set, so corrections have "
                "nowhere to live. Add client_folder to the campaign YAML."
            )
        elif not judged_users:
            st.caption("No judged creators in this run yet.")
        else:
            st.caption(
                "Marking a call as wrong appends the reason to the client's "
                "corrections file — every future judgment for this client sees "
                "it — and clears the creator's cached verdict so the next run "
                "re-judges them fresh."
            )
            c_user = st.selectbox("Creator", judged_users, key="corr_user")
            c_call = st.radio(
                "What should the call have been?",
                ["approve", "reject", "needs human review"],
                horizontal=True,
                key="corr_call",
            )
            c_reason = st.text_area(
                "Why? (be specific — this teaches the model)",
                key="corr_reason",
                placeholder=(
                    "e.g. Her grid is premium-athleisure even though the reels "
                    "skew travel — the wardrobe is exactly the Oddmuse-adjacent "
                    "look the brief wants."
                ),
            )
            if st.button("Save correction", type="primary", key="corr_save"):
                if not c_reason.strip():
                    st.warning("The reason is the whole point — add one.")
                else:
                    from src.corrections import record_correction
                    our_call_row = judged[judged["ig_username"] == c_user].iloc[0]
                    our_call = (
                        f"shortlisted (fit {our_call_row.get('campaign_fit_score', '?')})"
                        if "campaign_fit_score" in our_call_row and pd.notna(
                            our_call_row.get("campaign_fit_score")
                        )
                        else f"{our_call_row.get('category', 'rejected')}"
                    )
                    path = record_correction(
                        PROJECT_ROOT / "knowledge" / "clients" / client_folder,
                        c_user,
                        spec_raw.get("name", campaign_path.stem),
                        our_call,
                        c_call,
                        c_reason,
                    )
                    st.success(
                        f"Saved to {path.relative_to(PROJECT_ROOT)} and cleared "
                        f"@{c_user}'s cached verdict — the next run re-judges "
                        f"them with this correction in context."
                    )
