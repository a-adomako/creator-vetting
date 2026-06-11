# Status & Milestones

**Phase:** In production use, actively iterating
**Last Updated:** 2026-06-05

For comprehensive system context see [../SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md).

---

## Done

- [x] Pipeline core: fetch → download → transcribe → CLIP → analyzer → scorer → LLM → quality gate → CSV + JSON
- [x] Streamlit UI shipped: Home + Vet Creators + Build Shortlist + Train Clients
- [x] Light-mode design system with plain-language labels
- [x] Quality gate v2 (universal-disqualifier filter, negation-aware, concerns-only scan)
- [x] Per-client training files: Kloris (filled from Slack), Elavate (filled), AG1 (empty stub)
- [x] Spine sync script for `client_brand_context` table (versioned atomic writes)
- [x] Kloris pushed to central Supabase as version 1
- [x] Modash Raw API integration (profile + reels in one vendor)
- [x] Legacy CLI agent with 13 tools (still works, superseded by Build Shortlist for daily use)

---

## In Progress

- Nothing actively in flight — awaiting user direction on next major piece

---

## Up Next (priority order, see SYSTEM_CONTEXT.md §12 for full details)

1. **Spine Option A** — push every vetted creator's `profiles` row to the central DB on every pipeline run. The gate is reliable, so the precondition is met. ~1–2 days of focused work.
2. **Spine Option B** — push `creator_vetting` rows for per-creator scores. Depends on A. ~3–7 days.
3. **Rebuild `src/creator_store.py`** — the SQLite cross-run store interface. Source file is missing; only `.pyc` survives. CSV-mode codepath works; SQLite codepath broken.
4. **Corrections UI** — let pod members mark a Build Shortlist decision as wrong and persist the reason to the active client's `corrections.md`. Closes the feedback loop.
5. **Push Elavate to spine** — same script, one command (`--client Elavate --apply`). Currently in CreatorVetter locally but not in the central DB.
6. **Onboarding-call updates for Kloris** — once Mark gets the Kloris onboarding call notes, layer them into `knowledge/clients/Kloris/` and re-run the sync (will write version 2).
7. **Extend `clip_prompts` / `niche_keywords`** in config.yaml to cover the niches the Training UI offers (Menopause, Sleep & Recovery, Equestrian, Nature & Country Lifestyle) — currently only 6 niches are scored.

---

## Blocked / On Hold

- **Spine Option C (full orchestrator integration)** — deferred until Discovery portal volume justifies it. Today the portal handles a trickle. Options A and B capture most of the value.
- **`pages/Browse.py`** — depends on `src/creator_store.py` being rebuilt first.

---

## Known minor gaps (housekeeping)

- ~~Several 0-byte `enriched_*.csv` files in `output/`~~ — moved to `to-archive/empty-runs/` (2026-06-07)
- ~~Leftover `.mp4` files in `temp/`~~ — moved to `to-archive/orphaned-reels/` (2026-06-07)
- `launch.bat` hardcoded to a Windows path on Mark's machine
- `docker-compose.yml` service name misspelled as `creatovetter`
- `memory/contacts.md` is an empty stub
- No `tests/` directory — refactors are unprotected
- `to-archive/` (152 MB) holds stale artefacts pending review — see `to-archive/README.md` for what's safe to delete
