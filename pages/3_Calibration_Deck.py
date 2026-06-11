"""
pages/3_Calibration_Deck.py — Teach the model your taste, one swipe at a time.

Shows creators Claude has already judged for a campaign — borderline cases
first — WITHOUT revealing Claude's call. The human approves or rejects;
the label is recorded (local jsonl + prompt-injected markdown + best-effort
spine row), Claude's call is revealed, and a running agreement rate shows
how well-trained the client is. 9/10 agreement = well-calibrated; 6/10 =
keep labelling.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui_styles import inject as inject_styles
from src.calibration import (
    agreement_stats, load_candidates, load_labels, record_label,
)

st.set_page_config(page_title="Calibration Deck — CreatorVetter", layout="wide")
inject_styles()

CAMPAIGNS_DIR = PROJECT_ROOT / "campaigns"
CLIENTS_DIR = PROJECT_ROOT / "knowledge" / "clients"

st.markdown("""
<div class="page-header">
  <div class="page-title">Calibration Deck</div>
  <div class="page-subtitle">
    Train the model by judging real profiles — uncertain cases first. You see
    the creator's evidence, not the AI's verdict, so your call is unanchored.
    Every swipe becomes a labelled example injected into future judgments,
    and the agreement rate tells you when the client is trained well enough
    to trust.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Setup ────────────────────────────────────────────────────────────────────

campaign_files = sorted(CAMPAIGNS_DIR.glob("*.yaml"))
if not campaign_files:
    st.warning("No campaign specs in campaigns/ — create one first.")
    st.stop()

reviewer = st.sidebar.text_input(
    "Your name (recorded with each label)",
    value=st.session_state.get("calib_reviewer", ""),
)
st.session_state["calib_reviewer"] = reviewer

campaign_path = st.sidebar.selectbox(
    "Campaign", campaign_files, format_func=lambda p: p.stem
)
spec = yaml.safe_load(campaign_path.read_text(encoding="utf-8")) or {}
campaign_name = spec.get("name", campaign_path.stem)
client_folder = spec.get("client_folder")

if not client_folder:
    st.error("This campaign has no client_folder — labels need a client to "
             "belong to. Add client_folder to the campaign YAML.")
    st.stop()
client_dir = CLIENTS_DIR / client_folder

push_to_spine = st.sidebar.checkbox(
    "Also record labels in the central database",
    value=True,
    help="Writes a human_approved/human_rejected row to the spine's "
         "creator_vetting table. Local files are always written regardless.",
)

# ── Stats header ─────────────────────────────────────────────────────────────

labels = load_labels(client_dir)
stats = agreement_stats(labels, campaign_name)

candidates_key = f"calib_candidates_{campaign_name}"
if candidates_key not in st.session_state:
    st.session_state[candidates_key] = load_candidates(campaign_name, client_dir)
candidates = st.session_state[candidates_key]

c1, c2, c3 = st.columns(3)
c1.metric("Labelled so far", stats["labeled"])
c2.metric(
    "Agreement with the model",
    f"{stats['rate']}%" if stats["rate"] is not None else "—",
    help="Over labels where the model made a decisive call. 90%+ means this "
         "client is well-trained; under 70% means keep labelling.",
)
c3.metric("Waiting for a label", len(candidates))

st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)

# ── The deck ─────────────────────────────────────────────────────────────────

if not candidates:
    st.success(
        "Nothing left to label for this campaign — every judged creator has "
        "a human call. Run more vetting to feed the deck."
    )
    st.stop()

rec = candidates[0]
verdict = rec.get("verdict") or {}
metrics = rec.get("metrics") or {}
username = rec.get("username", "?")

with st.container(border=True):
    head_l, head_r = st.columns([3, 1])
    with head_l:
        st.markdown(
            f"### @{username}"
            f"&nbsp;&nbsp;<span style='font-size:0.8rem;'>"
            f"<a href='https://www.instagram.com/{username}/' target='_blank'>"
            f"open on Instagram ↗</a></span>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{metrics.get('ig_full_name', '')} · "
            f"{metrics.get('followers', 0):,} followers · "
            f"{metrics.get('avg_engagement_rate', '?')}% engagement · "
            f"{metrics.get('posts_last_30_days', '?')} posts in 30 days"
        )
    with head_r:
        st.caption(f"Card 1 of {len(candidates)} — borderline cases first")

    st.markdown("**Bio**")
    st.markdown(f"> {rec.get('biography', '').strip() or '_empty_'}")

    captions = [c for c in (rec.get("captions") or []) if c and c.strip()]
    if captions:
        st.markdown("**Recent captions**")
        for cap in captions[:3]:
            st.markdown(f"- {cap[:220]}")

    comments = rec.get("comments_sampled") or []
    if comments:
        with st.expander(f"Sample comments ({len(comments)})"):
            for cm in comments[:12]:
                st.markdown(f"- {cm}")

    transcripts = rec.get("transcripts") or []
    spoken = [t.get("text", "") for t in transcripts if t.get("text")]
    if spoken:
        with st.expander("Reel audio transcripts (may be background music)"):
            for i, t in enumerate(spoken, 1):
                st.markdown(f"**Reel {i}:** {t[:400]}")

# ── Swipe controls ───────────────────────────────────────────────────────────

why = st.text_input(
    "Why? (optional, but a reason teaches the model far more than the swipe alone)",
    key=f"calib_why_{username}",
)

b1, b2, b3 = st.columns([1, 1, 1])
decision = None
if b1.button("✓ Approve for this client", type="primary", use_container_width=True):
    decision = "approve"
if b2.button("✗ Reject for this client", use_container_width=True):
    decision = "reject"
if b3.button("Skip →", use_container_width=True):
    candidates.pop(0)
    st.rerun()

if decision:
    label = record_label(
        client_dir, campaign_name, rec, decision, why, reviewer or "unknown"
    )
    claude_call = verdict.get("recommendation", "needs_review")
    if claude_call == decision:
        st.success(
            f"Recorded. The model agreed — it also said **{claude_call}** "
            f"(fit {verdict.get('campaign_fit_score', '?')})."
        )
    else:
        st.warning(
            f"Recorded — and this one mattered: the model said "
            f"**{claude_call}** (fit {verdict.get('campaign_fit_score', '?')}), "
            f"you said **{decision}**. Your call now outranks it in every "
            f"future judgment."
        )

    if push_to_spine:
        from src.spine import record_human_decision, slugify_folder
        result = record_human_decision(
            username=username,
            campaign=campaign_name,
            client_slug=slugify_folder(client_folder),
            approved=(decision == "approve"),
            reason=why or f"calibration deck label by {reviewer or 'unknown'}",
            decided_by=reviewer or "unknown",
            verdict=verdict,
            profile_seed={
                "biography": rec.get("biography", ""),
                "followers": metrics.get("followers"),
                "ig_full_name": metrics.get("ig_full_name", ""),
                "platform_user_id": rec.get("platform_user_id"),
                "avg_engagement_rate": metrics.get("avg_engagement_rate"),
            },
        )
        if result and not result.errors:
            st.caption("Central database updated (profile + human decision row).")
        else:
            st.caption(
                "Central database unreachable — label saved locally and can "
                "be synced later."
            )

    candidates.pop(0)
    if st.button("Next card →", type="primary"):
        st.rerun()
