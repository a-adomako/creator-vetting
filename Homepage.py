"""
Homepage.py — CreatorVetter Streamlit entry point (Augmentum light mode).

Run with:
  streamlit run Homepage.py

The file appears as "Homepage" in the sidebar nav. Subpages live in pages/
and are auto-numbered to match the daily workflow:
  1_Vet_Creators → 2_Build_Shortlist → 3_Train_Clients

Light mode design language matches augmentum-media.com's editorial pages:
white background, near-black text + buttons, hot-pink accent reserved for
non-button surfaces (active nav, brand wordmark, badges, step numbers,
focus rings). Restrained — no animated orbs, no glow effects. Subtle
shadows only.
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

# Inject the shared Augmentum light-mode design system
from src.ui_styles import inject as inject_styles
inject_styles()

# Skip the giant inline CSS block — styles now live in src/ui_styles.py
# Below is just legacy markup that the script no longer renders.

# ── Session state initialisation ─────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "active_client" not in st.session_state:
    st.session_state["active_client"] = None

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
        'justify-content:center;font-family:Syne,sans-serif;font-weight:800;'
        'font-size:0.875rem;color:#FF1F8E;flex-shrink:0;">A</div>'
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
  <div class="sidebar-status-strip">
    <div class="sidebar-status-dot"></div>
    <span class="sidebar-status-label">Connected — ready to vet creators</span>
  </div>
</div>
""")

# ── Sidebar: Active client selector (drives Build Shortlist + Train Clients) ─

_clients_dir = Path(__file__).parent / "knowledge" / "clients"
_clients_dir.mkdir(parents=True, exist_ok=True)
_client_names = sorted([d.name for d in _clients_dir.iterdir() if d.is_dir()])

st.sidebar.markdown(
    '<div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.10em;'
    'text-transform:uppercase;color:#5A5A60;'
    'padding:1rem 0 0.25rem;">Active client</div>'
    '<div style="font-size:0.75rem;color:#5A5A60;padding-bottom:0.5rem;line-height:1.5;">'
    'Used by Build Shortlist and Train Clients. The Vet Creators pipeline runs '
    'against the global Augmentum rubric and does not use this selection.'
    '</div>',
    unsafe_allow_html=True,
)

if _client_names:
    _default_idx = 0
    if st.session_state.get("active_client") in _client_names:
        _default_idx = _client_names.index(st.session_state["active_client"])
    _selected = st.sidebar.selectbox(
        "Active client",
        options=_client_names,
        index=_default_idx,
        label_visibility="collapsed",
    )
    st.session_state["active_client"] = _selected
else:
    st.session_state["active_client"] = None
    st.sidebar.markdown(
        '<p style="font-size:0.8125rem;color:#5A5A60;'
        'padding:0 0 0.5rem;">No clients trained yet — create one on the '
        '<strong>Train Clients</strong> page.</p>',
        unsafe_allow_html=True,
    )
    st.sidebar.page_link("pages/3_Train_Clients.py",
                         label="Train your first client", icon="✏️")

st.sidebar.markdown('<hr style="border-color:#E5E5EA;margin:12px 0;"/>',
                    unsafe_allow_html=True)
st.sidebar.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

# ── Home — Hero ──────────────────────────────────────────────────────────────

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
    Score and shortlist Instagram creators against a client's brief without opening
    each profile by hand. Upload a CSV of creators, the tool fetches their profile
    data and reels via Modash, transcribes the audio locally with Whisper,
    classifies what's in the videos with CLIP, and asks Claude to weigh each one
    against your vetting rubric and the active client's scoring style.
  </div>

  <div class="hero-stats">
    <div>
      <div class="hero-stat-value">10k+</div>
      <div class="hero-stat-label">Creators per week the pipeline can chew through</div>
    </div>
    <div class="hero-stat-divider"></div>
    <div>
      <div class="hero-stat-value">Local</div>
      <div class="hero-stat-label">Whisper + CLIP run on this machine, not paid APIs</div>
    </div>
    <div class="hero-stat-divider"></div>
    <div>
      <div class="hero-stat-value">3</div>
      <div class="hero-stat-label">Pages: vet, shortlist, train</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Workflow cards ───────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Three things this tool does</div>',
            unsafe_allow_html=True)

col1, col2, col3 = st.columns(3, gap="small")

with col1:
    st.markdown("""
    <div class="workflow-card">
      <div class="workflow-num">Step 01 — Score</div>
      <div class="workflow-title">Vet Creators</div>
      <div class="workflow-desc">
        Upload a CSV of Instagram URLs or handles. The pipeline pulls each
        creator's profile and reels via Modash, transcribes the audio locally,
        scores engagement and audience quality, runs Claude over the
        transcript and visual scenes, then writes an enriched CSV with
        ~30 columns per creator. Universal-disqualifier check decides which
        creators are safe to enter the central Augmentum database.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Vet_Creators.py",
                 label="Open Vet Creators (upload a CSV and run the pipeline)",
                 icon="▶")

with col2:
    st.markdown("""
    <div class="workflow-card">
      <div class="workflow-num">Step 02 — Shortlist</div>
      <div class="workflow-title">Build Shortlist</div>
      <div class="workflow-desc">
        Take the most recent enriched CSV and have Claude filter it against
        a specific client's brand context, target niches, and personal
        scoring style. Approved / soft-reject / hard-reject groups come back
        with per-creator reasoning. Download the filtered CSV ready to hand
        to the campaign manager.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_Build_Shortlist.py",
                 label="Open Build Shortlist (filter creators for a specific client)",
                 icon="🎯")

with col3:
    st.markdown("""
    <div class="workflow-card">
      <div class="workflow-num">Step 03 — Train</div>
      <div class="workflow-title">Train Clients</div>
      <div class="workflow-desc">
        Create a profile for each client: brand context, target niches,
        and the way you personally evaluate creators for them. The richer
        the profile, the closer Claude's shortlists get to what you would
        pick by hand. Stored as YAML and markdown files in
        knowledge/clients/ and pushable to the central spine database.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_Train_Clients.py",
                 label="Open Train Clients (manage per-client briefs and scoring style)",
                 icon="✏️")

st.markdown('<div style="height:2.5rem;"></div>', unsafe_allow_html=True)

# ── Configuration status ─────────────────────────────────────────────────────

st.markdown('<div class="section-label">API keys configured for this machine</div>',
            unsafe_allow_html=True)

modash_key = os.getenv("MODASH_API_KEY", "")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

cfg_col1, cfg_col2 = st.columns(2, gap="small")

with cfg_col1:
    dot_class = "ok" if modash_key else "err"
    status_text = (
        "Configured — pipeline can fetch Instagram profile data and reels"
        if modash_key else
        "Not set — Vet Creators will not work until this is added to .env"
    )
    st.markdown(f"""
    <div class="config-card">
      <div class="config-status-dot {dot_class}"></div>
      <div>
        <div class="config-label">Modash API Key (MODASH_API_KEY)</div>
        <div class="config-value">{status_text}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

with cfg_col2:
    dot_class = "ok" if anthropic_key else "err"
    status_text = (
        "Configured — Claude can score creators and filter shortlists"
        if anthropic_key else
        "Not set — LLM analysis and the Build Shortlist page will not work"
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
    '<p style="font-size:0.75rem;color:#5A5A60;margin-top:0.75rem;">'
    'Both keys are loaded from the <code>.env</code> file in the project root. '
    'Edit that file directly if a key needs to be added or rotated.'
    '</p>',
    unsafe_allow_html=True,
)

st.markdown('<div style="height:2rem;"></div>', unsafe_allow_html=True)

# ── Input CSV format ─────────────────────────────────────────────────────────

st.markdown('<div class="section-label">What your input CSV needs to look like</div>',
            unsafe_allow_html=True)
st.markdown(
    '<p style="color:#424246;font-size:0.875rem;margin-bottom:1rem;'
    'max-width:720px;line-height:1.6;">'
    'Your CSV must contain at least one of the two columns below — either is fine. '
    'Every other column in the CSV (first name, source tag, niche label, anything) '
    'is preserved unchanged in the enriched output. The column names can be customised '
    'in <code>config/config.yaml</code> under <code>input_columns</code> if your CSV '
    'uses different headers.'
    '</p>',
    unsafe_allow_html=True,
)

import pandas as pd
st.dataframe(
    {
        "Column name": ["`Profile URL`", "`Username`"],
        "What goes in it": [
            "Full Instagram profile URL (e.g. https://www.instagram.com/handle/)",
            "Instagram handle, with or without the @ sign",
        ],
        "Required": [
            "Yes if you don't have Username — one of these two is needed",
            "Yes if you don't have Profile URL — one of these two is needed",
        ],
    },
    use_container_width=False,
    hide_index=True,
)

st.markdown(
    '<p style="font-size:0.75rem;color:#5A5A60;margin-top:0.75rem;">'
    'Need a sample? The <strong>Vet Creators</strong> page has a downloadable '
    'sample CSV you can use as a template.'
    '</p>',
    unsafe_allow_html=True,
)
