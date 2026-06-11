# CLAUDE.md — Behaviour Rules for This Project

> Read [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) first for everything about what
> this system does, how it's built, and what decisions have been made.
> This file only contains rules for how Claude should behave when editing it.

---

## Rules

- **`config/config.yaml` is the source of truth** for niches, CLIP prompts,
  scoring thresholds, gate patterns, and tier cut-offs. Edit there — never
  hardcode the equivalent values in Python.
- **No paid APIs for heavy per-reel work.** Whisper transcription and CLIP
  visual analysis must stay local. LLM judgment per creator is acceptable
  because Claude Haiku is cheap, but vision APIs are not.
- **Never modify the input CSV.** Always write a new
  `output/enriched_<timestamp>.csv`.
- **Wrap reel downloads in `try/finally`** so `temp/*.mp4` is deleted
  after every creator. At 10k creators/week, accumulating videos fills
  disk fast.
- **The Pipeline runs against the global config** (Augmentum-wide rubric).
  Per-client judgment happens in Build Shortlist, not in the Pipeline. The
  sidebar "Active client" drives Build Shortlist and Train Clients only —
  the Pipeline ignores it on purpose.
- **CSV writes are incremental + flushed per row.** Don't batch-write at
  the end of a run — partial runs must remain recoverable.
- **Streamlit pages share styling via `src/ui_styles.py`.** Call `inject()`
  at the top of every new page. Plain-language labels for tier, gate, and
  recommendation come from `src/ui_labels.py` — use them for display, keep
  the structured raw values in the CSV.
- **Quality gate scans `llm_concerns` only** and is negation-aware. If the
  rule changes, update [src/quality_gate.py](src/quality_gate.py) and the
  `quality_gate:` block in `config/config.yaml` — the patterns live in
  config so they're tunable without code edits.
- **Knowledge edits are local until pushed.** Editing
  `knowledge/clients/<name>/` only changes local YAML/markdown. To sync to
  the spine, run
  `python scripts/sync_brand_context_to_spine.py --client <name> --apply`.
- **Do not put project facts in this file.** Architecture, file lists,
  columns, decisions, status — all of that belongs in
  [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md).
