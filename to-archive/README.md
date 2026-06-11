# to-archive/

Holding pen for files that aren't part of the active project but shouldn't be
deleted without thought. Everything in here was moved out of the live tree on
2026-06-07 during a directory clean-up — see [SYSTEM_CONTEXT.md §17](../SYSTEM_CONTEXT.md)
for the matching decision-log entry.

Review each subfolder periodically. Once you're confident the contents aren't
needed, the whole `to-archive/` folder can be deleted in one shot.

---

## What's in here

### `empty-runs/` (10 files, ~24 KB)
Zero-byte and two-byte `enriched_*.csv` files from pipeline runs that crashed
before writing the header row. They have no data — they only survived because
the pipeline creates the output file before processing the first creator. Safe
to delete; nothing references them.

### `superseded-inputs/` (3 files, ~3 MB)
- `Creators - 2.xlsx` — Excel version of `input/Creators - 2.csv`. The CSV
  is what the pipeline reads, so the `.xlsx` is dead weight.
- `your_file.csv`, `your_file.xlsx` — generic placeholder names from the
  earliest test runs. Real-named CSVs (`Kloris_to_be_vetted.csv`,
  `test 1.csv`) supersede them.

### `reference/` (1 file)
- `creator_vetting_rubric.docx` — the original Word document that became
  [`knowledge/expertise.md`](../knowledge/expertise.md). The `.md` version is
  the live source of truth; the `.docx` is kept as the origin artefact for
  legal / audit / "what did Augmentum start with" purposes.

### `duplicate-assets/` (1 file)
- `Logo` — an unnamed image file (no extension) that was duplicated at the
  project root. `Homepage.py` actually loads `logo.jpg`, so this one was
  unused. Kept rather than deleted in case it's the canonical brand source.

### `orphaned-reels/` (12 files, ~149 MB)
Reel `.mp4` files that the pipeline downloaded into `temp/` and would
normally have deleted in its `finally` block — but the run crashed before
reaching cleanup. These are the largest artefacts in the archive. **Safe to
delete: the transcripts and visual analysis from these reels are already
captured in `output/profiles/<username>.json` (where applicable), and the
creators themselves are scored in the enriched CSVs from those runs.**

---

## When to delete the whole folder

Once you've confirmed:
- No 0-byte or 2-byte CSV in `empty-runs/` is actually being referenced by
  some downstream tool (none should be — they're literally empty).
- The `.xlsx` files in `superseded-inputs/` aren't the master source — the
  matching `.csv` files in `input/` should already cover the same data.
- The `.docx` rubric is fully reflected in [`knowledge/expertise.md`](../knowledge/expertise.md)
  and you don't need to refer back to the original Word formatting.
- The orphaned reel videos haven't been retroactively re-analysed by some
  script you wrote (very unlikely — they're temp data).

…then `rm -rf to-archive/` is safe and reclaims ~152 MB.
