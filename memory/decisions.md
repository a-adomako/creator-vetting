# Decisions & Rationale

Chronological. Full narrative + code references for each decision lives in
[../SYSTEM_CONTEXT.md §11](../SYSTEM_CONTEXT.md). This file is the running log.

---

### 2026-04-10 — Offline keyword/hashtag classifier (no LLM at the analyzer layer)
- **Decision:** Use an offline keyword + hashtag classifier instead of an LLM API for content classification.
- **Why:** At 10k creators/week, per-call LLM costs are prohibitive.
- **Status:** Partially superseded by the LLM analyzer layered on top (2026-04 onwards). Keyword classifier still runs.

### 2026-04-10 — Apify for Instagram data (SUPERSEDED)
- **Decision:** Use Apify's `apify/instagram-profile-scraper` actor.
- **Why:** Handled proxies and rate limiting. Most reliable option at scale.
- **Superseded by:** "Instagram data source — Modash Raw API" (2026-05-29 decision-log entry).

### 2026-04-10 — Accept both URL and username columns
- **Decision:** Parse both `Profile URL` and `Username` columns. Extract username from URL via regex.
- **Why:** Different sourcing tools export different formats.
- **Code:** [src/fetcher.py](../src/fetcher.py) → `extract_username()`.

### 2026-05-29 — Instagram data source: Modash Raw API
- **Decision:** Use Modash Raw API for profile data, reels, and discovery search.
- **Why:** Modash returns directly-downloadable signed CDN video URLs in `latestPosts[].videoUrl`. One vendor covers everything we needed Apify + a separate discovery API for.
- **Impact:** `MODASH_API_KEY` required. `APIFY_API_KEY` vestigial — kept in `.env` as fallback but read by no code. `.env.example` was cleaned to remove Apify.
- **Code:** [src/fetcher.py](../src/fetcher.py) (`ModashFetcher.fetch_profiles`), [src/modash.py](../src/modash.py) (discovery wrapper).

### 2026-06-05 — Quality gate v1 — universal vs brand-fit split
- **Decision:** Filter creators before central-DB push using a universal-disqualifier check. Universal disqualifiers (adult content, MLM, anti-vax advocacy, hate speech, religious extremism, pseudo-medical claims) block push. Brand-fit mismatches (wrong niche, wrong demographic) do NOT block push — recorded per-client separately.
- **Why:** A creator failed for Lululemon might pass for Elavate. Preserving central knowledge avoids re-vetting and lets us track creator quality over time.
- **Implementation:** [src/quality_gate.py](../src/quality_gate.py), patterns in `config/config.yaml` → `quality_gate:`.
- **Output:** Adds `gate_decision`, `gate_reason`, `push_to_spine` columns to every enriched CSV row.

### 2026-06-05 — Quality gate v2 — negation-aware, concerns-only scan
- **Decision:** Restrict keyword scanning to `llm_concerns + flags` (drop `llm_reasoning` and `llm_content_summary`). Add negation detection: patterns preceded within 50 chars by `no`, `not`, `cannot`, `rule out`, `verify for`, `assess for`, `passes screening` etc. are treated as descriptions of absence and ignored.
- **Why:** v1 produced ~5 false positives per 75-creator batch — Claude frequently writes things like *"cannot assess MLM involvement"*, *"no hate speech detected"*, *"passes brand-safety screening (no MLM, no political extremism)"*. Naïve substring matching tripped on all of these.
- **Status:** Tested against the 6 real false positives plus 3 real true positives from an actual run. 9/9 correct.
- **Code:** [src/quality_gate.py](../src/quality_gate.py) — `_NEGATION_PHRASES`, `_is_negated()`, `_text_haystack()` restricted to concerns + flags.

### 2026-06-05 — Spine integration starts with `client_brand_context`, not profiles
- **Decision:** First spine integration is per-client rubric sync, not per-creator profile sync.
- **Why:** Smallest unit of value. Got Kloris's training into the central DB so any future tool gets the same brief Claude uses locally. Profile push (Option A — every vetted creator into `profiles`) is the next piece.
- **Implementation:** [scripts/sync_brand_context_to_spine.py](../scripts/sync_brand_context_to_spine.py). Versioned atomic writes: existing active row → `active=false, archived_at=now()`, new row → `active=true, version=previous+1`.

### 2026-06-05 — Kloris context scraped from Slack
- **Decision:** Fill `knowledge/clients/Kloris/` from Slack history (#internal-kloris, #augmentum-kloris, #discovery-apportioning) rather than wait for the onboarding call.
- **What landed:** Brand context (premium UK wellness, April 2026 pivot from CBD-led identity), 12 target niches, ~1.8k chars of scoring notes, ~5.6k chars of scoring style.
- **Status:** Pushed to spine as version 1 (active). Onboarding-call notes can be layered as version 2 when they arrive.

### 2026-06-07 — Directory tidy-up + `to-archive/` + `.gitignore`
- **Decision:** Pull stale artefacts out of the live tree into a structured `to-archive/` holding pen rather than deleting outright. Add `.gitignore` so generated files stop reaccumulating.
- **Archive contents (152 MB):**
  - `empty-runs/` — 10 zero- and two-byte `enriched_*.csv` files from crashed runs (no header even written).
  - `superseded-inputs/` — `.xlsx` duplicates of CSVs + generic-named test files.
  - `reference/` — `creator_vetting_rubric.docx` (Word origin of `knowledge/expertise.md`).
  - `duplicate-assets/` — bare `Logo` file (unused; loaded one is `logo.jpg`).
  - `orphaned-reels/` — 12 `.mp4` files (149 MB) from runs that crashed before the `finally` cleanup.
- **Deleted outright (not archived):** all `__pycache__/` dirs, `.DS_Store` files. Both regenerate / are OS junk.
- **Empty working dirs preserved** via `.gitkeep` (input/, output/, temp/).
- **README at archive root** explains every subfolder and when it's safe to `rm -rf to-archive/`.

### 2026-06-05 — Entry point renamed `app.py` → `Homepage.py`
- **Decision:** Rename so sidebar nav reads "Homepage" instead of "app".
- **Why:** Streamlit derives sidebar labels from filenames. "app" was opaque.
- **Updated:** Dockerfile CMD, launch.bat, SYSTEM_CONTEXT.md, file docstring.
- **Run command:** `streamlit run Homepage.py` from the project root.

### 2026-06-05 — Text greys darkened (WCAG AAA)
- **Decision:** `--text-secondary` `#6E6E73` → `#424246` (9.3:1). `--text-muted` `#86868B` → `#5A5A60` (6.7:1). Also bulk-replaced hardcoded hex values in inline page styles.
- **Why:** User reported grey text not legible on white. The Apple `#86868B` only hits 4.04:1, fails WCAG AA. New values pass AAA.
- **Code:** [../src/ui_styles.py](../src/ui_styles.py) tokens; the four page files for inline overrides.

### 2026-06-05 — Button-text legibility — switched to near-black (final, after one pink iteration)
- **Iteration 1:** Deeper pink `#D91775` (4.59:1 contrast). User reported "still not legible" — mathematically passes WCAG AA but reads as low-contrast at button-text size in practice.
- **Final:** Primary button background `#1D1D1F` (same as body text), white text — 16.6:1 contrast, unmissable. Hover `#000000`. Focus ring is a translucent pink halo so the brand still pulses in on interaction.
- **Brand pink stays everywhere else** (active sidebar nav, "Creator" wordmark, hero badge, section dashes, step numbers, multiselect tags, badges, tier-B colour, focus rings). Buttons are not where the brand needs to live; the call-to-action is.
- **Coverage:** Added `[data-testid="baseButton-primary"]` and `[data-testid="baseButton-primaryFormSubmit"]` selectors plus `* { color: #FFFFFF !important }` so nested BaseWeb spans inherit white.
- **Code:** [../src/ui_styles.py](../src/ui_styles.py) — button rules block.

### 2026-06-05 — Build Shortlist chunking + lenient JSON parser
- **Decision:** Chunk creators into batches of 25 for the Claude filter call, with `max_tokens=8000` per chunk. Parse JSON leniently (strip code fences, extract first `{...}` block on parse failure).
- **Why:** First Kloris filter on a 76-creator CSV returned "0 approved" — Claude actually approved 17 but the response was truncated by the hardcoded `max_tokens=2048` in `AnthropicClient.chat()`, breaking the JSON parser. Chunking + bumped budget + lenient parser fixes all three failure modes.
- **Code:**
  - [../src/llm_client.py](../src/llm_client.py) — added `max_tokens` parameter to `chat()`.
  - [../pages/2_Build_Shortlist.py](../pages/2_Build_Shortlist.py) — `_CHUNK_SIZE`, `_MAX_TOKENS_PER_CHUNK`, `_run_one_chunk()`, `_parse_json_lenient()`, batched `_filter_creators_with_claude()`.

### 2026-06-05 — Light-mode UI (Option B from the brainstorm)
- **Decision:** Swap from dark mode + animated effects to Apple-style light mode. Adopt plain-language labels for tier/gate/recommendation across the UI.
- **Why:** "Easier to understand" — reduces developer-tool feel, calmer for daily ops use, closer to augmentum-media.com's editorial pages.
- **Shipped:** Light theme via [src/ui_styles.py](../src/ui_styles.py); three pages renumbered (1_Vet_Creators / 2_Build_Shortlist / 3_Train_Clients); descriptive copy on every label/button; plain-language labels via [src/ui_labels.py](../src/ui_labels.py); sample CSV download; first-run model download notice; sidebar active-client carries into Build Shortlist; essential columns shown by default with full data behind an expander.
- **Deferred:** "What is this?" onboarding text on home page (user said not needed yet).
- **Removed:** `pages/1_Pipeline.py`, `pages/3_Agent.py`, `pages/5_Training.py`, all animated effects (orbs, glow, drift).
