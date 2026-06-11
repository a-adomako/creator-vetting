"""
pages/1_Vet_Creators.py — Run the vetting pipeline on a CSV of creators.

Upload a CSV → the pipeline fetches each creator's profile + reels from Modash,
transcribes the audio with Whisper, classifies the visual scenes with CLIP,
asks Claude to weigh each one against the agency rubric, then writes an
enriched CSV + per-creator JSON.
"""

import io
import logging
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Regex for the structured STEP|N/M|@username|label log lines emitted by
# pipeline.py. Parsed on the page side to drive the live progress bar and
# "right now" status caption — see _STATUS_RE usage in the polling loop.
_STATUS_RE = re.compile(r"STEP\|(\d+)/(\d+)\|@([^|]+)\|(.+?)$")

# Where Hugging Face caches Whisper + CLIP. Used to detect a first-run on
# this machine so we can warn upfront instead of mid-pipeline.
_HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
_WHISPER_CACHE_DIRS = {
    "tiny": _HF_CACHE / "models--Systran--faster-whisper-tiny",
    "base": _HF_CACHE / "models--Systran--faster-whisper-base",
    "small": _HF_CACHE / "models--Systran--faster-whisper-small",
}
_CLIP_CACHE_DIR = _HF_CACHE / "models--timm--vit_base_patch32_clip_224.openai"

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# ── Paths and imports ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui_styles import inject as inject_styles

st.set_page_config(page_title="Vet Creators — CreatorVetter", layout="wide")
inject_styles()

INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Page header ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="page-header">
  <div class="page-title">Vet Creators</div>
  <div class="page-subtitle">
    Upload a CSV of Instagram creators. The pipeline downloads each creator's
    profile data and recent reels from Modash, transcribes the audio locally
    with Whisper, classifies what's in the videos using CLIP, then asks Claude
    to score every creator against the Augmentum vetting rubric. Output is an
    enriched CSV with engagement metrics, niche classification, an AI quality
    score, and a database-gate decision indicating whether the creator is safe
    to enter the central agency database.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar settings ─────────────────────────────────────────────────────────

st.sidebar.markdown(
    '<div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.10em;'
    'text-transform:uppercase;color:#5A5A60;margin-bottom:8px;">'
    'Vetting settings</div>'
    '<div style="font-size:0.75rem;color:#5A5A60;line-height:1.55;margin-bottom:12px;">'
    'These choices apply to the next pipeline run only. Defaults work for most cases.'
    '</div>',
    unsafe_allow_html=True,
)

reels_per_creator = st.sidebar.slider(
    "Reels to download and analyse per creator",
    min_value=1, max_value=7, value=3,
    help=(
        "More reels = more accurate niche classification and richer transcript, "
        "but slower. 3 is a good balance — covers ~90% of niche signal for ~30s "
        "of work per creator."
    ),
)

whisper_model = st.sidebar.selectbox(
    "Audio transcription model (Whisper)",
    options=["tiny", "base", "small"],
    index=1,
    help=(
        "tiny: ~5s per reel, lower accuracy. "
        "base: ~15s per reel, balanced (recommended). "
        "small: ~30s per reel, best for accented speech."
    ),
)

st.sidebar.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
st.sidebar.markdown(
    '<p style="font-size:0.75rem;color:#5A5A60;line-height:1.55;">'
    '<strong style="color:#1D1D1F;">First run on this machine</strong> downloads '
    'the Whisper model (~150 MB for base) and the CLIP visual model (~340 MB) '
    'into a local cache. Subsequent runs load in ~2 seconds.'
    '</p>',
    unsafe_allow_html=True,
)

# ── Step 1 — Upload ──────────────────────────────────────────────────────────

st.markdown("""
<div class="step-header">
  <div class="step-number">1</div>
  <div class="step-label">Upload a CSV of creators to vet</div>
</div>
<div class="step-desc">
  Your CSV needs at least one column called <code>Profile URL</code>
  (full Instagram URLs) or <code>Username</code> (handles, with or without @).
  Every other column is preserved unchanged in the enriched output. Need a
  template? Download the sample below.
</div>
""", unsafe_allow_html=True)

# Sample CSV download
_sample_csv = (
    "Profile URL,Username,First Name\n"
    "https://www.instagram.com/emmajanegallagher/,emmajanegallagher,Emma\n"
    "https://www.instagram.com/julieyourfeelgoodgirl/,julieyourfeelgoodgirl,Julie\n"
    ",katherinemay_,Katherine\n"
)
st.download_button(
    label="Download sample CSV (3 example rows you can edit)",
    data=_sample_csv.encode("utf-8"),
    file_name="creator_vetter_sample_input.csv",
    mime="text/csv",
    type="secondary",
)

st.markdown('<div style="height:0.75rem;"></div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Drop a CSV here (or click to browse) — the pipeline will save it to the input folder",
    type="csv",
    label_visibility="visible",
)

saved_input_path: Path | None = None

if uploaded_file is not None:
    import pandas as pd
    saved_input_path = INPUT_DIR / uploaded_file.name
    try:
        saved_input_path.write_bytes(uploaded_file.getvalue())
    except PermissionError:
        st.warning(
            "Could not save the uploaded file — it may already be open in another "
            "program. Close it and re-upload."
        )
        saved_input_path = None
    except Exception as e:
        st.warning(f"Could not save the uploaded file: {e}")
        saved_input_path = None

    if saved_input_path is not None:
        try:
            preview_df = pd.read_csv(saved_input_path)
            st.success(
                f"Saved to `{saved_input_path.relative_to(PROJECT_ROOT)}` — "
                f"{len(preview_df):,} rows detected, showing first 5 below."
            )
            st.dataframe(preview_df.head(5), use_container_width=True)
        except Exception as e:
            st.warning(
                f"Saved the file, but could not parse it as CSV: {e}. "
                "Check that the file is a valid CSV with column headers in the first row."
            )
            saved_input_path = None

# ── Step 2 — Confirm settings and run ────────────────────────────────────────

st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="step-header">
  <div class="step-number">2</div>
  <div class="step-label">Confirm settings and start the vetting run</div>
</div>
<div class="step-desc">
  Review the summary below. When you click <strong>Start vetting run</strong>,
  the pipeline begins in the background and live progress streams below.
</div>
""", unsafe_allow_html=True)

if saved_input_path is None:
    st.info(
        "Upload a creator CSV above to continue. Without a CSV the pipeline "
        "has nothing to vet."
    )
    st.stop()

modash_key = os.getenv("MODASH_API_KEY", "")
if not modash_key:
    st.error(
        "**MODASH_API_KEY is not set** — the pipeline cannot fetch Instagram "
        "profile data without it. Add the key to your `.env` file at the project "
        "root (`MODASH_API_KEY=your_key_here`) and refresh the page."
    )
    st.stop()

settings_cols = st.columns(3, gap="small")
with settings_cols[0]:
    st.markdown(f"""
    <div class="completion-stat">
      <div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Input file</div>
      <div style="font-size:0.9375rem;font-weight:600;color:#1D1D1F;margin-top:4px;word-break:break-all;">{saved_input_path.name}</div>
    </div>
    """, unsafe_allow_html=True)
with settings_cols[1]:
    st.markdown(f"""
    <div class="completion-stat">
      <div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Reels per creator</div>
      <div style="font-size:0.9375rem;font-weight:600;color:#1D1D1F;margin-top:4px;">{reels_per_creator} (set in sidebar)</div>
    </div>
    """, unsafe_allow_html=True)
with settings_cols[2]:
    st.markdown(f"""
    <div class="completion-stat">
      <div style="font-size:0.6875rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Whisper model</div>
      <div style="font-size:0.9375rem;font-weight:600;color:#1D1D1F;margin-top:4px;">{whisper_model} (set in sidebar)</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div style="height:1.25rem;"></div>', unsafe_allow_html=True)

# ── First-run model download check ───────────────────────────────────────────
# If the Whisper or CLIP weights aren't cached yet, warn upfront so the user
# isn't confused by a mid-pipeline pause while ~490 MB of model weights stream
# in from Hugging Face.
_whisper_cached = _WHISPER_CACHE_DIRS.get(whisper_model, Path("/nonexistent")).exists()
_clip_cached = _CLIP_CACHE_DIR.exists()
if not (_whisper_cached and _clip_cached):
    missing = []
    if not _whisper_cached:
        missing.append(f"Whisper `{whisper_model}` (~150 MB)")
    if not _clip_cached:
        missing.append("CLIP visual model (~340 MB)")
    st.warning(
        "**First run on this machine — model download required before vetting can start.** "
        f"The pipeline will fetch {', '.join(missing)} from Hugging Face into "
        f"`~/.cache/huggingface/hub` the moment it needs them. This is a one-time cost; "
        f"subsequent runs skip it and load in ~2 seconds. The progress bar may sit on the "
        f"first creator while this downloads."
    )

run_clicked = st.button(
    "Start vetting run (downloads reels, transcribes, scores against rubric)",
    type="primary",
    use_container_width=True,
)

if not run_clicked:
    st.markdown(
        '<p style="font-size:0.8125rem;color:#5A5A60;margin-top:0.75rem;text-align:center;">'
        'Click the button above when you\'re ready. The run typically takes '
        '15–60 seconds per creator depending on settings.'
        '</p>',
        unsafe_allow_html=True,
    )
    st.stop()

# ── Pipeline execution ───────────────────────────────────────────────────────

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = OUTPUT_DIR / f"enriched_{timestamp}.csv"

log_queue: queue.Queue = queue.Queue()
result_holder: dict = {"path": None, "error": None, "done": False}


class QueueHandler(logging.Handler):
    """Sends log records into a queue.Queue so the main thread can poll them."""
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
    def emit(self, record: logging.LogRecord):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


def run_pipeline_thread(input_path: str, out_path: str, reels: int, model: str):
    """Target for the background thread. Patches logging then runs Pipeline."""
    root_logger = logging.getLogger()
    handler = QueueHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(levelname)s  %(name)s — %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    try:
        import yaml
        config_path = PROJECT_ROOT / "config" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        config.setdefault("modash", {})["reels_per_creator"] = reels
        config.setdefault("whisper", {})["model_size"] = model

        temp_config_path = PROJECT_ROOT / "config" / "_ui_config.yaml"
        with open(temp_config_path, "w") as f:
            yaml.dump(config, f)

        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        from src.pipeline import Pipeline

        pipeline = Pipeline(config_path=str(temp_config_path))
        result_path = pipeline.run(input_path=input_path, output_path=out_path)
        result_holder["path"] = str(result_path)

    except Exception as exc:
        result_holder["error"] = str(exc)
        log_queue.put(f"ERROR  pipeline — {exc}")

    finally:
        root_logger.removeHandler(handler)
        temp_config = PROJECT_ROOT / "config" / "_ui_config.yaml"
        if temp_config.exists():
            temp_config.unlink()
        result_holder["done"] = True


thread = threading.Thread(
    target=run_pipeline_thread,
    args=(str(saved_input_path), str(output_path), reels_per_creator, whisper_model),
    daemon=True,
)
thread.start()

# ── Step 3 — Live progress ───────────────────────────────────────────────────

st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="step-header">
  <div class="step-number">3</div>
  <div class="step-label">Live progress (this updates every 0.3 seconds)</div>
</div>
<div class="step-desc">
  The pipeline writes one row to the output CSV per creator as they finish,
  so a crashed run still leaves usable partial output. If this is the very
  first run on this machine, expect a one-time pause while Whisper (~150 MB)
  and CLIP (~340 MB) models download from Hugging Face.
</div>
""", unsafe_allow_html=True)

progress_bar = st.progress(0, text="Starting pipeline…")
status_caption = st.empty()  # live "right now" line — see polling loop below
log_display = st.empty()
log_lines: list[str] = []
status_message = st.empty()

try:
    import pandas as pd
    total_creators = len(pd.read_csv(saved_input_path))
except Exception:
    total_creators = 0

# Driven by the STEP|N/M|@user|label log lines emitted by pipeline.py — the
# outer bar tracks creator N of M, the caption shows exactly what's happening
# right now for that creator (downloading reels / transcribing / scoring with
# Claude / etc.) so a long Whisper transcription doesn't look like a hang.
current_creator_idx = 0
current_username = ""
current_step = "Waiting for first creator…"
model_download_notified = False

log_expander = st.expander(
    "View detailed log output (every step the pipeline takes — useful when debugging)",
    expanded=False,
)

while not result_holder["done"]:
    while True:
        try:
            line = log_queue.get_nowait()
            log_lines.append(line)
            m = _STATUS_RE.search(line)
            if m:
                current_creator_idx = int(m.group(1))
                # m.group(2) is the total — we trust the CSV row count instead
                current_username = m.group(3)
                current_step = m.group(4).strip()
            # Surface model download as its own status (covers any user who
            # somehow gets here without the upfront warning firing).
            if not model_download_notified and (
                "Loading faster-whisper" in line or "Loading CLIP model" in line
            ):
                status_message.info(
                    "**First-run model download in progress.** Whisper and CLIP are "
                    "streaming from Hugging Face into `~/.cache/huggingface/hub`. "
                    "This is a one-time cost — subsequent runs skip this step."
                )
                model_download_notified = True
        except queue.Empty:
            break

    if total_creators > 0:
        pct = min(int(current_creator_idx / total_creators * 100), 99)
        progress_bar.progress(
            pct,
            text=f"Creator {current_creator_idx} of {total_creators} ({pct}%)",
        )
    else:
        progress_bar.progress(0, text="Running…")

    # Live "right now" line — what step the current creator is on. Keeps the
    # user oriented during a long Whisper pass on a single creator.
    if current_username:
        status_caption.markdown(
            f"<div style='font-size:0.875rem;color:#5A5A60;margin-top:-0.5rem;"
            f"margin-bottom:0.5rem;'><strong>Right now:</strong> "
            f"@{current_username} — {current_step}</div>",
            unsafe_allow_html=True,
        )
    else:
        status_caption.markdown(
            f"<div style='font-size:0.875rem;color:#5A5A60;margin-top:-0.5rem;"
            f"margin-bottom:0.5rem;'><strong>Right now:</strong> {current_step}</div>",
            unsafe_allow_html=True,
        )

    display_text = "\n".join(log_lines[-30:]) if log_lines else "Waiting for first log line from the pipeline…"
    with log_expander:
        log_display.code(display_text, language="text")

    time.sleep(0.3)

while True:
    try:
        line = log_queue.get_nowait()
        log_lines.append(line)
    except queue.Empty:
        break

with log_expander:
    log_display.code("\n".join(log_lines[-50:]), language="text")

# ── Step 4 — Completion ──────────────────────────────────────────────────────

if result_holder["error"]:
    progress_bar.progress(100, text="Pipeline failed.")
    st.error(
        f"**The pipeline run failed:** {result_holder['error']}\n\n"
        f"Open the log expander above to see the last log lines. Common causes: "
        f"a stale Modash API key, an invalid input CSV column, or ffmpeg not being "
        f"on PATH (required for audio transcription)."
    )
else:
    progress_bar.progress(100, text="Vetting complete — see results below.")
    out = result_holder["path"] or str(output_path)

    st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="step-header">
      <div class="step-number done">✓</div>
      <div class="step-label">Vetting complete — enriched CSV written to disk</div>
    </div>
    """, unsafe_allow_html=True)

    stat_col1, stat_col2 = st.columns(2, gap="small")
    with stat_col1:
        st.metric(
            "Creators in this run",
            f"{total_creators:,}" if total_creators else "—",
        )
    with stat_col2:
        st.metric("Output filename", Path(out).name)

    st.success(
        f"Enriched CSV saved to `{out}`. Per-creator JSON profiles "
        f"(full transcripts and raw scores) are in `output/profiles/`."
    )

    # In-page download — no need to dig into the filesystem.
    out_path_obj = Path(out)
    if out_path_obj.exists():
        try:
            csv_bytes = out_path_obj.read_bytes()
            st.download_button(
                label=f"Download enriched CSV ({out_path_obj.name})",
                data=csv_bytes,
                file_name=out_path_obj.name,
                mime="text/csv",
                type="primary",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(
                f"Couldn't load the CSV for an in-page download: {exc}. "
                f"It's still on disk at `{out}` — open it directly."
            )

    st.markdown('<div style="height:1.25rem;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="step-header">
      <div class="step-number">5</div>
      <div class="step-label">Next step — pick the best creators for a specific client</div>
    </div>
    <div class="step-desc">
      Head to the <strong>Build Shortlist</strong> page to filter and rank this
      CSV against a client's brief. Claude will read each creator's full profile
      and only surface the ones that fit the client's brand context, target
      niches, and scoring style.
    </div>
    """, unsafe_allow_html=True)

# ── Navigation footer ───────────────────────────────────────────────────────

st.markdown('<div style="height:2.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="border-top:1px solid #E5E5EA;padding-top:1.25rem;">
  <span style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Continue to</span>
</div>
""", unsafe_allow_html=True)
_nc1, _nc2 = st.columns([2, 1])
with _nc1:
    st.page_link(
        "pages/2_Build_Shortlist.py",
        label="Build Shortlist — filter this CSV against a specific client's brief",
        icon="🎯",
    )
with _nc2:
    st.page_link(
        "pages/3_Train_Clients.py",
        label="Train Clients — manage client briefs",
        icon="✏️",
    )
