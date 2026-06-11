# Status & Milestones

**Phase:** In production use, actively iterating
**Last Updated:** 2026-06-11

For comprehensive system context see [../SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md).

---

## Done

- [x] **Training flywheel (2026-06-11)**: spine push (profiles + creator_vetting rows, auto after each run; first live --apply awaiting user approval), Calibration Deck page (borderline-first swipes, agreement rate, labels injected into prompts), Evidence & sources tab (uploads + site/Slack/Fathom fetch + distill-to-brief with human confirm)

- [x] **Campaign vetting flow (v2)** — `run_campaign.py` + `src/vetter.py` + `src/campaign.py` + `src/frames.py`: CSV + campaign spec → shortlist/rejected/review CSVs. Hard filters first, then ONE structured Claude vision call (bio + captions + transcripts + sampled frames). Fixes the lyric-transcript false rejections (April Alexander / Richard Bromilow), the "no data = unsafe" gate misfires, and the essay-bloated CSVs from the Thrivin run. See SYSTEM_CONTEXT §2a.
- [x] Thrivin campaign spec (`campaigns/thrivin.yaml`); hard-filter replay validated against the 38-creator Thrivin run
- [x] Pipeline core (v1): fetch → download → transcribe → CLIP → analyzer → scorer → LLM → quality gate → CSV + JSON
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

- Nothing actively in flight. Same-day v2 follow-ups all landed 2026-06-11:
  Thrivin floor → 0.5%, Streamlit UI simplified to Homepage + Vet for
  Campaign + Train Clients (v1 pages archived to `to-archive/legacy-ui/`),
  vetting cache shipped (6-month verdict reuse, `output/vetting_cache.db`),
  Whisper tiny → base.

---

## Up Next (priority order, see SYSTEM_CONTEXT.md §12/§12a for full details)

1. **First live spine push** — `python push_run_to_spine.py --run-dir output/campaigns/test_geo_comments --apply` (the permission layer requires the user to run/approve the first production write; auto-push activates for all later runs).
2. **Top up Modash credits**, then re-vet the full Thrivin CSV with v2 — exercises geo + texture at batch scale and feeds the Calibration Deck + spine.
3. **Label the 7 waiting calibration cards** for Thrivin to establish the first agreement-rate baseline.
4. ~~Spine Option A~~ / ~~Option B (vetting rows)~~ / ~~Corrections UI~~ — shipped 2026-06-11 (auto-push + creator_vetting rows + Correct-a-decision + Calibration Deck).
5. **Rebuild `src/creator_store.py`** — legacy SQLite store interface; source missing, only `.pyc` survives. Low urgency (v1 only).
6. **Push Elavate to spine** — `sync_brand_context_to_spine.py --client Elavate --apply`.
7. **Onboarding-call updates for Kloris** — layer call notes in via the new Evidence tab, re-sync (version 2).

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
