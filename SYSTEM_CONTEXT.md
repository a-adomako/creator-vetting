# SYSTEM_CONTEXT.md — CreatorVetter

> Hand-off document. Comprehensive enough that an LLM picking this up cold can
> understand what the system does, why it's built the way it is, what has
> shipped, what hasn't, and where every important piece of code lives.
> If anything in this doc contradicts the code, the code wins — update the doc.
>
> Last refreshed: 2026-06-11.

---

## 1. What this system is, in one paragraph

CreatorVetter is Augmentum Media's internal tool for evaluating Instagram
creators at scale. You upload a CSV of usernames or Profile URLs. The pipeline
pulls each creator's profile data and recent reels via the Modash Raw API,
downloads the reel videos, transcribes them locally with faster-whisper,
classifies what's on screen using CLIP, fuses transcript + visual signals into
niche scores, computes engagement / audience / quality / tier, asks Claude to
re-evaluate each creator against Augmentum's vetting rubric, and runs a
quality gate that decides whether each creator is universally disqualified
(adult content, MLM, hate speech, etc.) or safe to enter Augmentum's central
agency database. The enriched CSV plus per-creator JSON profiles land in
`output/`. A Streamlit UI on top wraps three pages: Vet Creators (run the
pipeline), Build Shortlist (filter the enriched CSV against a specific
client's brief), and Train Clients (manage per-client brand context and
scoring style). A one-off script pushes per-client brand context into the
central Supabase database.

The product positioning: **10k+ creators per week**, **all heavy work runs
locally** (no per-frame paid vision APIs), and one cheap LLM call per creator.

**As of 2026-06-11 there are TWO pipelines.** The original (above, "v1") still
works and powers the Streamlit UI. The new **campaign vetting flow ("v2",
`run_campaign.py` + `src/vetter.py`)** is the redesign built from first
principles after the Thrivin run exposed three failures in v1 (lyric
transcripts driving wrong rejections, no-data creators being scored as
"unsafe", and bloated essay CSVs — see §5a and the 2026-06-11 decision log
entries). v2 is one motion: **CSV + campaign spec → shortlist.csv /
rejected.csv / review.csv**, with deterministic hard filters first and ONE
structured Claude call (bio + captions + transcripts + sampled reel frames
via Haiku vision) per surviving creator. v2 is the recommended flow for
campaign work; v1 remains the path for client-blind bulk enrichment until
v2 takes over the UI.

---

## 2. End-to-end pipeline flow

```
Input CSV (Profile URL and/or Username, plus any other columns)
   │
   ▼
[Pipeline.run() in src/pipeline.py]
   │
   ├─► src/fetcher.py — extract_username() (URL or @handle → lowercase username)
   │
   ├─► src/fetcher.py — ModashFetcher.fetch_profiles()
   │       Modash Raw API:
   │         GET /v1/raw/ig/user-info    → profile metadata
   │         GET /v1/raw/ig/user-reels   → recent reels (videoUrl, like_count, ...)
   │       Rate-limited (2 req/sec default), normalises snake_case → camelCase
   │
   ▼
For each profile (tqdm loop):
   │
   ├─► src/scorer.py — score_profile()
   │       engagement rate, posts/30d, days_since_last_post,
   │       audience_quality_score, overall_quality_score,
   │       tier (A/B/C/D), flags
   │
   ├─► Pipeline._process_creator():
   │       1. extract_reel_urls (top N reels, default 3 from the UI)
   │       2. VideoDownloader.download_reels  (4-worker thread pool, 200 MB cap/video)
   │       3. Transcriber.transcribe_batch    (faster-whisper, ffmpeg-extracted WAV)
   │       4. VisualAnalyzer.analyze_batch    (CLIP per-frame + OpenCV blur/brightness)
   │       5. NicheAnalyzer.analyze           (fuses CLIP 60% + transcript 40%)
   │       6. cleanup() in `finally` — videos deleted from temp/
   │
   ├─► (Optional) src/llm_analyzer.py — LLMAnalyzer.analyze()
   │       Sends transcript + scenes + metrics to Claude Haiku 4.5.
   │       Injects knowledge/expertise.md + active client's calibration files.
   │       Returns llm_primary_niche, llm_brand_fit_score, llm_authenticity,
   │       llm_content_consistency, llm_brand_safety, llm_production_quality_score,
   │       llm_recommendation (yes/maybe/no), llm_reasoning, llm_strengths,
   │       llm_concerns, llm_quality_score (mean of 4 dimensions).
   │
   ├─► src/quality_gate.py — evaluate()
   │       Universal-disqualifier check. Reads only llm_concerns + flags.
   │       Negation-aware. Sets gate_decision, gate_reason, push_to_spine.
   │       (Full details in §5.)
   │
   ▼
Write row to output/enriched_<timestamp>.csv  (incremental, flushed per row)
Write full JSON to output/profiles/<username>.json  (richer than the CSV — full transcripts, raw CLIP scores per reel)
```

**Key invariant:** CSV is flushed after every row, so a crashed mid-run still
leaves usable output. The header is written on the first row using
`csv.DictWriter` so all rows share the same column order.

---

## 2a. Campaign vetting flow (v2) — `run_campaign.py`

```
Input CSV + campaigns/<name>.yaml (campaign spec)
   │
   ▼
[CampaignVetter.run() in src/vetter.py]
   │
   ├─► Modash fetch (fetcher.py — now also returns bio + per-post captions)
   │
   ├─► src/scorer.py — score_profile()           (unchanged from v1)
   │
   ├─► STAGE 1 — HARD FILTERS (src/campaign.py, deterministic, free)
   │       private / below follower min / above VIP ceiling / engagement
   │       floor / dormancy. Fails here NEVER cost a download or LLM call.
   │       VIP-tier creators route to review.csv, not rejected.csv.
   │
   ├─► STAGE 2 — CONTENT GATHERING (survivors only)
   │       download reels → Whisper transcribe_detailed() (adds per-reel
   │       speech_confidence hint) → sample 2 frames/reel as base64 JPEG
   │       (src/frames.py, ≤8 frames, 512px, q70 ≈ 1–2¢/creator on Haiku).
   │       Zero usable signal (no bio, captions, transcript, frames) →
   │       review.csv as no_content. NEVER scored, NEVER marked unsafe.
   │
   ├─► STAGE 3 — ONE STRUCTURED JUDGMENT CALL (Claude Haiku vision)
   │       System: knowledge/expertise.md + client folder calibration +
   │       campaign brief/judgment_notes + EVIDENCE RULES (lyrics ≠ creator).
   │       User: profile facts, bio, captions, labeled transcripts, frames.
   │       Forced tool_choice → record_vetting_verdict — schema-valid output,
   │       no JSON parsing, no keyword gate. Verdict: niche, fit score 0-100,
   │       approve/reject/needs_review, ≤30-word reason, ≤40-word evidence,
   │       universal_disqualifiers (enum list), visual_flags (none/
   │       suggestive/nsfw), spoken_content_is_music (bool).
   │
   ▼
output/campaigns/<name>_<timestamp>/
   ├── shortlist.csv    approved only — 11 lean columns, one-line reasons
   ├── rejected.csv     stage + category + reason (hard_filter | judgment | gate)
   ├── review.csv       VIP tier, no-data, fetch failures, genuine ambiguity
   └── profiles/<username>.json   full evidence per judged creator
```

**Why v2 exists** — three failures observed in the 2026-06-07 Thrivin run:

1. **Lyric transcripts drove wrong universal rejections.** Whisper
   transcribes the licensed/trending music on reels exactly like speech.
   @aprilalexander was gate-blocked for a "racial slur" that was a song
   lyric; @richardbromilowpt (a verified PT) was rejected as a "music
   creator". Both were approved on human review. v2 defends three ways:
   captions + bio (the creator's own words) are first-class inputs, frames
   give direct visual evidence, and the prompt's EVIDENCE RULES forbid
   attributing lyric content to the creator. The verdict's
   `spoken_content_is_music` flag makes the detection auditable.
2. **Missing data was recorded as "unsafe".** No-reel accounts got
   llm_brand_safety=0 → gate-rejected as `rejected_brand_safety_critical`.
   In v2, no-data creators are caught by hard filters or the no_content
   check and routed to review — they never reach a safety judgment.
3. **The keyword gate still false-positived** (@jasmijnvz_ rejected for
   "MLM" inside a *cannot-assess-MLM* concern, slipping past the negation
   lookback). v2 has no keyword scan: `universal_disqualifiers` comes back
   as a schema-enforced enum list and `push_to_spine = (list is empty)`.

**Validation (2026-06-11):** hard-filter replay over the 38-creator Thrivin
run matched the human pass (no-data zombies rejected on metrics, katb_fit +
charliekamale routed to VIP review). Live re-vet of April + Richard: no
disqualifiers, music correctly flagged, rejections (if any) now cite real
bio/caption/frame evidence and are tunable via the campaign YAML.

**Campaign spec** (`campaigns/<name>.yaml`): `name`, `brief`,
`target_niches`, `judgment_notes`, optional `client_folder` (injects
`knowledge/clients/<folder>/` calibration), and `hard_filters:`
(`min_followers`, `vip_review_above`, `min_engagement_pct`,
`max_days_since_last_post`, `exclude_private`). See `campaigns/thrivin.yaml`
for a fully-worked example built from the Thrivin client knowledge.

**Vetting cache (added 2026-06-11)** — [src/vetting_cache.py](src/vetting_cache.py),
SQLite at `output/vetting_cache.db`. Before fetching anything, the run checks
whether each creator was already LLM-judged for THIS campaign within
`campaign_vetting.cache_max_age_days` (default 183 ≈ 6 months). Hits replay
the stored verdict into the right CSV with `source=cached:<date>` — zero
Modash quota, zero LLM spend, instant. Only judged outcomes are cached;
hard-filter results never are (metrics drift and re-checking is free). The
cache self-seeds from existing `output/campaigns/*/profiles/*.json` on first
open. Bypass: `--no-cache` on the CLI or untick "Reuse verdicts" in the UI.
Verified: re-running April + Richard hit the cache 2/2 with 0 LLM calls.

---

## 3. File map

```
creator_vetter/
├── Homepage.py                         # Streamlit entry point — appears as "Homepage" in the sidebar nav
├── run.py                              # CLI entry — runs the v1 pipeline on a CSV
├── run_campaign.py                     # NEW — CLI entry for the v2 campaign vetting flow (§2a)
├── push_run_to_spine.py                # NEW — push an existing run's judged creators to the spine
├── agent.py                            # Legacy CLI conversational agent over an enriched CSV (still works)
│
├── campaigns/                          # NEW — campaign spec YAMLs for the v2 flow
│   └── thrivin.yaml                    # Thrivin Gymwear spec (10k floor, 1% ER, 250k VIP ceiling)
│
├── pages/                              # Streamlit subpages (simplified 2026-06-11 — two pages)
│   ├── 1_Vet_for_Campaign.py           # v2 flow: campaign + CSV → shortlist/rejected/review
│   ├── 2_Train_Clients.py              # Client briefs + scoring style + Evidence & sources tab
│   └── 3_Calibration_Deck.py           # Swipe deck: human labels, agreement rate, spine decisions
│
├── src/
│   ├── __init__.py
│   ├── pipeline.py                     # Pipeline class — v1 orchestrator
│   ├── vetter.py                       # NEW — CampaignVetter, v2 orchestrator (§2a)
│   ├── campaign.py                     # NEW — CampaignSpec + deterministic hard filters
│   ├── frames.py                       # NEW — reel frame sampling → base64 JPEG for vision
│   ├── fetcher.py                      # ModashFetcher + extract_username() (now returns bio + captions)
│   ├── downloader.py                   # VideoDownloader — parallel reel downloads
│   ├── transcriber.py                  # Transcriber — faster-whisper local (+ transcribe_detailed with speech_confidence)
│   ├── visual.py                       # VisualAnalyzer — CLIP + OpenCV (v1 only)
│   ├── analyzer.py                     # NicheAnalyzer — fuses transcript + visual (v1 only)
│   ├── scorer.py                       # score_profile() — engagement/quality/tier (shared v1+v2)
│   ├── llm_analyzer.py                 # LLMAnalyzer — Claude with calibration injection (v1; _load_calibration shared with v2)
│   ├── llm_client.py                   # Anthropic + Ollama wrappers (+ tool_choice for forced structured output)
│   ├── vetting_cache.py                # NEW — cross-run verdict cache (6-month TTL, see §2a)
│   ├── spine.py                        # NEW — spine push: /upsert + phantom run + creator_vetting rows
│   ├── calibration.py                  # NEW — calibration deck candidates + label store
│   ├── evidence.py                     # NEW — evidence uploads/fetch (site, Slack, Fathom) + distillation
│   ├── corrections.py                  # NEW — human corrections → corrections.md + cache invalidation
│   ├── quality_gate.py                 # Keyword-scan disqualifier filter (v1 only — v2 uses structured enums, see §2a)
│   ├── modash.py                       # Modash discovery wrapper (used by legacy agent.py)
│   ├── influencers_club.py             # Influencers.Club discovery wrapper (legacy)
│   ├── agent_tools.py                  # Tool functions exposed to the conversational CLI agent
│   ├── ui_styles.py                    # NEW — Augmentum light-mode design system (inject() helper)
│   └── ui_labels.py                    # NEW — Plain-language labels for tier/gate/recommendation/flags
│
├── scripts/
│   └── sync_brand_context_to_spine.py  # NEW — push knowledge/clients/* → Supabase client_brand_context (versioned)
│
├── config/
│   └── config.yaml                     # All thresholds, niches, CLIP prompts, gate patterns
│
├── knowledge/
│   ├── expertise.md                    # Global Augmentum vetting rubric (Hard / Soft / Flag-for-review)
│   ├── clients/                        # Per-client training data
│   │   ├── AG1/profile.yaml            # (empty)
│   │   ├── Elavate/profile.yaml + my_style.md
│   │   └── Kloris/profile.yaml + my_style.md  (filled this session — v1 also in spine DB)
│   └── briefs/                         # Campaign brief markdown for the legacy agent.py flow
│       └── test_wellness.md
│
├── memory/                             # Project's own decision log
│   ├── status.md                       # Current phase + what's next
│   ├── decisions.md                    # Chronological decisions + rationale
│   ├── preferences.md                  # Project-wide Claude preferences
│   └── contacts.md                     # Empty stub
│
├── input/                              # User-uploaded CSVs (cleaned 2026-06-07)
├── output/                             # Generated artefacts
│   ├── enriched_<timestamp>.csv        # Per-run enriched output (v1)
│   ├── campaigns/<name>_<ts>/          # v2 run outputs: shortlist/rejected/review.csv + profiles/*.json
│   ├── vetting_cache.db                # Cross-run verdict cache for v2 (6-month TTL)
│   ├── profiles/<username>.json        # Per-creator JSON (full transcripts + raw CLIP) (v1)
│   ├── shortlists/                     # Agent-exported shortlists (legacy CLI)
│   ├── creators.db                     # SQLite cross-run store (7 MB — creator_store.py source is missing, see §12)
│   └── queued/                         # CSVs queued by the legacy agent for the next pipeline run
│
├── temp/                               # Working dir for reel videos (auto-deleted per creator, .gitkeep only)
├── to-archive/                         # Holding pen for stale artefacts (~152 MB — see to-archive/README.md)
│   ├── legacy-ui/                      # 1_Vet_Creators.py + 2_Build_Shortlist.py (v1 pages, retired 2026-06-11)
│   ├── README.md                       # Explains what's in here and when it's safe to delete
│   ├── empty-runs/                     # 0-byte + 2-byte enriched_*.csv from crashed runs
│   ├── superseded-inputs/              # .xlsx duplicates + generic test CSVs
│   ├── reference/                      # creator_vetting_rubric.docx (origin of expertise.md)
│   ├── duplicate-assets/               # Unused logo duplicate
│   └── orphaned-reels/                 # .mp4 files from crashed runs (149 MB)
│
├── .gitignore                          # Excludes secrets, generated artefacts, OS junk
├── .streamlit/config.toml              # Light theme base
├── .env / .env.example                 # API keys
├── Dockerfile                          # python:3.11-slim + ffmpeg, runs Homepage.py on 8501
├── docker-compose.yml                  # Mounts ./input, ./output, ./.env
├── requirements.txt
├── launch.bat                          # Windows launcher (hardcoded path — needs editing per machine)
├── logo.jpg                            # Augmentum brand mark (loaded by Homepage.py sidebar)
├── CLAUDE.md                           # Behaviour rules only (project facts live in this file)
├── MEMORY.md                           # Index into memory/
└── SYSTEM_CONTEXT.md                   # This document
```

---

## 4. Configuration system — `config/config.yaml`

This is the **single source of truth** for tuning. Editing code instead of
config is a documented anti-pattern. The file is loaded once at
`Pipeline.__init__` and passed through to every component.

### Top-level keys

| Key | What it controls |
|---|---|
| `input_columns` | Which CSV headers map to `url` / `username`. Defaults: `Profile URL`, `Username`. |
| `modash` | `base_url`, `reels_per_creator` (default 7, UI overrides to 3), `requests_per_second` (rate limit). |
| `whisper` | `model_size` (tiny / base / small / medium / large), `language` (null = auto), `device` (auto). |
| `clip` | `model` (ViT-B-32), `pretrained` (openai), `frames_per_second` (0.5 = 1 frame every 2s). |
| `clip_prompts` | Per-niche CLIP zero-shot text prompts. Six niches: Health & Wellness, Fitness, Fashion, Lifestyle, Beauty & Skincare, Food & Beverage. |
| `niche_keywords` | Per-niche transcript keywords. Single words use word-boundary regex; multi-word phrases use substring matching. |
| `analysis_weights` | `visual: 0.6, transcript: 0.4` — must sum to 1.0. |
| `target_niches` | Verticals `brand_fit_score` weights against. |
| `engagement_thresholds` | excellent / good / average % cut-offs. |
| `frequency_thresholds` | active / occasional posts-per-30-days cut-offs. |
| `recency_flag_days` | Days since last post before `stale_<N>d` flag. |
| `quality_weights` | engagement / audience / frequency / recency contributions to `overall_quality_score`. Must sum to 1.0. |
| `tier_thresholds` | Score floors for tier A / B / C. Below C = D. |
| `llm_analysis` | `enabled: true`, default `brand_context`, default `target_niches`. Skipped silently if `ANTHROPIC_API_KEY` is missing. |
| `quality_gate` | Patterns and thresholds for the v1 keyword-scan disqualifier filter. Full details in §5. Not used by v2. |
| `campaign_vetting` | **NEW** — v2 flow settings: `model` (null = LLM_MODEL env), `reels_per_creator` (3), `frames_per_reel` (2), `max_total_frames` (8), `max_image_dim` (512), `jpeg_quality` (70), `cache_enabled` (true), `cache_max_age_days` (183). |

### Per-run overrides

The Vet Creators page writes a temporary `config/_ui_config.yaml` for each run
that overrides `modash.reels_per_creator` and `whisper.model_size` based on
the sidebar sliders. The file is deleted in the pipeline's `finally` block.

---

## 5. The quality gate — universal disqualifiers vs brand-fit mismatches

> **v1 only.** The v2 campaign flow does not run this gate — it gets
> universal disqualifiers back from the judgment call as a schema-enforced
> enum list (§2a), which eliminates the keyword-matching false-positive
> class entirely (two were observed in a single 38-creator run; see the
> 2026-06-11 decision log). The universal-vs-brand-fit *principle* below
> still governs both flows.

Lives at [src/quality_gate.py](src/quality_gate.py). All patterns and
thresholds in `config/config.yaml` → `quality_gate:`. Runs after the LLM
analysis merges into the row and before the row is written to CSV.

### Why it exists

The principle: **a creator who is universally wrong for the agency** (adult
content, MLM, anti-vax advocacy, hate speech, religious extremism) should not
enter the central Augmentum database. A creator who is **wrong for this
specific client** (wrong niche, wrong demographic) is per-client knowledge —
they may be right for a different client and should still be saved centrally.

The gate enforces this split. Failing the gate = `push_to_spine: False`,
meaning the row stays in the local enriched CSV but will not be sent to the
central Supabase DB (once §10 Option A ships). Passing the gate = the creator
is centrally storable; the per-client decision is recorded separately in
Build Shortlist.

### Output columns

| Column | Values |
|---|---|
| `gate_decision` | `passes` or `rejected_<category>` (e.g. `rejected_adult_sexual_content`, `rejected_mlm`, `rejected_brand_safety_critical`, `rejected_multi_signal_floor`) |
| `gate_reason` | Human-readable explanation — what matched and why |
| `push_to_spine` | Boolean — `True` means safe for central DB, `False` means hold back |

### Decision rules (first hit wins)

1. **Recommendation exclusion** — if `llm_recommendation` is in
   `quality_gate.exclude_recommendations`. **Default: empty list.** A `"no"`
   recommendation is treated as client-specific brand fit, not universal
   disqualification, so it does not block centrally.
2. **Brand-safety floor** — if `llm_brand_safety < min_brand_safety_floor`
   (default `30`). Claude saw something serious we didn't enumerate.
3. **Keyword scan** — case-insensitive substring match across the union of
   `llm_concerns` + `flags`. Patterns are grouped by category in config
   (see `universal_reject_patterns`). The first matching category wins.
4. **Multi-signal floor** — defence-in-depth catch-all. Fires only if
   `brand_safety < 50` AND `tier == "D"` AND `llm_recommendation == "no"`
   simultaneously. Each leg is individually configurable.

If nothing fires, the row gets `gate_decision="passes"` and
`push_to_spine=True`.

### Anti-false-positive design (v2 — shipped 2026-06-05)

The first version of the gate (shipped earlier this session) produced ~5
false positives per 75-creator batch. Root cause: keyword scanning hit
**negated mentions** like *"no MLM detected"*, *"cannot assess MLM
involvement"*, *"passes hate-speech screening — no adult content, hate
speech, or wellness red flags detected"*. Two fixes shipped together:

1. **Concerns-only scan.** The haystack now includes only `llm_concerns`
   (where Claude lists *detected* issues) and `flags`. It deliberately
   excludes `llm_reasoning` and `llm_content_summary`, both of which discuss
   absence as much as presence and were the dominant false-positive source.
2. **Negation detection.** Within `llm_concerns`, any pattern preceded by
   one of `_NEGATION_PHRASES` within 50 characters is treated as Claude
   describing an absence and ignored. Phrase list includes *no, not,
   without, cannot, can't, didn't, doesn't, free of, rule out, ruled out,
   verify for, assess for, no evidence of, no detected, passes, passed,
   screened, screening, lacks, lacking, not detected, not present, cannot
   rule, could not verify*.

Both implementations live in [src/quality_gate.py](src/quality_gate.py).
The fix was verified against all 6 real false positives from a 75-creator
test run plus 3 real true positives; 9/9 behave correctly.

### Mapping to the global rubric

Every "Hard Reject" row in `knowledge/expertise.md` maps to a category in
`universal_reject_patterns`. "Soft Reject" rows deliberately do not — those
are client-overridable per the rubric, so they belong in per-client scoring
style, not in the universal gate.

### End-of-run summary

Pipeline prints at completion:

```
Gate     : 70 would be pushed to central DB, 5 held back (93% pass)
  • rejected_brand_safety_critical: 3
  • rejected_multi_signal_floor: 2
```

---

## 6. Knowledge & per-client training

### Three layers of context

Injected into every per-client LLM call ([src/llm_analyzer.py](src/llm_analyzer.py)):

1. **Global rubric** — `knowledge/expertise.md`. Augmentum-wide vetting
   standards. Six categories (adult, wellness red flags, political,
   general safety, audience quality, client-specific) at three severity
   levels (Hard reject, Soft reject, Flag for review).
2. **Per-client brand context** — `knowledge/clients/<name>/profile.yaml`.
   Keys: `brand_context` (free text), `target_niches` (list),
   `scoring_notes` (free text — hard rules specific to this client).
3. **Per-client scoring style** — `knowledge/clients/<name>/my_style.md`.
   Free-form markdown. The user's personal "how I'd evaluate creators for
   this client" guide.
4. **(Optional) corrections.md + good_examples.md** — same folder.
   Loaded by `_load_calibration()` if present. **No UI yet to author
   these** — gap noted in §12.

### Currently trained clients

| Client | profile.yaml | my_style.md | In spine DB |
|---|---|---|---|
| AG1 | Empty stub | — | No |
| Elavate | Filled (collagen brand, women 25+, light scoring) | Filled (small) | No — pending sync |
| Kloris | Filled (premium UK wellness, women 35+, trust-led not deal-led) | Filled (~5.6k chars, scraped from Slack 2026-06-05) | **Yes — version 1, active** |

Kloris was the first client pushed to the central database via the new sync
script. See §10.

### How knowledge gets into Claude's prompt

`LLMAnalyzer.analyze()` builds the system message in this order:

```
=== AGENCY STANDARDS & SELECTION CRITERIA ===
{contents of knowledge/expertise.md}

=== CLIENT SCORING STYLE ===
{contents of knowledge/clients/<active>/my_style.md}

=== PAST CORRECTIONS FOR THIS CLIENT ===
{contents of knowledge/clients/<active>/corrections.md — if present}

=== APPROVED EXAMPLES FOR THIS CLIENT ===
{contents of knowledge/clients/<active>/good_examples.md — if present}

Use all of the above to match my judgment exactly.
```

The Build Shortlist page (`pages/2_Build_Shortlist.py`) reads `profile.yaml`
+ `my_style.md` and constructs a combined brief that goes into both the
system prompt and the user message.

---

## 7. Streamlit UI

### Entry point and theme

`streamlit run Homepage.py` from the project root. The light-mode design system
lives at [src/ui_styles.py](src/ui_styles.py); every page imports `inject()`
at the top so styling follows the user across navigation. Theme base in
`.streamlit/config.toml` is `light` with primary `#FF1F8E`, bg `#FFFFFF`,
secondary bg `#FAFAFA`, text `#1D1D1F`.

### Two pages (auto-discovered from `pages/`) — simplified 2026-06-11

The UI was cut down to match the v2 flow: **Vet Creators** and **Build
Shortlist** (both v1) moved to `to-archive/legacy-ui/` because Vet for
Campaign does both jobs in one motion. The Homepage's sidebar active-client
selector, hero stats, and CSV-format section were removed with them — the
campaign YAML's `client_folder` now decides calibration, not a global
selector.

| File | Purpose |
|---|---|
| [Homepage.py](Homepage.py) | **Homepage.** Brand lockup, short hero, two workflow cards (Vet for Campaign / Train Clients), API-key status. |
| [pages/1_Vet_for_Campaign.py](pages/1_Vet_for_Campaign.py) | **Vet for Campaign (v2).** 4 steps: (1) pick a campaign spec from campaigns/*.yaml with a summary of its brief + instant filters, (2) upload CSV, (3) run with live progress, (4) results as Shortlist / Rejected / Needs-review tabs with per-file downloads. Sidebar: test-run limit + "Reuse verdicts from the last 6 months" cache toggle. Same engine as `run_campaign.py` via a `progress_callback` on `CampaignVetter.run()`. |
| [pages/2_Train_Clients.py](pages/2_Train_Clients.py) | **Train Clients.** Three tabs: (1) clients list + create + delete + set active, (2) brand context + target niches multiselect + scoring notes form, (3) personal scoring style markdown editor with a starter template and guiding questions. |

### Shared label transforms

[src/ui_labels.py](src/ui_labels.py) — display-only translations used by the
Build Shortlist results table. **The CSV always stores the structured raw
values** (`A`/`B`/`C`/`D`, `rejected_<category>`, etc.) so downstream tools
that read the CSV are unaffected.

| Raw value | Display |
|---|---|
| `tier: A` | "Excellent (A)" |
| `tier: D` | "Weak (D)" |
| `gate_decision: passes` | "Cleared for central database" |
| `gate_decision: rejected_mlm` | "Held back — MLM involvement" |
| `gate_decision: rejected_brand_safety_critical` | "Held back — brand-safety score critically low" |
| `llm_recommendation: yes` | "Yes — recommend" |
| `llm_recommendation: no` | "No — do not shortlist" |
| `flags: stale_135d\|low_engagement` | "Stale for 135 days, Low engagement" |
| Any column key | Friendly column name via `friendly_column()` |

`ESSENTIAL_COLUMNS` is the list of 9 columns shown by default in the
shortlist preview: `ig_username`, `ig_full_name`, `followers`,
`avg_engagement_rate`, `tier`, `primary_niche`, `brand_fit_score`,
`llm_recommendation`, `gate_decision`.

### Design philosophy

- White background (#FFFFFF), Apple-style near-black text (#1D1D1F),
  hot pink (#FF1F8E) as the single accent — used for primary buttons,
  active nav, and the brand wordmark only.
- Apple hairline borders (#E5E5EA), very soft shadows (alpha ≤ 0.06).
- No animations, no glow effects, no gradient orbs — restrained,
  internal-tool feel. Replaces the previous dark-mode "product launch page"
  treatment.
- Typography: Syne for display (headings), DM Sans for body.
- Every label, button, and help tooltip phrased descriptively — buttons
  say what they do ("Start vetting run (downloads reels, transcribes,
  scores against rubric)"), labels explain trade-offs, help text expands
  on consequences.

---

## 8. CLI tools and scripts

### `run_campaign.py` — campaign vetting (v2, recommended for campaign work)

```bash
source ../../.venv/bin/activate
python run_campaign.py --input input/creators.csv --campaign campaigns/thrivin.yaml
python run_campaign.py --input input/x.csv --campaign campaigns/thrivin.yaml --limit 5   # test run
```

CSV + campaign spec → `output/campaigns/<name>_<timestamp>/` with
shortlist.csv, rejected.csv, review.csv, and per-creator evidence JSONs.
Requires both `MODASH_API_KEY` and `ANTHROPIC_API_KEY` (no CLIP fallback).
~19s/creator observed; hard-filtered creators cost no download or LLM call.

### `run.py` — v1 pipeline from the command line

```bash
source ../../.venv/bin/activate     # workspace venv has the deps
python run.py --input input/your_file.csv
python run.py --input input/x.csv --output output/y.csv --config config/x.yaml --log-level DEBUG
```

Same pipeline as the Streamlit Vet Creators page; useful for cron / batch
runs.

### `agent.py` — legacy conversational CLI agent

```bash
python agent.py --db output/enriched_<timestamp>.csv
```

Chat-driven interface over an enriched CSV. 13 tools defined in
[agent.py](agent.py): `search_creators`, `get_creator_profile`,
`add_to_shortlist`, `remove_from_shortlist`, `get_shortlist`,
`export_shortlist`, `analyze_creator_for_campaign`, `discover_creators`
(Influencers.Club), `discover_via_modash`, `brief_to_discovery` (reads a
brief and asks Claude to extract Modash filters), `queue_for_vetting`,
`list_briefs`, `read_brief`. Tool implementations in
[src/agent_tools.py](src/agent_tools.py).

Provider switching: `LLM_PROVIDER=anthropic` (default in practice) or
`LLM_PROVIDER=ollama`. The Ollama path is wired but not exercised.

Superseded for daily use by the Streamlit Build Shortlist page. Still works.

### `scripts/sync_brand_context_to_spine.py` — push training to central DB

```bash
# Dry-run (default) — prints what WOULD be written, no DB writes
python scripts/sync_brand_context_to_spine.py
python scripts/sync_brand_context_to_spine.py --client Kloris

# Apply
python scripts/sync_brand_context_to_spine.py --client Kloris --apply
python scripts/sync_brand_context_to_spine.py --apply   # all client folders
```

Reads every `knowledge/clients/<name>/` folder. Maps folder name to spine
`clients.slug` via `slugify_folder()` (lowercase, `&`→`and`, `+`→`-plus`,
drop apostrophes, dash-collapse non-alphanumeric). Looks up `client_id` in
the spine's `clients` table. Then atomically:

1. Sets the existing active `client_brand_context` row (if any) to
   `active=false, archived_at=now()`.
2. Inserts a new row with `version = previous + 1`, `active=true`,
   `created_by='manual'`.

The partial unique index `client_brand_context(client_id) WHERE active=true`
guarantees only one active rubric per client.

`DATABASE_URL` is auto-loaded from `Evergreen/augmentum-spine/.env` if not
already in the environment. SSL is required (Supabase enforces it). Works
with both `postgresql://` and `postgresql+asyncpg://` DSN formats.

---

## 9. Output formats

### Enriched CSV — `output/enriched_<timestamp>.csv`

One row per creator. Original input columns preserved. New columns added
(grouped by source):

| Source | Columns |
|---|---|
| fetcher | `ig_username`, `ig_full_name`, `ig_verified`, `ig_private` |
| scorer | `followers`, `following`, `total_posts`, `follower_following_ratio`, `avg_engagement_rate`, `posts_last_30_days`, `days_since_last_post`, `audience_quality_score`, `overall_quality_score`, `tier`, `flags` |
| pipeline | `reels_analyzed`, `transcript_sample` |
| visual | `detected_scenes`, `production_quality` |
| analyzer | `primary_niche`, `secondary_niche`, `niche_confidence`, `brand_fit_score`, `content_summary` |
| llm_analyzer | `llm_primary_niche`, `llm_brand_fit_score`, `llm_content_summary`, `llm_authenticity`, `llm_content_consistency`, `llm_brand_safety`, `llm_production_quality_score`, `llm_recommendation`, `llm_reasoning`, `llm_strengths`, `llm_concerns`, `llm_quality_score`, `llm_error` |
| quality_gate | `gate_decision`, `gate_reason`, `push_to_spine` |

### Per-creator JSON — `output/profiles/<username>.json`

Superset of the CSV. Includes the **full transcript** (no 300-char cap),
per-reel `clip_scores` dict, per-reel `production_quality` detail,
`visual_results` array, raw `analysis` block, and a full `engagement` block.

This is what the legacy agent reads when it calls `get_creator_profile()` —
much richer than the CSV row.

### SQLite cross-run store — `output/creators.db`

Exists (~7 MB). The Python class that reads/writes it (`CreatorStore`) is
referenced by `src/agent_tools.py` but **`src/creator_store.py` source is
missing** (only a `.pyc` in `__pycache__`). The legacy agent.py uses CSV
mode (`CreatorDatabase(csv_path)`) which doesn't touch the SQLite store, so
nothing currently breaks. See §12 gap #1.

### Spine database — `client_brand_context` table

When `scripts/sync_brand_context_to_spine.py --apply` runs, the active
rubric for that client lands as one row in Supabase's `client_brand_context`
table. Schema reference in
[augmentum-spine/SYSTEM_CONTEXT_DATABASE.md §14.5](../augmentum-spine/SYSTEM_CONTEXT_DATABASE.md).

---

## 10. Spine database integration

The Augmentum spine is the FastAPI service at
`Evergreen/augmentum-spine/`, deployed at
`https://augmentum-influencer-profiles.onrender.com`, backed by Supabase
Postgres with 131k+ profile rows. It's where the agency stores every
creator long-term.

### What ships today

| Component | Status |
|---|---|
| `client_brand_context` push (per-client rubrics) | **Shipped** via `scripts/sync_brand_context_to_spine.py`. Kloris is in the DB as version 1. |
| `profiles` push (every vetted creator) | **Not yet wired.** |
| `creator_vetting` push (per-creator vetting scores) | **Not yet wired.** |
| Full orchestrator integration (CreatorVetter as the spine's `Vetter`) | **Not yet wired.** |

The quality gate's `push_to_spine` column is the precondition for the
profile-push: when Option A ships, it will read this column and skip rows
where it's `False`.

### Three integration options (documented for the next contributor)

#### Option A — Lightweight profile sync (1–2 days)

After each pipeline run, push every creator with `push_to_spine=True` into
the spine's `profiles` table via the existing `POST /upsert` endpoint.
Vetting scores stay in CreatorVetter's local CSV / SQLite for now.

- **Win:** every vetted creator becomes findable across the agency.
- **Cost:** small. One new module `src/spine_writer.py`, called at the end
  of `Pipeline.run`.
- **Doesn't solve:** vetting scores still live only in CreatorVetter.

#### Option B — Profile sync + vetting sync (3–7 days)

Option A, plus writing `creator_vetting` rows.

- **What the spine needs:** a new endpoint `POST /api/creator-vetting` (does
  not exist yet) OR CreatorVetter writes directly to Supabase via
  `DATABASE_URL`.
- **What CreatorVetter needs:** before writing a vetting row, we need
  valid `request_id` and `run_id` to FK to. Cleanest is "B1 phantom
  request": CreatorVetter opens a `discovery_requests` row at the start of
  each pipeline run, plus a `discovery_runs` row, then `creator_vetting`
  rows under that run. Mark `completed` at the end.
- **Win:** every vetting decision is centrally queryable. "Have we vetted
  this creator for Kloris before?" becomes a real query.

#### Option C — Full orchestrator integration (1–2 weeks)

Implement `app/orchestrator/vetters/mark.py` in the spine repo. It calls
into CreatorVetter's `Pipeline` class per-creator. Set
`ORCHESTRATOR_VETTER=mark` in the Render worker env. The Discovery portal
→ spine orchestrator → CreatorVetter chain runs end-to-end.

- **Win:** unified flow. Discovery requests come in via the portal, the
  orchestrator picks them up, runs them through CreatorVetter, writes to
  `creator_vetting`. Streamlit UI shifts to a "review what was vetted"
  surface.
- **Cost:** medium. Refactor so CreatorVetter is importable as a Python
  package. Migrate `knowledge/clients/<name>/profile.yaml` to
  `client_brand_context` rows as the source of truth.

### Recommended path

**A now → B next → C as the destination.** Option A is the obvious next
piece of work. The gate is now reliable enough to power it.

### Open questions before implementing Option A

These don't block Option A but should be answered as part of building it:

1. **Folder → slug mapping** is handled by
   `sync_brand_context_to_spine.slugify_folder()`. Re-use this in
   `spine_writer.py` so it's one rule.
2. **`profile_id` round-trip.** The spine's `/upsert` returns the row. We
   need to capture the UUID and persist a local mapping
   (`ig_username → profile_id`) so Option B can FK to it. A small SQLite
   table or a JSON file in `output/spine_mappings.json` would work.
3. **Modash `platform_user_id`.** The spine uses this as the primary
   unique key (numeric Instagram ID). Modash returns it in
   `user-info` responses; needs to be threaded through
   `src/fetcher.py:_normalize_profile`.
4. **Per-client slug mismatch.** Today the CreatorVetter folder names match
   spine slugs in the cases tested (Kloris → kloris, Elavate → elavate).
   Confirm this for every client before going live.

---

## 11. Decisions log

Chronological. Each entry: what was decided, why, what it superseded.
Memory copy lives at [memory/decisions.md](memory/decisions.md).

### 2026-04-10 — Offline keyword/hashtag classifier (no LLM)
- **Decision:** Use an offline keyword + hashtag classifier instead of an LLM API for content classification.
- **Why:** At 10k creators/week, per-call LLM costs are prohibitive.
- **Status:** Partially superseded. The keyword classifier still runs (`src/analyzer.py`) but Claude is now layered on top as a per-creator LLM pass (`src/llm_analyzer.py`). Acceptable because Claude Haiku is cheap (~$0.001-0.002 per creator).

### 2026-04-10 — Apify for Instagram data
- **Decision:** Use Apify's `apify/instagram-profile-scraper` actor.
- **Status:** **Superseded** by Modash 2026-05-29 (see below).

### 2026-04-10 — Accept both URL and username columns
- **Decision:** Parse both `Profile URL` and `Username` columns. Extract username from URL via regex.
- **Status:** Holds. Implemented at [src/fetcher.py](src/fetcher.py) `extract_username()`.

### ~April 2026 — Modash Raw API (superseding Apify)
- **Decision:** Use Modash Raw API for profile data and reel video URLs.
- **Why:** Modash returns directly-downloadable signed CDN video URLs in `latestPosts[].videoUrl`. One vendor handles profile metrics, reels, and the discovery search endpoint.
- **Impact:** `MODASH_API_KEY` is now required. `APIFY_API_KEY` is vestigial — kept in `.env` as a fallback but read by no code. `.env.example` was cleaned up to remove the Apify entry.

### ~April 2026 — LLM analyzer enabled by default
- **Decision:** `llm_analysis.enabled: true` in config. Claude scores every creator alongside CLIP + keywords.
- **Why:** Catches content/visual mismatches that CLIP and keywords miss (e.g. a creator whose visuals tag as "wellness" but whose transcripts are explicit/political).
- **Gated on:** `ANTHROPIC_API_KEY`. Missing key skips the pass silently and the row has `llm_error: "no_key"`-style markers.

### ~April 2026 — Per-creator JSON profiles persisted
- **Decision:** Write `output/profiles/<username>.json` for every creator alongside the CSV row.
- **Why:** Lets the legacy agent read the full transcript later (the CSV's `transcript_sample` is capped at 300 chars).
- **Status:** Still produced. Will be the basis for richer Spine integration in Option B.

### ~April 2026 — `temp/` cleanup per creator
- **Decision:** Reel videos deleted in a `finally` block after every creator.
- **Why:** 10k/week × ~50 MB/reel = >1 TB if accumulated.
- **Enforced at:** `Pipeline._process_creator()` in [src/pipeline.py](src/pipeline.py).

### ~April 2026 — CSV flushed per row
- **Decision:** `csv.DictWriter` + `csv_file.flush()` after every row.
- **Why:** Crashed runs leave usable partial output. Don't batch-write at end.

### ~April 2026 — SQLite cross-run store designed
- **Decision:** Persist creators across runs in `output/creators.db` so the agent can search the union.
- **Status:** The DB file exists (~7 MB). The Python class `CreatorStore` is referenced by `src/agent_tools.py` but the source file `src/creator_store.py` is **missing** (only `.pyc`). Practical effect: the legacy CLI agent uses CSV mode and works fine; anything trying to use the SQLite-backed flow is broken. See §12 gap #1.

### 2026-05-29 — Apify decision back-logged as superseded
- Updated `memory/decisions.md` to explicitly mark the Apify decision as superseded by Modash.

### 2026-05-29 — Kloris client folder scaffolded
- Created empty `knowledge/clients/Kloris/profile.yaml` so the client appears in the Train Clients dropdown.

### 2026-06-05 — Quality gate v1 shipped
- **Decision:** Universal-disqualifier check before central-DB push. Universal (adult content, MLM, hate speech, anti-vax, etc.) blocks push. Brand-fit (wrong niche) doesn't block — recorded per-client separately.
- **Implementation:** [src/quality_gate.py](src/quality_gate.py), patterns in `config/config.yaml` → `quality_gate:`. Adds `gate_decision`, `gate_reason`, `push_to_spine` columns to enriched CSV.
- **Rationale for the universal/brand-fit split:** a creator failed for Lululemon doesn't necessarily fail for Elavate. We want to preserve knowledge cross-client to avoid re-vetting and to track over time whether a creator's quality has improved.

### 2026-06-05 — Quality gate v2 (negation-aware, concerns-only)
- **Decision:** Restrict keyword scan to `llm_concerns + flags`. Add negation detection.
- **Why:** v1 had ~5 false positives per 75-creator batch. All five tripped on Claude saying things like "cannot assess MLM involvement", "no hate speech detected", "passes brand-safety screening". These mentions were almost all in `llm_reasoning` (which v2 no longer reads) plus a few in `llm_concerns` (which v2 handles with negation lookback).
- **Status:** Verified against the 6 real false positives from a test run. 9/9 cases now behave correctly.

### 2026-06-05 — Spine integration: `client_brand_context` push shipped
- **Decision:** First spine integration is per-client brand context push, not per-creator profile push.
- **Why:** Smallest unit of value. Got Kloris's rubric into the central DB so any future tool querying it gets the same brief Claude uses locally. Profile push (Option A) is next.
- **Implementation:** [scripts/sync_brand_context_to_spine.py](scripts/sync_brand_context_to_spine.py). Auto-loads `DATABASE_URL` from `augmentum-spine/.env`. Versioned writes.

### 2026-06-05 — Kloris context scraped from Slack and filled
- **Decision:** Fill `knowledge/clients/Kloris/` from Slack history (#internal-kloris, #augmentum-kloris, #discovery-apportioning) rather than wait for onboarding-call notes.
- **What landed:** Brand context (premium UK wellness, post-CBD-rebrand identity, April 2026 strategic pivot), 12 target niches, ~1.8k chars of scoring notes, ~5.6k chars of scoring style (including the April Pedram/Kim brief on trust-led-not-deal-led creators).
- **Status:** Pushed to spine as version 1. Onboarding-call updates can be layered as version 2 when they arrive.

### 2026-06-07 — Directory tidy-up + `to-archive/` + `.gitignore`
- **Decision:** Pull dead artefacts out of the live tree without deleting them. Add a `.gitignore` so generated files (and the artefacts themselves) don't reaccumulate.
- **What moved into `to-archive/`** (152 MB total, see [to-archive/README.md](to-archive/README.md)):
  - `empty-runs/` — 10 zero-byte and two-byte `enriched_*.csv` files from runs that crashed before writing the header row.
  - `superseded-inputs/` — `Creators - 2.xlsx`, `your_file.csv`, `your_file.xlsx`. Excel duplicates of CSVs the pipeline actually reads; generic placeholder filenames from early testing.
  - `reference/` — `creator_vetting_rubric.docx`, the original Word document that became `knowledge/expertise.md`. Kept as the origin artefact.
  - `duplicate-assets/` — bare `Logo` file (the loaded brand mark is `logo.jpg`).
  - `orphaned-reels/` — 12 reel `.mp4` files (149 MB) from runs where the pipeline crashed before reaching its `finally` cleanup block. Largest item in the archive; safe to delete once confirmed nothing references them.
- **What stays live:** every CSV in `input/` and `output/` that has real data, every `.py`, every `knowledge/`, `memory/`, `config/`, `src/`, `pages/`, `scripts/` file. Empty working dirs (`temp/`, `input/`, `output/`) retain `.gitkeep` so the tree structure survives a fresh checkout.
- **What was deleted outright (not archived):** `__pycache__/` folders (Python regenerates them), `.DS_Store` files (macOS junk).
- **`.gitignore` added:** excludes `.env`, `__pycache__/`, `.DS_Store`, `*.pyc`, `temp/*.mp4`, `output/enriched_*.csv`, `output/profiles/*.json`, `output/creators.db`, `output/shortlists/*.csv`, `config/_ui_config.yaml`, the to-archive blobs. The `to-archive/README.md` itself is committed.
- **Run command unchanged:** `streamlit run Homepage.py`.

### 2026-06-05 — Entry point renamed `app.py` → `Homepage.py`
- **Decision:** Rename the Streamlit entry script so the sidebar nav reads "Homepage" instead of "app".
- **Why:** Streamlit derives sidebar nav labels from filenames. "app" reads as a placeholder and gives no sense of what the page does; "Homepage" is explicit.
- **Updated references:** `Dockerfile` CMD, `launch.bat`, this doc (§3, §6, §15), the docstring inside the file itself.
- **Run command going forward:** `streamlit run Homepage.py`.

### 2026-06-05 — Text greys darkened to pass WCAG AAA
- **Decision:** `--text-secondary` `#6E6E73` → `#424246` (9.3:1 contrast on white). `--text-muted` `#86868B` → `#5A5A60` (6.7:1). Hardcoded hex values in inline page styles bulk-replaced too (sed across `Homepage.py` and all three subpages).
- **Why:** User reported "grey text on white is not legible". The Apple-palette `#86868B` fails WCAG AA for normal text (4.04:1). The new values pass AAA, so subtitles, captions, sidebar hints, and "Continue to / Go to" footer labels all read clearly.
- **Code:** [src/ui_styles.py](src/ui_styles.py) for the token defaults; the four page files for inline overrides.

### 2026-06-05 — Sidebar nav order confirmed as Homepage / Vet Creators / Build Shortlist / Train Clients
- **Decision:** Keep the current numbered order. Files `pages/1_Vet_Creators.py`, `2_Build_Shortlist.py`, `3_Train_Clients.py` drive the order alphabetically/numerically in the sidebar.
- **Why:** Matches the daily workflow. A user opens the app to vet a fresh CSV from sourcing → filter the result for one client → optionally update a client's brief. Setup (training) is rare; daily use leads with Vet Creators. Verified with user.

### 2026-06-05 — Button-text legibility — switched to near-black (final)
- **First attempt:** Use deeper pink `#D91775` (4.59:1 contrast). Mathematically passed WCAG AA but in practice still read as low-contrast at button-text size.
- **Final decision:** Primary buttons use `#1D1D1F` (same near-black as body text). White text on near-black is 16.6:1 — unmissable. Hover state goes to pure `#000000`. Focus ring is a 3px halo in `var(--primary-muted)` (translucent pink), so the brand still ghosts in on the interaction without compromising rest-state legibility.
- **Brand pink stays everywhere else:** active sidebar nav border, "Creator" wordmark accent, hero badge text, section-label dashes, step number badges, active client badge, multiselect tags, tier-B badges, focus rings. Removing it from buttons does not weaken the brand — it strengthens the call-to-action.
- **Selectors covered:** `.stButton > button[kind="primary"]`, `.stButton > button:not([kind="secondary"])`, `[data-testid="baseButton-primary"]`, `[data-testid="baseButton-primaryFormSubmit"]`, `[data-testid="stFormSubmitButton"] > button`, `[data-testid="stDownloadButton"] > button`. Plus `* { color: #FFFFFF !important }` on each so any nested span the BaseWeb library wraps the label in still inherits white.
- **Code:** [src/ui_styles.py](src/ui_styles.py) — button rules block.

### 2026-06-05 — Build Shortlist: chunked filtering + robust JSON parsing
- **Decision:** Send creators to Claude in batches of `_CHUNK_SIZE = 25` instead of one big request, with `max_tokens = 8000` per batch. Merge results from every batch. Use a lenient JSON parser that strips code fences and extracts the first `{...}` block if a direct parse fails.
- **Why:** First Kloris filter run on a 76-creator CSV returned "0 approved" even though Claude actually approved 17. Root cause: the AnthropicClient hardcoded `max_tokens=2048`, which truncated the JSON response mid-creator, which broke the naïve `json.loads`. Chunking + higher token budget + lenient parser fixes all three failure modes at once.
- **Side effect:** Long CSVs no longer hit a single-call ceiling. A 200-creator CSV runs in 8 batches; each batch is independent, so a single-batch failure doesn't lose the whole shortlist — a warning is surfaced per-batch and successful batches still produce a partial shortlist.
- **Code:**
  - [src/llm_client.py](src/llm_client.py) — added `max_tokens: int = 2048` parameter to `AnthropicClient.chat()` and `OllamaClient.chat()` (Ollama ignores it).
  - [pages/2_Build_Shortlist.py](pages/2_Build_Shortlist.py) — `_CHUNK_SIZE`, `_MAX_TOKENS_PER_CHUNK`, `_run_one_chunk()`, `_parse_json_lenient()`, refactored `_filter_creators_with_claude()` to return `(approved_rows, merged_dict, warnings_list)`.

### 2026-06-11 — Lyric-transcript false rejections diagnosed (Thrivin run)
- **Finding:** Whisper transcribes the licensed/trending music on reels as if
  it were the creator speaking. In the 2026-06-07 Thrivin run this drove
  wrong decisions: @aprilalexander gate-blocked for a "racial slur" that was
  a song lyric; @richardbromilowpt (verified PT) LLM-rejected as a "music
  creator". Both confirmed accepted on human review. Two further gate false
  positives in the same 38 rows: @jasmijnvz_ rejected_mlm on "MLM" inside a
  *cannot-assess* concern (negation lookback miss), and @issychapman
  rejected_brand_safety_critical because *no data* produced brand_safety=0.
- **Conclusion:** transcript-only judgment + keyword-scan gating are
  structurally unreliable. Drove the v2 build below.

### 2026-06-11 — Campaign vetting flow (v2) built
- **Decision:** New pipeline alongside v1 (v1 untouched, still powers the
  UI). One motion: CSV + campaign spec → shortlist / rejected / review.
  Full design in §2a.
- **What changed vs v1:**
  - **Hard filters first** ([src/campaign.py](src/campaign.py)) — follower
    band, engagement floor, dormancy, private, VIP ceiling run before any
    download or LLM call. No-data accounts can no longer reach a safety
    judgment (fixes the "missing data = unsafe" class).
  - **CLIP + keyword niche fusion dropped from this flow** — replaced by
    sampled reel frames ([src/frames.py](src/frames.py), ≤8 frames @512px
    ≈1–2¢/creator) sent to Claude Haiku vision in ONE structured call per
    creator ([src/vetter.py](src/vetter.py)). Captions + bio (the creator's
    own words, newly fetched in [src/fetcher.py](src/fetcher.py)) are
    first-class judgment inputs.
  - **Keyword gate dropped from this flow** — `universal_disqualifiers`
    returns as a schema-enforced enum list via forced tool_choice
    ([src/llm_client.py](src/llm_client.py)); `push_to_spine` = empty list.
  - **Lyric defence** — prompt EVIDENCE RULES forbid attributing lyric
    content to the creator; `spoken_content_is_music` in the verdict makes
    it auditable; [src/transcriber.py](src/transcriber.py) gained
    `transcribe_detailed()` with a per-reel `speech_confidence` hint.
  - **Lean outputs** — three small CSVs with ≤30-word reasons; full
    evidence lives in `profiles/<username>.json` per run. No more
    five-essay rows.
- **Validation:** hard-filter replay over the 38-creator Thrivin run matched
  the human pass (zombie accounts → metric rejects; katb_fit/charliekamale
  → VIP review). Live re-vet of April + Richard: zero disqualifiers, music
  correctly flagged, evidence-cited verdicts.
- **Known tension:** Thrivin's documented 1% engagement floor rejects
  @fitwithmaaike_ (0.74%) and @demivthuil (0.68%), both approved by the
  human pass. One-line fix in `campaigns/thrivin.yaml` if the floor should
  be 0.5 — awaiting user call.

### 2026-06-11 (later) — Vetting cache + frontend simplification
- **Vetting cache** — [src/vetting_cache.py](src/vetting_cache.py): a creator
  already LLM-judged for the same campaign within ~6 months
  (`cache_max_age_days: 183`) is replayed from `output/vetting_cache.db`
  instead of re-fetched/re-judged. Zero Modash + LLM cost on hits; `source`
  column says `cached:<date>`. Hard-filter outcomes are never cached
  (metrics drift; rechecking is free). Self-seeds from past run folders.
  User-requested ("if someone has already been vetted for this campaign…
  pull from the database if it's in the last 6 months").
- **Frontend simplified** (user-requested) — UI is now Homepage +
  Vet for Campaign + Train Clients. `pages/1_Vet_Creators.py` and
  `pages/2_Build_Shortlist.py` moved to `to-archive/legacy-ui/` (superseded
  by the one-motion v2 page). Homepage lost the active-client sidebar
  selector (campaign YAML decides calibration), hero stats, and the
  CSV-format section.
- **Thrivin engagement floor → 0.5%** (user call) — docs said 1.0 but the
  human pass approved 0.68–0.74% creators; borderline ER is now the LLM's
  judgment call.
- **Whisper tiny → base** in config — cleaner transcripts help the
  speech-vs-music distinction and the judgment.

### 2026-06-11 (evening) — Accuracy upgrades: audience geo, comment texture, corrections loop
- **Audience geo check (user-approved lever #1)** — after the LLM approves a
  creator, the vetter fetches the Modash audience report (full API, costs
  credits — finalists only) and checks the campaign's
  `audience.target_country` / `min_pct`. Below the floor → demoted to
  review.csv as `audience_geo_mismatch` with the numbers in the reason.
  Shortlist gains `audience_target_pct`, `audience_credibility` (Modash
  fake-follower signal), `audience_top_countries`. First live probe proved
  the value instantly: @itsjustheva (A-tier, 31% ER) is 42.7% Iran / 8.7% UK
  / 53% male — invisible to every previous pass.
- **Comment texture (lever #2)** — comments from the 2 most recent posts
  (raw API `media-comments?code=`) are sampled into the judgment prompt;
  the verdict gains `engagement_texture` (real_conversation / mixed /
  emoji_or_bot / unknown). Live-validated: @gserranofit's emoji rows →
  `emoji_or_bot`; @peacheymiax's substantive replies → `mixed`.
- **Corrections loop (lever #3)** — "Correct a decision" expander on the
  results step ([src/corrections.py](src/corrections.py)): appends to the
  client's `corrections.md` (already injected into every future judgment)
  and invalidates the creator's cached verdict so the next run re-judges
  with the lesson in context.
- **Credit-exhaustion guard** — Modash `not_enough_credits` (403) was being
  misreported as per-creator "fetch_failed". Now raises
  `ModashCreditsExhausted` and stops the run loudly. Found the hard way:
  credits ran out mid-test on 2026-06-11.
- **Spine consolidation: forward-only (user decision)** — `creators.db`
  (stale April v1 snapshot) will NOT be bulk-pushed. Option A pushes
  fresh v2-vetted creators only.

### 2026-06-12 — Modash credit monitoring + the two-pools discovery
- **Modash bills from two SEPARATE pools** (confirmed via `/v1/user/info` +
  #augmentum-modash): Discovery API "credits" (report=1.0, classic
  search=0.15/page, AI search=0.025/result) and a RAW API "rawRequests"
  allotment (user-info / user-reels / media-comments = 1 each). The
  2026-06-11 "credits exhausted" incident was actually the RAW pool hitting
  -10 while 461.55 Discovery credits sat unused. The account is SHARED
  across Augmentum (Aditya's discovery agent, Mark's tools, CreatorVetter).
- **Monitoring shipped** ([src/modash_usage.py](src/modash_usage.py)):
  every Modash call logs to `output/modash_usage.jsonl`; `get_balance()`
  reads the live account-wide pools; the Homepage Modash card shows both
  pools + this tool's 7-day usage with a low-raw warning; the vetter checks
  the balance BEFORE fetching (warns when the raw pool can't cover the run)
  and prints a consumption line at run end.

### 2026-06-11 (late night) — The training flywheel shipped (spine push + calibration deck + evidence intake)

User decision: training is evidence-curation, not document-writing. Four
pieces, built in dependency order:

- **Spine Option A + decisions plumbing** ([src/spine.py](src/spine.py),
  [push_run_to_spine.py](push_run_to_spine.py)). Every judged creator with
  no disqualifiers → `POST /upsert` on the spine API (profile row, keyed by
  handle + `platform_user_id` — Modash `pk` now threaded through the
  fetcher) **plus** a row in the spine's existing `creator_vetting` table
  (migration 0014) under a phantom `discovery_requests`/`discovery_runs`
  pair tagged "CreatorVetter v2". Decision enum mapping: LLM
  approve/reject/needs_review → `auto_approved`/`auto_rejected`/
  `pending_review`; calibration swipes + corrections → `human_approved`/
  `human_rejected` (via `record_human_decision()`). The vetter auto-pushes
  at end of run (`campaign_vetting.spine_push: true`, best-effort, never
  fails the run); the CLI covers older runs. **Status: dry-run validated
  (client slug resolves, decisions map); the first live `--apply` write
  needs the user to run/approve it** — the permission layer correctly
  stopped an unattended first write to the production DB.
- **Calibration Deck** ([pages/3_Calibration_Deck.py](pages/3_Calibration_Deck.py),
  [src/calibration.py](src/calibration.py)). Shows judged creators
  borderline-first (fit nearest 55) WITHOUT revealing the model's call.
  Each human swipe writes: `calibration_labels.jsonl` (machine log),
  `calibration_labels.md` (now the 4th file `_load_calibration()` injects
  into every judgment — disagreements are marked "MODEL DISAGREED… the
  human call is correct"), and best-effort a `human_*` spine row. Header
  shows the **agreement rate** — the first quantitative answer to "is this
  client trained well enough?" (90%+ = trust it; <70% = keep labelling).
- **Evidence & sources tab** (Train Clients tab 4,
  [src/evidence.py](src/evidence.py)). Upload anything (txt/md/csv/yaml/
  json/pdf) into `knowledge/clients/<name>/evidence/`, or have Claude fetch
  it: brand website (tag-stripped), the client's Slack channel
  (SLACK_BOT_TOKEN from the workspace .env), Fathom call transcripts
  (FATHOM_API_KEY). **Raw evidence never enters prompts** — a distillation
  pass extracts judgment rules with provenance, the human edits/confirms,
  and only then does it land in `my_style.md`. Distiller validated live:
  extracted geo/follower/yoga/Boohoo rules from a noisy test snippet,
  ignored the chatter.

### 2026-06-11 (night) — UI redesigned to the Augmentum brand design language
- **Decision:** Replace the Apple-style palette (near-black #1D1D1F, pink
  #FF1F8E, Syne/DM Sans) with the canonical Augmentum light-mode brand spec
  from `.claude/skills/augmentum-design-language-light-mode`: navy `#030937`
  text (never pure black), hot-pink `#ff007e` accent, **Playfair Display**
  (display, italic pink accents) + **Geist** (body/UI/data), off-white
  `#f7f8fc` surface gradient, pink-gradient card accent strips, navy
  download buttons, pink primary buttons, metric cards with pink bottom
  borders.
- **Scope:** [src/ui_styles.py](src/ui_styles.py) fully rewritten (class
  names preserved so page markup kept working); inline hexes in
  Homepage + both pages swept to the new tokens; `.streamlit/config.toml`
  theme updated. Editorial, premium, data-forward — matches
  augmentum-media.com.

### 2026-06-05 — Light-mode UI shipped (Option B from the brainstorm)
- **Decision:** Swap from dark mode + animated effects to a light, restrained Apple-style design.
- **Why:** Reduces the "developer tool" / "product launch page" feel; calmer for daily internal use. Light mode is closer to augmentum-media.com's editorial pages.
- **Scope shipped:** Full light theme, three pages renumbered (1_Vet_Creators / 2_Build_Shortlist / 3_Train_Clients), descriptive copy throughout, plain-language label transforms via `src/ui_labels.py`, sample CSV download, first-run model-download notice, sidebar active-client now drives Build Shortlist default, essential columns shown by default + full columns behind expander.
- **Scope deferred:** A "what is this?" onboarding block on the home page — user said it's not necessary yet.
- **Implementation:** [src/ui_styles.py](src/ui_styles.py) is the shared CSS helper; every page calls `inject()` at the top.
- **What was removed:** `pages/1_Pipeline.py`, `pages/3_Agent.py`, `pages/5_Training.py` deleted. Animated background orbs, glow effects, drift animations all removed.

---

## 12. Status — what's done, what's open, what to build next

### Last refreshed: 2026-06-11

### Done

- ✅ **Campaign vetting flow (v2)** — `run_campaign.py`: hard filters → frames+captions+bio → one structured vision call → shortlist/rejected/review CSVs. Validated against the Thrivin run (§2a)
- ✅ Thrivin campaign spec (`campaigns/thrivin.yaml`) built from client knowledge
- ✅ Pipeline core (v1): fetch → download → transcribe → CLIP → analyzer → scorer → LLM → gate → CSV + JSON
- ✅ Quality gate v2 (negation-aware, concerns-only) — false positives fixed
- ✅ Light-mode UI shipped (3 pages, descriptive copy, plain-language labels)
- ✅ Button-text contrast bump (WCAG AA — darker pink #D91775 on primary buttons)
- ✅ Sample CSV download + first-run model-download notice
- ✅ Sidebar active-client carries to Build Shortlist
- ✅ Build Shortlist: chunked filtering (25 creators/batch, max_tokens=8000) + lenient JSON parser
- ✅ Kloris client trained from Slack scrape, pushed to spine as version 1
- ✅ Spine sync script versions correctly (atomic deactivate + insert)
- ✅ Modash discovery wrapper, Influencers.Club legacy wrapper
- ✅ Legacy CLI agent (13 tools) still works as before

### Open gaps (priority order)

0. **v2 follow-ups (new, 2026-06-11):**
   - ~~Settle the Thrivin engagement floor~~ — set to 0.5% same day.
   - ~~Wire the v2 flow into the Streamlit UI~~ — shipped same day; UI then
     simplified to Homepage + Vet for Campaign + Train Clients (v1 pages
     archived to `to-archive/legacy-ui/`).
   - ~~Re-vet avoidance~~ — vetting cache shipped same day (6-month TTL).
   - Spine Option A should read v2's `push_to_spine` (from the enum
     verdict) rather than v1's keyword gate column. The legacy
     `output/creators.db` (4,904 rows of April v1 scores, only 850 with LLM
     verdicts, frozen since 2026-04-21) should NOT be bulk-pushed — it's a
     stale client-blind snapshot; consolidate by pushing fresh v2-vetted
     profiles instead and treating creators.db as archive material.
   - Decide v1's future: the engine still exists for bulk enrichment via
     `run.py`, but the UI no longer exposes it.

1. **`src/creator_store.py` source is missing.** The SQLite file
   `output/creators.db` exists. `src/agent_tools.py` references the class.
   Only the `.pyc` survives in `__pycache__`. CSV mode (the only currently
   used codepath) is fine; SQLite-backed flow is broken. **Fix:** rebuild
   from the call sites — interface is fully specified by `CreatorDatabase`
   methods. Decompiling the `.pyc` (`uncompyle6`/`decompyle3` for Python
   3.14) is another option but the bytecode format may not be supported.

2. **Spine Option A — push every vetted creator's `profiles` row.** Most
   impactful next architectural step. Design in §10. Needs `src/spine_writer.py`,
   reads `push_to_spine` from the gate, calls `POST /upsert`, captures the
   returned UUID for Option B. The user has asked when to start; awaiting
   green light.

3. **Spine Option B — push `creator_vetting` rows.** After Option A. Needs
   either a new spine endpoint (`POST /api/creator-vetting`) or direct DB
   writes via `DATABASE_URL`. Phantom-request pattern handles the FK
   requirement (see §10).

4. **No corrections UI.** `corrections.md` and `good_examples.md` are
   loaded by `_load_calibration()` if present, but there's no UI to author
   them. The obvious next user-facing feature: a "this was wrong" button
   on Build Shortlist results that persists the rejection reason into
   the active client's `corrections.md` so the next analysis improves.

5. **No `pages/Browse.py`.** The legacy agent's `discover_*` tools mention
   "browse them in the Browse page" but no such page exists. Build it
   once `creator_store.py` is back.

6. **Build Shortlist batching is fixed but not infinite.** Shortlist now
   chunks creators into batches of 25 with `max_tokens=8000` per batch
   (shipped 2026-06-05). Tested cleanly on a 76-creator CSV (3 batches).
   At several thousand creators this still works (just slower); above ~5k
   creators consider a different surface — the legacy `agent.py` paginated
   tool-use pattern is the better template for very large pools.

7. **No tests.** No `tests/` directory. Refactors are unprotected.

8. **`config.yaml` has only six niches** but Training UI offers more
   (Menopause, Sleep & Recovery, Nature & Country Lifestyle, Equestrian,
   etc. — added for Kloris). The Pipeline's CLIP/keyword scoring can't
   surface those extras because there are no prompts/keywords for them.
   Either add CLIP prompts + keyword lists for the additional niches, or
   restrict the Training niche dropdown to a subset of `config.yaml`'s
   niches.

9. **Streamlit progress bar is heuristic.** It counts
   `"Processing creators"` log lines, not actual progress. A cleaner
   implementation would have the Pipeline accept a `progress_callback`.

10. ~~Stale 0-byte CSVs in `output/`~~ — **resolved 2026-06-07.** All 0-byte
    and 2-byte enriched CSVs moved to [to-archive/empty-runs/](to-archive/empty-runs/).

11. ~~Stale `.mp4` files in `temp/`~~ — **resolved 2026-06-07.** All 12
    orphaned reel videos moved to [to-archive/orphaned-reels/](to-archive/orphaned-reels/).
    `temp/` is now empty save `.gitkeep`.

12. **`launch.bat` is hardcoded** to a Windows path on Mark's machine.
    Doesn't work elsewhere without editing.

13. **`docker-compose.yml` service name is misspelled** as `creatovetter`.

14. **`contacts.md` is an empty stub.** Either fill it (Mark, Aaron,
    pod leads) or delete.

### Recommended next move

**Spine Option A.** The gate is now reliable. Every component for profile
push exists conceptually. ~1–2 days of focused work; immediate value.

---

## 12a. Future additions to make

The agreed roadmap, in priority order. (Levers 1–3 from the 2026-06-11
accuracy review shipped same day — see the decisions log.)

1. ~~**Spine Option A — consolidate forward**~~ — SHIPPED 2026-06-11 (see
   decisions log). Remaining: the first live `--apply` push needs user
   approval; after that it runs automatically at the end of every vet run.
1b. **(superseded detail below kept for design reference)** Push each
   freshly v2-vetted creator's profile to the central Supabase DB after a
   run, reading `push_to_spine` from the structured verdict. Do NOT bulk-
   push `creators.db` — it's a stale, client-blind April v1 snapshot
   (4,904 rows, only 850 with LLM verdicts, frozen 2026-04-21). Treat it
   as archive material. Design + open questions in §10.
2. **Bio link checking (lever #4 — deliberately deferred).** Thread
   `external_url` + `bio_links` (already confirmed present in the Modash
   user-info response) through `_normalize_profile` and into the judgment
   prompt. Cheap, high-signal for universal disqualifiers (OnlyFans/Linktree
   destinations) — left for later by user call 2026-06-11.
3. **Spine Option B** — per-creator `creator_vetting` rows in the central
   DB (after A). "Have we vetted this creator for any client before?"
   becomes a cross-campaign query, superseding the local vetting cache.
4. **Live geo validation run** — the audience-report integration is coded
   and the endpoint is proven, but the full approve→report→demote path
   has not run end-to-end yet: Modash credits ran out mid-test. Re-test
   on the first run after the account is topped up.
5. **Re-vet the full Thrivin CSV with v2** once credits are back —
   produces the clean shortlist and exercises geo + texture at batch scale.
6. **Comment pagination / weighting** — today we sample the first ~20
   comments of the 2 newest posts. If texture calls look noisy, sample
   across more posts or weight by comment length.
7. **Tests.** Still no `tests/` directory. The hard filters, gate logic,
   cache TTL, and slugify are all pure functions begging for unit tests.

---

## 13. How to run

### First-time setup (macOS)

```bash
cd Evergreen/creator_vetter
# Use the workspace .venv at the repo root (Python 3.14)
source ../../.venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg

# Copy and fill in API keys
cp .env.example .env   # edit and add MODASH_API_KEY + ANTHROPIC_API_KEY
```

### Streamlit UI (primary)

```bash
streamlit run Homepage.py
# → http://localhost:8501
```

First pipeline run downloads the Whisper model (~150 MB for `base`) and
the CLIP model (~340 MB) into `~/.cache/`. The UI shows an inline notice
when this is happening.

### CLI pipeline

```bash
# v2 — campaign vetting (recommended for campaign work)
python run_campaign.py --input input/your_file.csv --campaign campaigns/thrivin.yaml
# Output → output/campaigns/<name>_<timestamp>/{shortlist,rejected,review}.csv + profiles/

# v1 — client-blind enrichment
python run.py --input input/your_file.csv
# Output → output/enriched_<timestamp>.csv + output/profiles/<username>.json
```

### CLI agent (legacy)

```bash
python agent.py --db output/enriched_<timestamp>.csv
```

### Spine sync (per-client brand context)

```bash
# Dry-run first
python scripts/sync_brand_context_to_spine.py --client <ClientFolderName>

# Then apply
python scripts/sync_brand_context_to_spine.py --client <ClientFolderName> --apply
```

### Docker

```bash
docker compose up --build
# Mounts ./input, ./output, ./.env into the container; serves Streamlit on :8501.
```

---

## 14. Conventions that must not be broken

From CLAUDE.md, memory/preferences.md, and the rules embedded in this
codebase. If any of these get broken in a refactor, fix them.

1. **No paid APIs for per-frame / per-reel heavy work.** Whisper and CLIP
   stay local. LLM judgment per creator is okay (Haiku is cheap); vision
   APIs are not.
2. **`temp/` videos deleted after each creator** in a `try/finally`.
   Currently violated by old crashes — leftover `.mp4`s in `temp/` are
   safe to delete, but the cleanup logic itself is correct.
3. **Never modify the input CSV.** Always write a new
   `enriched_<timestamp>.csv`.
4. **All thresholds, niches, gate patterns go in `config/config.yaml`.**
   Don't hardcode in Python.
5. **CSV output is incremental + flushed per row.** Don't change to
   batch-write at the end.
6. **Evidence-cited LLM decisions only.** The rubric mandates citing post
   URL / bio text / link destination for every reject or flag. Keep the
   "reasoning referencing specific content" wording in the prompt.
7. **Hard rejects are not brief-overridable.** Soft rejects are.
8. **Universal disqualifiers ≠ brand-fit mismatches.** A creator failed
   for one client may pass for another. Only universal disqualifiers
   (the categories in `quality_gate.universal_reject_patterns`) block
   central-DB entry.
9. **Streamlit pages share styling via `src/ui_styles.py`.** Don't
   duplicate CSS across pages.
10. **Plain-language labels are display-only.** CSV always stores the raw
    structured values (`A`/`B`/`C`/`D`, `rejected_<category>`, etc.).
    Downstream tools that read the CSV must not break when the UI
    changes its labels.
11. **Knowledge edits don't auto-sync to the spine.** After editing
    `knowledge/clients/<name>/`, run
    `scripts/sync_brand_context_to_spine.py --client <name> --apply`
    to push the change centrally. The script versions in place.
12. **Never attribute reel-audio transcript content to the creator.**
    Reels routinely use licensed/trending music; Whisper transcribes the
    lyrics like speech. Any judgment path must treat lyric-like transcripts
    as ambient audio (the v2 prompt's EVIDENCE RULES encode this). Profanity
    or slurs inside song lyrics are never grounds for rejection.
13. **Missing data is never a safety verdict.** A creator with no reels /
    bio / captions routes to review as `no_content` — they must not reach
    an LLM safety judgment or be recorded as unsafe.
14. **v2 structured output stays schema-enforced.** Universal disqualifiers
    come back as an enum list via forced tool_choice — do not reintroduce
    free-text scanning or JSON-from-prose parsing into the v2 verdict path.
15. **Hard filters before spend.** In the v2 flow, metric criteria
    (followers, engagement, recency) must run before reel downloads and
    LLM calls — campaign YAML is where those thresholds live, not code.

---

## 15. Critical-file cheat sheet

If you're about to edit, start here.

### Campaign vetting (v2)
- [src/vetter.py](src/vetter.py) — `CampaignVetter.run()` orchestrator,
  the verdict tool schema, and the EVIDENCE RULES prompt (lyric defence).
- [src/campaign.py](src/campaign.py) — `CampaignSpec` + hard filters.
- [campaigns/thrivin.yaml](campaigns/thrivin.yaml) — worked campaign spec;
  thresholds and judgment notes live here, not in code.
- [src/frames.py](src/frames.py) — frame sampling for the vision call.

### Pipeline + gating (v1)
- [config/config.yaml](config/config.yaml) — all thresholds, niches, CLIP
  prompts, gate patterns, and the `campaign_vetting:` block. Edit here, not in code.
- [src/pipeline.py](src/pipeline.py) — `Pipeline.run()` orchestrator. Every
  v1 entry point goes through it.
- [src/fetcher.py](src/fetcher.py) — `_normalize_profile()` maps Modash's
  response shape to our internal contract. If Modash changes their schema,
  this breaks first.
- [src/scorer.py](src/scorer.py) — `score_profile()` — all numeric scoring
  logic.
- [src/llm_analyzer.py](src/llm_analyzer.py) — Claude prompt assembly +
  calibration injection.
- [src/quality_gate.py](src/quality_gate.py) — universal-disqualifier
  filter. Negation phrases and the "concerns-only" decision live here.

### UI
- [Homepage.py](Homepage.py) — Streamlit entry point (light theme + workflow cards + config). The file is named `Homepage.py` so the sidebar label reads "Homepage" not "app".
- [src/ui_styles.py](src/ui_styles.py) — shared light-mode CSS helper. Every
  page calls `inject()` at the top.
- [src/ui_labels.py](src/ui_labels.py) — plain-language label transforms.
  Used only for display; the CSV keeps raw values.

### Knowledge
- [knowledge/expertise.md](knowledge/expertise.md) — the global Augmentum
  vetting rubric. Single most-leveraged document in the system.
- [knowledge/clients/Kloris/profile.yaml](knowledge/clients/Kloris/profile.yaml)
  + [knowledge/clients/Kloris/my_style.md](knowledge/clients/Kloris/my_style.md)
  — example of a fully trained client.

### Scripts
- [scripts/sync_brand_context_to_spine.py](scripts/sync_brand_context_to_spine.py)
  — the only currently shipped spine integration. Reads local YAML/markdown,
  versions into `client_brand_context`.

### Legacy
- [agent.py](agent.py) — conversational CLI agent. 13 tool definitions
  there; tool implementations in [src/agent_tools.py](src/agent_tools.py).

---

## 16. Environment variables

```bash
# Required for the Vet Creators pipeline
MODASH_API_KEY=...

# Required for the LLM analyzer + Build Shortlist page
ANTHROPIC_API_KEY=...

# Optional
INFLUENCERS_CLUB_API_KEY=...   # legacy discovery only
LLM_PROVIDER=anthropic         # default in practice
LLM_MODEL=...                  # default: claude-haiku-4-5-20251001
DEBUG_MODASH=true              # dump Modash search responses to stdout

# Only used by scripts/sync_brand_context_to_spine.py
DATABASE_URL=...               # auto-loaded from Evergreen/augmentum-spine/.env if not set
```

`APIFY_API_KEY` may still be present in `.env` but is unused. Keep it or
remove it — doesn't affect anything.

---

End of context. If anything in this doc disagrees with the code, the code
wins — update the doc.
