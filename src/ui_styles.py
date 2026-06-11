"""
ui_styles.py — Augmentum light mode design system for the Streamlit app.

One source of truth for tokens, base styles, component styles, and per-page
classes. Every Streamlit page calls `inject()` at the top so the styling
follows the user across navigation.

Light mode rules:
  - Pure white background (#FFFFFF), Apple-style near-black text (#1D1D1F)
  - Hot pink (#FF1F8E) is the single accent — used sparingly for status
    cues, active nav, and primary buttons
  - Subtle hairline borders (#E5E5EA), very soft shadows (alpha < 0.1)
  - No animations, no glow effects — restrained, internal-tool feel
"""

import streamlit as st


_STYLES = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap" rel="stylesheet">
<style>

/* ─── TOKENS ─────────────────────────────────────────────────────────────── */
:root {
  --bg:             #FFFFFF;
  --surface:        #FAFAFA;
  --surface-raised: #FFFFFF;
  --surface-border: #E5E5EA;
  --surface-hover:  #F2F2F4;

  --primary:        #FF1F8E;
  --primary-muted:  rgba(255,31,142,0.06);
  --primary-border: rgba(255,31,142,0.22);
  --primary-deep:   #D91775;

  /* Text greys darkened for legibility on white.
     - text-primary  #1D1D1F  → 16.6 : 1  (body, headlines)
     - text-secondary #424246 →  9.3 : 1  (labels, subtitles, body paragraphs)
     - text-muted    #5A5A60 →  6.7 : 1  (captions, hints, fine print)
     All three pass WCAG AAA. Earlier palette used #6E6E73 / #86868B which
     read as washed-out on white. */
  --text-primary:   #1D1D1F;
  --text-secondary: #424246;
  --text-muted:     #5A5A60;

  --success:        #06A672;
  --success-bg:     rgba(6,166,114,0.08);
  --error:          #D03B47;
  --error-bg:       rgba(208,59,71,0.07);
  --warning:        #C77609;
  --warning-bg:     rgba(199,118,9,0.08);

  --font-display: 'Syne', system-ui, sans-serif;
  --font-body:    'DM Sans', system-ui, sans-serif;
  --font-mono:    'SF Mono', 'Fira Code', monospace;

  --r-xs: 4px; --r-sm: 6px; --r-md: 10px; --r-lg: 16px;
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 16px;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.06);

  --dur: 180ms;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
}

/* ─── BASE ───────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
  font-family: var(--font-body) !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
.stApp { background-color: var(--bg) !important; color: var(--text-primary) !important; }
.main .block-container {
  background-color: var(--bg) !important;
  padding-top: 2rem !important;
  padding-bottom: 4rem !important;
  max-width: 1200px;
}

h1 {
  font-family: var(--font-display) !important;
  font-size: 2.5rem !important; font-weight: 800 !important;
  letter-spacing: -0.03em !important;
  color: var(--text-primary) !important; line-height: 1.1 !important;
}
h2 {
  font-family: var(--font-display) !important;
  font-size: 1.5rem !important; font-weight: 700 !important;
  letter-spacing: -0.02em !important; color: var(--text-primary) !important;
}
h3 { font-size: 1.125rem !important; font-weight: 600 !important; color: var(--text-primary) !important; }
h4, h5, h6 { font-weight: 600 !important; color: var(--text-primary) !important; }

p, .stMarkdown p {
  color: var(--text-secondary) !important;
  line-height: 1.65 !important; font-size: 0.9375rem !important;
}
p strong, .stMarkdown p strong { color: var(--text-primary) !important; }
label, .stMarkdown span { color: var(--text-secondary) !important; }

/* ─── SIDEBAR ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background-color: var(--surface) !important;
  border-right: 1px solid var(--surface-border) !important;
}
[data-testid="stSidebar"] > div { padding-top: 0 !important; }
[data-testid="stSidebar"] * { color: var(--text-primary); }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
  font-family: var(--font-body) !important;
  font-size: 0.6875rem !important; font-weight: 600 !important;
  letter-spacing: 0.10em !important; text-transform: uppercase !important;
  color: var(--text-muted) !important; margin-bottom: 0.5rem !important;
}

.sidebar-brand {
  padding: 1.5rem 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  margin-bottom: 0.5rem;
}
.sidebar-logo-wrap { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.sidebar-logo-img {
  width: 36px; height: 36px; border-radius: 8px;
  object-fit: contain; background: #FFFFFF;
  border: 1px solid var(--surface-border);
  padding: 4px; flex-shrink: 0;
}
.sidebar-logo-text { display: flex; flex-direction: column; gap: 1px; }
.sidebar-product-name {
  font-family: 'Syne', sans-serif;
  font-size: 1.0625rem; font-weight: 800;
  letter-spacing: -0.025em;
  color: var(--text-primary) !important; line-height: 1.1;
}
.sidebar-product-name span { color: var(--primary) !important; }
.sidebar-company-name {
  font-size: 0.6875rem; font-weight: 500;
  letter-spacing: 0.05em;
  color: var(--text-muted) !important; text-transform: uppercase;
}
.sidebar-status-strip { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
.sidebar-status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--success); flex-shrink: 0;
}
.sidebar-status-label {
  font-size: 0.6875rem; font-weight: 500;
  color: var(--text-muted) !important; letter-spacing: 0.02em;
}

[data-testid="stSidebar"] nav a {
  color: var(--text-secondary) !important;
  text-decoration: none !important;
  border-radius: var(--r-sm) !important;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease) !important;
  padding: 8px 12px !important;
  display: flex !important; align-items: center !important;
  margin: 1px 0 !important;
}
[data-testid="stSidebar"] nav a span { color: var(--text-secondary) !important; font-size: 0.875rem !important; }
[data-testid="stSidebar"] nav a:hover { background-color: var(--surface-hover) !important; }
[data-testid="stSidebar"] nav a:hover span { color: var(--text-primary) !important; }
[data-testid="stSidebar"] nav a[aria-current="page"] {
  background: var(--primary-muted) !important;
  border-left: 2px solid var(--primary) !important;
  border-radius: 0 var(--r-sm) var(--r-sm) 0 !important;
}
[data-testid="stSidebar"] nav a[aria-current="page"] span {
  color: var(--primary) !important; font-weight: 600 !important;
}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {
  color: var(--text-muted) !important; font-size: 0.75rem !important;
}
[data-testid="stSidebar"] [data-testid="stMetric"] {
  background: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important;
  padding: 10px 14px !important; margin-bottom: 8px !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="stSidebar"] .stCode {
  background-color: var(--surface) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-sm) !important; font-size: 0.8rem !important;
}
[data-testid="stSidebar"] code { color: var(--primary-deep) !important; background-color: transparent !important; }
[data-testid="stSidebar"] hr { border-color: var(--surface-border) !important; margin: 16px 0 !important; }

/* ─── BUTTONS ────────────────────────────────────────────────────────────── */
.stButton > button {
  font-family: var(--font-body) !important;
  font-weight: 600 !important; font-size: 0.875rem !important;
  letter-spacing: 0.01em !important;
  border-radius: var(--r-sm) !important;
  padding: 0.5rem 1.25rem !important;
  transition: all var(--dur) var(--ease) !important;
  cursor: pointer !important;
}
/* Primary buttons use near-black (#1D1D1F, same as text). White text on
   #1D1D1F is 16.6:1 contrast — unmissable. Brand hot pink (#FF1F8E) is
   reserved for non-button accents: active sidebar nav, brand wordmark
   accent, hero badge, section-label dashes, step number badges. */
.stButton > button[kind="primary"],
.stButton > button:not([kind="secondary"]),
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"] {
  background: #1D1D1F !important;
  color: #FFFFFF !important;
  border: none !important;
  font-weight: 700 !important;
  letter-spacing: 0.01em !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.10) !important;
}
.stButton > button[kind="primary"] *,
.stButton > button:not([kind="secondary"]) *,
[data-testid="baseButton-primary"] *,
[data-testid="baseButton-primaryFormSubmit"] * {
  color: #FFFFFF !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button:not([kind="secondary"]):hover,
[data-testid="baseButton-primary"]:hover,
[data-testid="baseButton-primaryFormSubmit"]:hover {
  background: #000000 !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.18) !important;
  transform: translateY(-1px) !important;
}
.stButton > button[kind="primary"]:focus,
.stButton > button:not([kind="secondary"]):focus,
[data-testid="baseButton-primary"]:focus {
  box-shadow: 0 0 0 3px var(--primary-muted), 0 1px 2px rgba(0,0,0,0.10) !important;
  outline: none !important;
}
.stButton > button[kind="primary"]:active,
.stButton > button:not([kind="secondary"]):active { transform: translateY(0) !important; }
.stButton > button[kind="secondary"] {
  background-color: var(--surface-raised) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--surface-border) !important;
}
.stButton > button[kind="secondary"]:hover {
  background-color: var(--surface) !important;
  border-color: var(--text-muted) !important;
}
/* Form-submit and download buttons match the primary (near-black) treatment. */
[data-testid="stFormSubmitButton"] > button,
[data-testid="stDownloadButton"] > button {
  background: #1D1D1F !important;
  color: #FFFFFF !important; border: none !important;
  font-weight: 700 !important; letter-spacing: 0.01em !important;
  border-radius: var(--r-sm) !important;
  transition: all var(--dur) var(--ease) !important;
}
[data-testid="stFormSubmitButton"] > button *,
[data-testid="stDownloadButton"] > button * {
  color: #FFFFFF !important;
}
[data-testid="stFormSubmitButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover {
  background: #000000 !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.18) !important;
  transform: translateY(-1px) !important;
}

/* ─── FORM INPUTS ────────────────────────────────────────────────────────── */
.stTextInput > div > div > input, .stTextArea > div > div > textarea {
  background-color: var(--surface-raised) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-sm) !important;
  font-family: var(--font-body) !important; font-size: 0.9375rem !important;
}
.stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px var(--primary-muted) !important;
  outline: none !important;
}
.stTextInput > div > div > input::placeholder, .stTextArea > div > div > textarea::placeholder {
  color: var(--text-muted) !important;
}
.stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div {
  background-color: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-sm) !important; color: var(--text-primary) !important;
}
.stSelectbox [data-baseweb="select"] > div:hover { border-color: var(--text-muted) !important; }
[data-baseweb="popover"] [data-baseweb="menu"] {
  background-color: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important;
  box-shadow: var(--shadow-md) !important;
}
[data-baseweb="popover"] [role="option"] { background-color: transparent !important; color: var(--text-secondary) !important; }
[data-baseweb="popover"] [role="option"]:hover, [data-baseweb="popover"] [aria-selected="true"] {
  background-color: var(--primary-muted) !important; color: var(--text-primary) !important;
}
.stMultiSelect [data-baseweb="tag"] {
  background-color: var(--primary-muted) !important;
  border: 1px solid var(--primary-border) !important;
  color: var(--primary-deep) !important;
  border-radius: 4px !important; font-size: 0.8125rem !important;
}
[data-testid="stSlider"] > div > div > div > div { background: var(--primary) !important; }
[data-testid="stSlider"] [data-testid="stThumbValue"] { color: var(--primary) !important; }
.stCheckbox > label { color: var(--text-secondary) !important; gap: 8px !important; }
[data-testid="stFileUploader"] {
  background-color: var(--surface) !important;
  border: 2px dashed var(--surface-border) !important;
  border-radius: var(--r-md) !important;
}
[data-testid="stFileUploader"]:hover { border-color: var(--primary-border) !important; }
[data-testid="stFileUploader"] span, [data-testid="stFileUploader"] small { color: var(--text-muted) !important; }

/* ─── METRICS, CONTAINERS, ALERTS ────────────────────────────────────────── */
[data-testid="stMetric"] {
  background: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important;
  padding: 18px 20px !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="stMetricLabel"] > div {
  color: var(--text-muted) !important; font-size: 0.6875rem !important;
  font-weight: 600 !important; letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
}
[data-testid="stMetricValue"] > div {
  font-family: var(--font-display) !important; color: var(--text-primary) !important;
  font-size: 1.75rem !important; font-weight: 700 !important;
  letter-spacing: -0.02em !important; line-height: 1.2 !important;
}
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="stAlert"] { border-radius: var(--r-md) !important; border: none !important; padding: 14px 18px !important; }
div[class*="stSuccess"] { background-color: var(--success-bg) !important; border-left: 3px solid var(--success) !important; }
div[class*="stError"] { background-color: var(--error-bg) !important; border-left: 3px solid var(--error) !important; }
div[class*="stWarning"] { background-color: var(--warning-bg) !important; border-left: 3px solid var(--warning) !important; }
div[class*="stInfo"] { background-color: var(--primary-muted) !important; border-left: 3px solid var(--primary) !important; }
[data-testid="stAlert"] p, [data-testid="stAlert"] span, [data-testid="stAlert"] div { color: var(--text-primary) !important; }

[data-testid="stExpander"] {
  background-color: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important; overflow: hidden !important;
}
[data-testid="stExpander"] summary { padding: 14px 18px !important; font-weight: 500 !important; color: var(--text-secondary) !important; }
[data-testid="stExpander"] summary:hover { color: var(--text-primary) !important; }
[data-testid="stExpander"] > div > div { padding: 0 18px 18px !important; }

/* ─── DATAFRAME ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
  border-radius: var(--r-md) !important;
  overflow: hidden !important;
  border: 1px solid var(--surface-border) !important;
}
[data-testid="stDataFrame"] table { background-color: var(--surface-raised) !important; }
[data-testid="stDataFrame"] th {
  background-color: var(--surface) !important; color: var(--text-muted) !important;
  font-size: 0.6875rem !important; font-weight: 600 !important;
  letter-spacing: 0.08em !important; text-transform: uppercase !important;
  border-bottom: 1px solid var(--surface-border) !important;
  padding: 12px 16px !important;
}
[data-testid="stDataFrame"] td {
  background-color: var(--surface-raised) !important; color: var(--text-primary) !important;
  border-bottom: 1px solid var(--surface-border) !important;
  padding: 11px 16px !important; font-size: 0.875rem !important;
}
[data-testid="stDataFrame"] tr:hover td { background-color: var(--surface) !important; }

/* ─── PROGRESS, STATUS, TABS ─────────────────────────────────────────────── */
[data-testid="stStatus"] {
  background-color: var(--surface-raised) !important;
  border: 1px solid var(--surface-border) !important;
  border-radius: var(--r-md) !important;
}
[data-testid="stStatus"] p { color: var(--text-muted) !important; }
[data-testid="stSpinner"] { color: var(--primary) !important; }
.stProgress > div > div { background-color: var(--surface-hover) !important; border-radius: 99px !important; overflow: hidden !important; }
.stProgress > div > div > div { background: var(--primary) !important; border-radius: 99px !important; transition: width 300ms var(--ease) !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0 !important; border-bottom: 1px solid var(--surface-border) !important; background-color: transparent !important; }
.stTabs [data-baseweb="tab"] {
  background-color: transparent !important; color: var(--text-muted) !important;
  font-weight: 500 !important; font-size: 0.875rem !important;
  padding: 10px 18px !important; border-bottom: 2px solid transparent !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-primary) !important; background-color: transparent !important; }
.stTabs [aria-selected="true"] { color: var(--primary) !important; border-bottom-color: var(--primary) !important; font-weight: 600 !important; }

/* ─── CODE ───────────────────────────────────────────────────────────────── */
code {
  font-family: var(--font-mono) !important; font-size: 0.8125rem !important;
  background-color: var(--surface) !important; color: var(--primary-deep) !important;
  padding: 2px 6px !important; border-radius: 4px !important;
  border: 1px solid var(--surface-border) !important;
}
.stCode > div { background-color: var(--surface) !important; border: 1px solid var(--surface-border) !important; border-radius: var(--r-md) !important; }

/* ─── PAGE LINKS ─────────────────────────────────────────────────────────── */
[data-testid="stPageLink"] a {
  display: inline-flex !important; align-items: center !important; gap: 6px !important;
  font-size: 0.8125rem !important; font-weight: 600 !important;
  color: var(--text-secondary) !important; text-decoration: none !important;
  padding: 6px 0 !important;
}
[data-testid="stPageLink"] a:hover { color: var(--primary) !important; }

/* ─── MISC ───────────────────────────────────────────────────────────────── */
hr { border: none !important; border-top: 1px solid var(--surface-border) !important; margin: 2rem 0 !important; }
.stCaption, [data-testid="stCaptionContainer"] p, small {
  color: var(--text-muted) !important; font-size: 0.8125rem !important; line-height: 1.5 !important;
}
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--surface-border); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ═══ HOME — HERO ════════════════════════════════════════════════════════ */
.hero-wrapper { position: relative; padding: 3rem 0 2.5rem; }
.hero-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--primary-muted); border: 1px solid var(--primary-border);
  border-radius: 99px; padding: 5px 14px 5px 8px;
  margin-bottom: 1.5rem;
}
.hero-badge-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); flex-shrink: 0; }
.hero-badge-text {
  font-family: var(--font-body); font-size: 0.6875rem; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--primary-deep);
}
.hero-title {
  font-family: var(--font-display); font-size: 4.25rem; font-weight: 800;
  letter-spacing: -0.045em; line-height: 0.95; color: var(--text-primary);
}
.hero-title-accent { color: var(--primary); }
.hero-title-dim { color: var(--text-muted); }
.hero-subtitle {
  font-size: 1.0625rem; color: var(--text-secondary);
  line-height: 1.6; max-width: 640px; margin-top: 1.5rem;
}
.hero-stats {
  display: flex; align-items: center; gap: 2rem;
  margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid var(--surface-border);
}
.hero-stat-value {
  font-family: var(--font-display); font-size: 1.5rem; font-weight: 800;
  letter-spacing: -0.03em; color: var(--text-primary); line-height: 1;
}
.hero-stat-label { font-size: 0.75rem; font-weight: 500; color: var(--text-muted); margin-top: 4px; letter-spacing: 0.02em; }
.hero-stat-divider { width: 1px; height: 32px; background: var(--surface-border); flex-shrink: 0; }

/* ═══ SECTION LABEL ══════════════════════════════════════════════════════ */
.section-label {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-body); font-size: 0.6875rem;
  font-weight: 600; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--text-muted);
  margin-bottom: 1rem;
}
.section-label::before {
  content: ''; display: block; width: 16px; height: 2px;
  background: var(--primary); border-radius: 99px; flex-shrink: 0;
}

/* ═══ WORKFLOW CARDS (home) ══════════════════════════════════════════════ */
.workflow-card {
  position: relative; background: var(--surface-raised);
  border: 1px solid var(--surface-border); border-radius: var(--r-lg);
  padding: 1.5rem 1.5rem 1.25rem;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.workflow-card:hover { border-color: var(--primary-border); box-shadow: var(--shadow-md); transform: translateY(-2px); }
.workflow-num {
  font-family: var(--font-display); font-size: 0.6875rem; font-weight: 700;
  letter-spacing: 0.16em; color: var(--primary);
  margin-bottom: 0.75rem; text-transform: uppercase;
}
.workflow-title {
  font-family: var(--font-display); font-size: 1.125rem; font-weight: 700;
  color: var(--text-primary); margin-bottom: 0.5rem; letter-spacing: -0.02em;
}
.workflow-desc { font-size: 0.8125rem; color: var(--text-muted); line-height: 1.6; }

/* ═══ CONFIG CARDS (home) ════════════════════════════════════════════════ */
.config-card {
  background: var(--surface-raised); border: 1px solid var(--surface-border);
  border-radius: var(--r-md); padding: 1rem 1.25rem;
  display: flex; align-items: center; gap: 0.875rem;
}
.config-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.config-status-dot.ok   { background: var(--success); }
.config-status-dot.err  { background: var(--error); }
.config-status-dot.warn { background: var(--warning); }
.config-label { font-size: 0.8125rem; font-weight: 600; color: var(--text-primary); }
.config-value { font-size: 0.75rem; color: var(--text-muted); margin-top: 2px; }

/* ═══ PAGE HEADER (sub-pages) ════════════════════════════════════════════ */
.page-header {
  padding: 2rem 0 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  margin-bottom: 1.75rem;
}
.page-title {
  font-family: var(--font-display) !important; font-size: 2.125rem !important;
  font-weight: 800 !important; letter-spacing: -0.035em !important;
  color: var(--text-primary) !important;
  margin-bottom: 0.375rem !important; line-height: 1.05 !important;
}
.page-subtitle {
  font-size: 0.9375rem; color: var(--text-muted);
  line-height: 1.55; max-width: 720px;
}

/* ═══ STEP HEADERS (Vet Creators page) ═══════════════════════════════════ */
.step-header {
  display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem;
}
.step-number {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 50%;
  background-color: var(--primary-muted); border: 1px solid var(--primary-border);
  font-size: 0.75rem; font-weight: 700; color: var(--primary);
  flex-shrink: 0; font-family: var(--font-display, sans-serif);
}
.step-number.done { background-color: var(--success-bg); border-color: rgba(6,166,114,0.30); color: var(--success); }
.step-label { font-size: 1rem; font-weight: 600; color: var(--text-primary); }
.step-desc { font-size: 0.875rem; color: var(--text-muted); margin-top: 0.25rem; margin-bottom: 1rem; line-height: 1.55; max-width: 720px; }
.run-cta {
  background: var(--surface-raised); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 1.5rem 1.75rem; margin-bottom: 1.25rem;
}
.progress-section {
  background-color: var(--surface-raised); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 1.5rem 1.75rem;
}
.progress-title {
  font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.10em;
  text-transform: uppercase; color: var(--text-muted); margin-bottom: 1rem;
}
.completion-stat {
  background: var(--surface-raised); border: 1px solid var(--surface-border);
  border-radius: var(--radius-sm); padding: 1rem 1.25rem;
}

/* ═══ AGENT/SHORTLIST PAGE ═══════════════════════════════════════════════ */
.agent-intro {
  background: var(--surface-raised); border: 1px solid var(--primary-border);
  border-left: 3px solid var(--primary); border-radius: var(--radius-md);
  padding: 1.25rem 1.5rem; margin-bottom: 1.5rem;
}
.agent-intro-title {
  font-size: 0.8125rem; font-weight: 700;
  color: var(--primary-deep); letter-spacing: 0.04em;
  margin-bottom: 0.5rem;
}
.agent-intro-text { font-size: 0.875rem; color: var(--text-secondary); line-height: 1.65; }
.agent-intro-text strong { color: var(--text-primary); }

/* ═══ TIER BADGES ════════════════════════════════════════════════════════ */
.tier-badge {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 3px 10px; border-radius: var(--r-xs);
  font-size: 0.6875rem; font-weight: 700; font-family: var(--font-body);
  letter-spacing: 0.04em; text-transform: uppercase; flex-shrink: 0;
}
.tier-A { background: var(--success-bg); color: var(--success); border: 1px solid rgba(6,166,114,0.25); }
.tier-B { background: var(--primary-muted); color: var(--primary-deep); border: 1px solid var(--primary-border); }
.tier-C { background: var(--warning-bg); color: var(--warning); border: 1px solid rgba(199,118,9,0.25); }
.tier-D { background: var(--error-bg); color: var(--error); border: 1px solid rgba(208,59,71,0.25); }
.tier-unknown { background: var(--surface); color: var(--text-muted); border: 1px solid var(--surface-border); }

/* ═══ TRAIN CLIENTS PAGE ═════════════════════════════════════════════════ */
.client-card {
  background: var(--surface-raised); border: 1px solid var(--surface-border);
  border-radius: var(--r-md); padding: 1rem 1.25rem;
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; margin-bottom: 8px;
  transition: border-color 180ms ease;
}
.client-card:hover { border-color: var(--primary-border); }
.client-card-active {
  border-color: var(--primary) !important;
  background: linear-gradient(140deg, rgba(255,31,142,0.04), var(--surface-raised)) !important;
}
.client-name {
  font-family: 'Syne', sans-serif; font-size: 1rem; font-weight: 700;
  color: var(--text-primary); letter-spacing: -0.02em;
}
.client-meta { font-size: 0.75rem; color: var(--text-muted); margin-top: 2px; }
.active-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 99px;
  font-size: 0.6875rem; font-weight: 600;
  background: var(--primary-muted); color: var(--primary-deep);
  border: 1px solid var(--primary-border); flex-shrink: 0;
}
.style-guide-wrap {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--r-md); padding: 1.5rem; margin-bottom: 1.5rem;
}
.guide-question {
  font-size: 0.8125rem; color: var(--text-secondary);
  margin-bottom: 6px; padding-left: 12px;
  border-left: 2px solid var(--primary-border);
}
</style>
"""


def inject() -> None:
    """Inject the Augmentum light-mode design system into the current page."""
    st.html(_STYLES)
