"""
ui_styles.py — Augmentum Media design language (light mode) for Streamlit.

Redesigned 2026-06-11 against the canonical brand spec
(.claude/skills/augmentum-design-language-light-mode): white page with a
faint surface gradient, navy #030937 text (never pure black), hot-pink
#ff007e accent, Playfair Display for display type, Geist for body/UI/data.
Editorial, premium, data-forward.

Every page calls inject() at the top so styling follows the user across
navigation. Class names are stable — pages reference them in html blocks —
so change values here, not names.
"""

import streamlit as st

_STYLES = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&family=Geist:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>

/* ─── TOKENS (canonical Augmentum light mode) ───────────────────────────── */
:root {
  --color-navy:      #030937;
  --color-navy-80:   rgba(3, 9, 55, 0.80);
  --color-navy-60:   rgba(3, 9, 55, 0.60);
  --color-navy-20:   rgba(3, 9, 55, 0.20);
  --color-navy-08:   rgba(3, 9, 55, 0.08);
  --color-pink:      #ff007e;
  --color-pink-20:   rgba(255, 0, 126, 0.20);
  --color-pink-10:   rgba(255, 0, 126, 0.10);
  --color-white:     #ffffff;
  --color-surface:   #f7f8fc;
  --color-surface-2: #eef0f8;
  --color-border:    #e2e5f0;
  --color-muted:     #858588;
  --color-success:   #00c27c;
  --color-warning:   #f5a623;
  --color-error:     #e53e3e;
  --font-display: "Playfair Display", Georgia, serif;
  --font-body: "Geist", "Inter", system-ui, sans-serif;
  --shadow-sm: 0 1px 3px rgba(3,9,55,0.06), 0 4px 16px rgba(3,9,55,0.04);
  --shadow-md: 0 4px 24px rgba(3,9,55,0.10);
  --radius-md: 8px;
  --radius-lg: 12px;
}

/* ─── BASE ──────────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
  background: linear-gradient(180deg, var(--color-surface) 0%, var(--color-white) 280px) !important;
  font-family: var(--font-body) !important;
  color: var(--color-navy) !important;
}
[data-testid="stHeader"] { background: transparent !important; }
.block-container { max-width: 1200px; padding-top: 2.4rem !important; }

h1, h2, h3 { font-family: var(--font-display) !important; color: var(--color-navy) !important; letter-spacing: -0.02em; }
h4, h5, h6 { font-family: var(--font-body) !important; color: var(--color-navy) !important; }
p, li { font-family: var(--font-body); color: var(--color-navy-80); }
a { color: #0099ff !important; }
hr { border-color: var(--color-border) !important; }
code {
  background: var(--color-navy-08) !important; color: var(--color-navy) !important;
  border-radius: 4px; padding: 1px 5px; font-size: 0.85em;
}

/* ─── SIDEBAR ───────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: var(--color-white) !important;
  border-right: 1px solid var(--color-border) !important;
}
[data-testid="stSidebar"] * { font-family: var(--font-body); }

/* Material icon glyphs must keep their ligature font — without this the
   sidebar collapse arrow renders as literal "keyboard_double_arrow_left" */
[data-testid="stIconMaterial"], .material-symbols-rounded,
[class*="material-symbols"], [data-testid="stExpanderToggleIcon"] {
  font-family: "Material Symbols Rounded" !important;
}
[data-testid="stSidebarNav"] a {
  border-radius: var(--radius-md);
  font-weight: 500;
  color: var(--color-navy-80) !important;
}
[data-testid="stSidebarNav"] a:hover { background: var(--color-surface) !important; }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--color-pink-10) !important;
  border-left: 3px solid var(--color-pink);
  font-weight: 600;
}
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--color-navy) !important; }

.sidebar-brand { padding: 0.4rem 0 0.9rem; border-bottom: 1px solid var(--color-border); margin-bottom: 0.75rem; }
.sidebar-logo-wrap { display: flex; align-items: center; gap: 10px; }
.sidebar-logo-img { width: 38px; height: 38px; border-radius: 9px; object-fit: cover; }
.sidebar-logo-text { min-width: 0; }
.sidebar-product-name {
  font-family: var(--font-display); font-weight: 700; font-size: 1.05rem;
  color: var(--color-navy); line-height: 1.15;
}
.sidebar-product-name span { color: var(--color-pink); font-style: italic; }
.sidebar-company-name {
  font-size: 0.66rem; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--color-muted); margin-top: 2px;
}
.sidebar-status-strip { display: flex; align-items: center; gap: 7px; margin-top: 10px; }
.sidebar-status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); flex-shrink: 0; }
.sidebar-status-label { font-size: 0.72rem; color: var(--color-navy-60); }

/* ─── HERO ──────────────────────────────────────────────────────────────── */
.hero-wrapper { padding: 1.6rem 0 2.2rem; }
.hero-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--color-pink-10); border: 1px solid var(--color-pink-20);
  border-radius: 999px; padding: 5px 14px; margin-bottom: 1.4rem;
}
.hero-badge-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-pink); }
.hero-badge-text {
  font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--color-pink);
}
.hero-title {
  font-family: var(--font-display); font-size: 3.4rem; font-weight: 600;
  line-height: 1.02; letter-spacing: -0.04em; margin-bottom: 1.1rem;
  color: var(--color-navy);
}
.hero-title-accent { color: var(--color-pink); font-style: italic; }
.hero-title-dim { color: var(--color-navy); }
.hero-subtitle {
  font-size: 1.02rem; line-height: 1.65; color: var(--color-navy-60);
  max-width: 680px;
}

/* ─── SECTION LABELS + STEP HEADERS ─────────────────────────────────────── */
.section-label {
  font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--color-pink);
  margin: 1.6rem 0 0.9rem; display: flex; align-items: center; gap: 10px;
}
.section-label::after { content: ""; flex: 1; height: 1px; background: var(--color-border); }

.step-header { display: flex; align-items: center; gap: 12px; margin: 2.2rem 0 0.9rem; }
.step-number {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: var(--color-pink); color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 0.8125rem; font-weight: 700;
}
.step-title {
  font-family: var(--font-display); font-size: 1.35rem; font-weight: 600;
  color: var(--color-navy); letter-spacing: -0.01em;
}

/* ─── PAGE HEADERS ──────────────────────────────────────────────────────── */
.page-header { padding: 0.4rem 0 1.2rem; border-bottom: 1px solid var(--color-border); margin-bottom: 1rem; }
.page-title {
  font-family: var(--font-display); font-size: 2.3rem; font-weight: 600;
  color: var(--color-navy); letter-spacing: -0.03em; margin-bottom: 0.55rem;
}
.page-subtitle { font-size: 0.95rem; line-height: 1.65; color: var(--color-navy-60); max-width: 760px; }

/* ─── CARDS ─────────────────────────────────────────────────────────────── */
.workflow-card {
  position: relative; background: var(--color-white);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  padding: 1.5rem 1.5rem 1.25rem; height: 100%;
  box-shadow: var(--shadow-sm); overflow: hidden;
  transition: box-shadow .18s ease, transform .18s ease;
}
.workflow-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.workflow-card::before {
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, #ff007e, #ff4da6);
}
.workflow-num {
  font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--color-pink); margin-bottom: 0.5rem;
}
.workflow-title {
  font-family: var(--font-display); font-size: 1.45rem; font-weight: 600;
  color: var(--color-navy); margin-bottom: 0.6rem;
}
.workflow-desc { font-size: 0.875rem; line-height: 1.62; color: var(--color-navy-60); }

.config-card {
  display: flex; align-items: flex-start; gap: 12px;
  background: var(--color-white); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: 1rem 1.2rem; box-shadow: var(--shadow-sm);
}
.config-status-dot { width: 9px; height: 9px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.config-status-dot.ok { background: var(--color-success); box-shadow: 0 0 0 3px rgba(0,194,124,0.15); }
.config-status-dot.err { background: var(--color-error); box-shadow: 0 0 0 3px rgba(229,62,62,0.15); }
.config-label { font-size: 0.8125rem; font-weight: 600; color: var(--color-navy); }
.config-value { font-size: 0.78rem; color: var(--color-navy-60); margin-top: 2px; line-height: 1.5; }

/* Train Clients page cards */
.client-card {
  background: var(--color-white); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: 1.1rem 1.25rem;
  box-shadow: var(--shadow-sm); margin-bottom: 0.75rem;
}
.client-name {
  font-family: var(--font-display); font-size: 1.1rem; font-weight: 600;
  color: var(--color-navy);
}
.client-meta { font-size: 0.78rem; color: var(--color-navy-60); margin-top: 3px; }
.active-badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--color-pink-10); color: var(--color-pink);
  border: 1px solid var(--color-pink-20); border-radius: 999px;
  font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.05em;
  text-transform: uppercase; padding: 3px 10px;
}
.style-guide-wrap {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: 1.5rem; margin-bottom: 1.5rem;
}
.guide-question {
  font-size: 0.8125rem; color: var(--color-navy-60);
  margin-bottom: 6px; padding-left: 12px;
  border-left: 2px solid var(--color-pink-20);
}

/* ─── BUTTONS ───────────────────────────────────────────────────────────── */
.stButton > button, [data-testid="stFormSubmitButton"] > button {
  font-family: var(--font-body) !important; font-weight: 600 !important;
  font-size: 0.875rem !important; border-radius: 6px !important;
  padding: 0.55rem 1.4rem !important; letter-spacing: 0.01em;
  transition: filter .15s ease, box-shadow .15s ease;
}
.stButton > button[kind="primary"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"],
[data-testid="stFormSubmitButton"] > button {
  background: var(--color-pink) !important; border: none !important;
  box-shadow: 0 2px 10px rgba(255,0,126,0.25);
}
.stButton > button[kind="primary"] *,
[data-testid="baseButton-primary"] *,
[data-testid="baseButton-primaryFormSubmit"] *,
[data-testid="stFormSubmitButton"] > button * { color: #ffffff !important; }
.stButton > button[kind="primary"]:hover { filter: brightness(0.92); box-shadow: 0 3px 14px rgba(255,0,126,0.35); }
.stButton > button[kind="primary"]:disabled { background: var(--color-navy-20) !important; box-shadow: none; }

.stButton > button[kind="secondary"] {
  background: transparent !important; color: var(--color-navy) !important;
  border: 1.5px solid var(--color-navy-20) !important;
}
.stButton > button[kind="secondary"]:hover { border-color: var(--color-navy) !important; }

[data-testid="stDownloadButton"] > button {
  background: var(--color-navy) !important; border: none !important;
  border-radius: 6px !important; font-weight: 600 !important; font-size: 0.85rem !important;
}
[data-testid="stDownloadButton"] > button * { color: #ffffff !important; }
[data-testid="stDownloadButton"] > button:hover { filter: brightness(1.6); }

/* ─── INPUTS ────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {
  background: var(--color-white) !important; color: var(--color-navy) !important;
  border-radius: var(--radius-md) !important;
  border-color: var(--color-border) !important;
  font-family: var(--font-body) !important;
}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
  border-color: var(--color-pink) !important;
  box-shadow: 0 0 0 3px var(--color-pink-20) !important;
}
[data-baseweb="checkbox"] [aria-checked="true"] > div:first-child {
  background: var(--color-pink) !important; border-color: var(--color-pink) !important;
}

/* ─── FILE UPLOADER ─────────────────────────────────────────────────────── */
[data-testid="stFileUploaderDropzone"] {
  background: var(--color-surface) !important;
  border: 1.5px dashed var(--color-navy-20) !important;
  border-radius: var(--radius-lg) !important;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--color-pink) !important; }
[data-testid="stFileUploaderDropzone"] button {
  background: var(--color-white) !important; color: var(--color-navy) !important;
  border: 1.5px solid var(--color-navy-20) !important; border-radius: 6px !important;
  font-weight: 600 !important;
}

/* ─── TABS — segmented-control style, clearly separated ─────────────────── */
.stTabs [data-baseweb="tab-list"] {
  gap: 6px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 5px;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--font-body) !important; font-weight: 500;
  font-size: 0.85rem;
  color: var(--color-navy-60) !important;
  background: transparent !important;
  border-radius: 8px !important;
  padding: 9px 18px !important;
  transition: background .15s ease, color .15s ease;
}
.stTabs [data-baseweb="tab"]:hover {
  background: rgba(255,255,255,0.7) !important;
  color: var(--color-navy) !important;
}
.stTabs [aria-selected="true"] {
  background: var(--color-white) !important;
  color: var(--color-navy) !important;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border);
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-panel"] {
  padding-top: 1.4rem;
  border-top: 1px solid var(--color-border);
  margin-top: 1rem;
}

/* ─── METRICS ───────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
  background: var(--color-white); border: 1px solid var(--color-border);
  border-bottom: 2px solid var(--color-pink);
  border-radius: var(--radius-lg); padding: 1rem 1.2rem 0.8rem;
  box-shadow: var(--shadow-sm);
}
[data-testid="stMetricLabel"] p {
  font-size: 0.6875rem !important; font-weight: 600 !important;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--color-pink) !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--font-body) !important; font-weight: 700 !important;
  color: var(--color-navy) !important;
}

/* ─── DATAFRAMES, EXPANDERS, MISC ───────────────────────────────────────── */
[data-testid="stDataFrame"] {
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  overflow: hidden; box-shadow: var(--shadow-sm);
}
[data-testid="stExpander"] {
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--color-white);
  box-shadow: var(--shadow-sm);
}
[data-testid="stExpander"] summary { font-weight: 600; color: var(--color-navy) !important; }
[data-testid="stExpander"] summary:hover { color: var(--color-pink) !important; }

.stProgress > div > div > div > div { background: linear-gradient(90deg, #ff007e, #ff4da6) !important; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--color-muted) !important; }
.stAlert { border-radius: var(--radius-lg) !important; }
[data-testid="stSpinner"] p { color: var(--color-navy-60) !important; }
</style>
"""


def inject() -> None:
    """Inject the Augmentum light-mode design system into the current page.

    Call once at the top of every page, right after st.set_page_config().
    """
    st.html(_STYLES)
