"""
Homepage.py — CreatorVetter Streamlit entry point (Augmentum light mode).

Run with:
  streamlit run Homepage.py

The file appears as "Homepage" in the sidebar nav. Subpages live in pages/:
  1_Vet_for_Campaign → 2_Train_Clients

Simplified 2026-06-11: the v1 pages (Vet Creators, Build Shortlist) moved to
to-archive/legacy-ui/ — the campaign flow does both jobs in one motion. The
sidebar active-client selector went with them (the campaign YAML's
client_folder decides calibration now; Train Clients manages its own
selection).
"""

import os
import base64
import sys
from pathlib import Path

import streamlit as st

# Make `src/` importable so the shared design-system helper can be loaded
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

st.set_page_config(
    page_title="CreatorVetter — Augmentum Media",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.ui_styles import inject as inject_styles
inject_styles()

# ── Sidebar brand lockup ─────────────────────────────────────────────────────

_logo_path = None
for _ext in ("logo.png", "logo.avif", "logo.jpg", "logo.jpeg", "logo.svg", "logo.webp",
             "Augmentum logo.jpg", "Augmentum logo.png", "Augmentum logo.jpeg"):
    _candidate = Path(__file__).parent / _ext
    if _candidate.exists():
        _logo_path = _candidate
        break

if _logo_path:
    _mime = (
        "image/jpeg" if str(_logo_path).lower().endswith((".jpg", ".jpeg")) else
        "image/png"  if str(_logo_path).lower().endswith(".png")            else
        "image/avif" if str(_logo_path).lower().endswith(".avif")           else
        "image/png"
    )
    _b64 = base64.b64encode(_logo_path.read_bytes()).decode()
    _logo_html = f'<img src="data:{_mime};base64,{_b64}" class="sidebar-logo-img" />'
else:
    _logo_html = (
        '<div style="width:36px;height:36px;border-radius:8px;background:rgba(255,31,142,0.10);'
        'border:1px solid rgba(255,31,142,0.25);display:flex;align-items:center;'
        'justify-content:center;font-family:Playfair Display,sans-serif;font-weight:800;'
        'font-size:0.875rem;color:#ff007e;flex-shrink:0;">A</div>'
    )

st.sidebar.html(f"""
<div class="sidebar-brand">
  <div class="sidebar-logo-wrap">
    {_logo_html}
    <div class="sidebar-logo-text">
      <div class="sidebar-product-name"><span>Creator</span>Vetter</div>
      <div class="sidebar-company-name">Augmentum Media — Internal Tool</div>
    </div>
  </div>
</div>
""")

# ── Hero ─────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="hero-wrapper">
  <div class="hero-badge">
    <div class="hero-badge-dot"></div>
    <span class="hero-badge-text">Augmentum Media — Discovery Intelligence</span>
  </div>

  <div class="hero-title">
    <span class="hero-title-accent">Creator</span><br>
    <span class="hero-title-dim">Vetter</span>
  </div>

  <div class="hero-subtitle">
    Upload a CSV of Instagram creators, pick a campaign, get back a shortlist.
    Creators failing the campaign's measurable criteria are filtered instantly
    for free; the rest are judged by AI on their bio, captions, and frames
    sampled from their recent reels — weighed against the campaign brief and
    the client's trained scoring style. Already-vetted creators are reused
    from the last 6 months instead of being re-vetted.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Workflow cards ───────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Two things this tool does</div>',
            unsafe_allow_html=True)

col1, col2 = st.columns(2, gap="small")

with col1:
    st.markdown("""
    <div class="workflow-card">
      <div class="workflow-num">Step 01 — Vet</div>
      <div class="workflow-title">Vet for Campaign</div>
      <div class="workflow-desc">
        Pick a campaign spec, upload a CSV of Instagram URLs or handles, run.
        Results come back in three lean lists: shortlisted (with a one-line
        reason and the evidence behind it), rejected (with the stage and
        category), and needs-review (VIP-tier accounts, missing data, genuine
        judgment calls). Full per-creator evidence is saved alongside.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Vet_for_Campaign.py",
                 label="Open Vet for Campaign (upload a CSV and run)",
                 icon="▶")

with col2:
    st.markdown("""
    <div class="workflow-card">
      <div class="workflow-num">Step 02 — Train</div>
      <div class="workflow-title">Train Clients</div>
      <div class="workflow-desc">
        Create a profile for each client: brand context, target niches, and
        the way you personally evaluate creators for them. Campaign specs
        point at a client folder, so the richer the profile, the closer the
        AI's calls get to what you would pick by hand. Stored as YAML and
        markdown in knowledge/clients/ and pushable to the central spine
        database.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_Train_Clients.py",
                 label="Open Train Clients (manage per-client briefs and scoring style)",
                 icon="✏️")

st.markdown('<div style="height:2.5rem;"></div>', unsafe_allow_html=True)

# ── Configuration status ─────────────────────────────────────────────────────

st.markdown('<div class="section-label">API keys configured for this machine</div>',
            unsafe_allow_html=True)

modash_key = os.getenv("MODASH_API_KEY", "")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

cfg_col1, cfg_col2 = st.columns(2, gap="small")

@st.cache_data(ttl=600, show_spinner=False)
def _modash_balance():
    from src.modash_usage import get_balance, usage_summary
    return get_balance(), usage_summary(days=7)


with cfg_col1:
    if not modash_key:
        dot_class, status_text = "err", (
            "Not set — vetting will not work until this is added to .env"
        )
    else:
        balance, week = _modash_balance()
        if balance is None:
            dot_class, status_text = "ok", "Configured — balance check unavailable right now"
        else:
            credits = balance.get("credits") or 0
            raw = balance.get("raw_requests")
            raw_ok = raw is not None and raw > 100
            dot_class = "ok" if raw_ok else "err"
            status_text = (
                f"{credits:,.0f} Discovery credits · {raw:,.0f} raw requests left "
                f"(shared account — separate pools). This tool used "
                f"{week['raw_requests']} raw + {week['credits']} credits in 7 days."
            )
            if not raw_ok:
                status_text += " ⚠ Raw pool low/exhausted — request a top-up in #augmentum-modash."
    st.markdown(f"""
    <div class="config-card">
      <div class="config-status-dot {dot_class}"></div>
      <div>
        <div class="config-label">Modash — credits &amp; raw requests</div>
        <div class="config-value">{status_text}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

with cfg_col2:
    dot_class = "ok" if anthropic_key else "err"
    status_text = (
        "Configured — Claude can judge creators against campaign briefs"
        if anthropic_key else
        "Not set — vetting will not work until this is added to .env"
    )
    st.markdown(f"""
    <div class="config-card">
      <div class="config-status-dot {dot_class}"></div>
      <div>
        <div class="config-label">Anthropic API Key (ANTHROPIC_API_KEY)</div>
        <div class="config-value">{status_text}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown(
    '<p style="font-size:0.75rem;color:#686b87;margin-top:0.75rem;">'
    'Keys load from the <code>.env</code> file in the project root. Your input '
    'CSV needs a <code>Profile URL</code> or <code>Username</code> column — '
    'everything else is preserved as-is.'
    '</p>',
    unsafe_allow_html=True,
)
