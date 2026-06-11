#!/usr/bin/env python3
"""
sync_brand_context_to_spine.py — One-off pusher: local client training → spine.

Reads every folder under `knowledge/clients/<name>/` (profile.yaml + my_style.md),
resolves the matching `clients` row in the Augmentum spine database by slug,
and inserts a new `client_brand_context` row.

Versioning is honoured: if the client already has an active rubric, this script
flips that row's `active=false` and stamps `archived_at=now()` before inserting
the new one with `version = previous + 1` and `created_by='manual'`. The
partial unique index on `client_brand_context(client_id) WHERE active = true`
enforces that only one active row exists per client at any time.

Usage:
    # From workspace root
    source .venv/bin/activate

    # Dry-run (default) — prints what WOULD be written, no DB writes
    python Evergreen/creator_vetter/scripts/sync_brand_context_to_spine.py

    # Apply for one client only
    python Evergreen/creator_vetter/scripts/sync_brand_context_to_spine.py \\
        --apply --client Kloris

    # Apply for every client folder it can map
    python Evergreen/creator_vetter/scripts/sync_brand_context_to_spine.py --apply

Requires DATABASE_URL in the loaded environment. The spine .env at
Evergreen/augmentum-spine/.env is auto-loaded if present. SSL is required by
Supabase — the connection enforces it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENTS_DIR = REPO_ROOT / "knowledge" / "clients"
SPINE_ENV = REPO_ROOT.parent / "augmentum-spine" / ".env"


def _load_env() -> None:
    """Auto-load the spine .env if DATABASE_URL isn't already in env."""
    if os.environ.get("DATABASE_URL"):
        return
    if not SPINE_ENV.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(SPINE_ENV)
    except ImportError:
        # Fallback: parse manually
        for line in SPINE_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def slugify_folder(folder_name: str) -> str:
    """
    Map a CreatorVetter folder name to a spine `clients.slug`.

    Rule (matches dashboard slug rules):
      lowercase → replace & with 'and' → replace + with '-plus' →
      drop apostrophes → collapse non-alphanumeric to single dash → strip dashes
    """
    s = folder_name.lower()
    s = s.replace("&", "and").replace("+", "-plus").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def collect_client(folder: Path) -> Optional[dict]:
    """Read profile.yaml + my_style.md from one client folder."""
    profile_path = folder / "profile.yaml"
    style_path = folder / "my_style.md"

    if not profile_path.exists():
        return None

    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        print(f"  ! Could not parse {profile_path}: {e}", file=sys.stderr)
        return None

    brand_description = (profile.get("brand_context") or "").strip()
    target_niches = profile.get("target_niches") or []
    scoring_notes = (profile.get("scoring_notes") or "").strip()
    scoring_style = ""
    if style_path.exists():
        scoring_style = style_path.read_text(encoding="utf-8").strip()

    if not brand_description and not scoring_style and not target_niches:
        # Empty placeholder folder (like the current AG1) — skip
        return None

    return {
        "folder": folder.name,
        "slug": slugify_folder(folder.name),
        "brand_description": brand_description,
        "target_niches": [str(n) for n in target_niches if str(n).strip()],
        "avoid_niches": [],  # not currently captured in profile.yaml
        "scoring_style": scoring_style,
        "scoring_notes": scoring_notes,
    }


async def fetch_client_id(conn, slug: str) -> Optional[str]:
    """Look up clients.id by slug."""
    row = await conn.fetchrow(
        "SELECT id, display_name FROM clients WHERE slug = $1", slug
    )
    if not row:
        return None
    return row["id"]


async def fetch_active_version(conn, client_id) -> Optional[int]:
    """Return the current active rubric version, or None if none exists."""
    row = await conn.fetchrow(
        """
        SELECT version FROM client_brand_context
        WHERE client_id = $1 AND active = true
        """,
        client_id,
    )
    return row["version"] if row else None


async def upsert_brand_context(conn, client_id, payload: dict, next_version: int) -> str:
    """
    Atomic versioning swap inside a transaction:
      1. flip the existing active row to active=false, archived_at=now()
      2. insert the new row with active=true, version=next_version
    """
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE client_brand_context
            SET active = false, archived_at = now()
            WHERE client_id = $1 AND active = true
            """,
            client_id,
        )
        new_id = await conn.fetchval(
            """
            INSERT INTO client_brand_context (
                client_id,
                brand_description,
                target_niches,
                avoid_niches,
                scoring_style,
                scoring_notes,
                version,
                created_by,
                active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'manual', true)
            RETURNING id
            """,
            client_id,
            payload["brand_description"] or None,
            payload["target_niches"],
            payload["avoid_niches"],
            payload["scoring_style"] or None,
            payload["scoring_notes"] or None,
            next_version,
        )
    return str(new_id)


async def run(apply: bool, client_filter: Optional[str]) -> int:
    import asyncpg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set and could not be loaded from spine .env",
              file=sys.stderr)
        return 1

    # asyncpg wants postgresql://, not postgresql+asyncpg://
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)

    # Walk client folders
    if not CLIENTS_DIR.exists():
        print(f"ERROR: {CLIENTS_DIR} not found", file=sys.stderr)
        return 1

    candidates = []
    for folder in sorted(CLIENTS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if client_filter and folder.name.lower() != client_filter.lower():
            continue
        client = collect_client(folder)
        if client:
            candidates.append(client)
        else:
            print(f"  · skipping {folder.name} (empty profile.yaml)")

    if not candidates:
        print("No clients with non-empty training data found. Nothing to do.")
        return 0

    print(f"\nMode: {'APPLY (writing to DB)' if apply else 'DRY RUN (no writes)'}")
    print(f"Clients to process: {', '.join(c['folder'] for c in candidates)}\n")

    conn = await asyncpg.connect(dsn, ssl="require")
    try:
        success = 0
        skipped = 0
        for client in candidates:
            slug = client["slug"]
            print(f"── {client['folder']} (slug: {slug}) ──")

            client_id = await fetch_client_id(conn, slug)
            if not client_id:
                print(f"  ! No clients row with slug='{slug}' — skipping. "
                      f"Either fix the local folder name or insert the client first.")
                skipped += 1
                print()
                continue

            current_version = await fetch_active_version(conn, client_id)
            next_version = (current_version or 0) + 1
            action = (
                f"INSERT new rubric (version {next_version})"
                if current_version is None
                else f"DEACTIVATE v{current_version}, INSERT v{next_version}"
            )

            niche_count = len(client["target_niches"])
            print(f"  client_id        : {client_id}")
            print(f"  action           : {action}")
            print(f"  brand_description: {len(client['brand_description'])} chars")
            print(f"  target_niches    : {niche_count} ({', '.join(client['target_niches'][:5])}"
                  f"{'…' if niche_count > 5 else ''})")
            print(f"  scoring_style    : {len(client['scoring_style'])} chars")
            print(f"  scoring_notes    : {len(client['scoring_notes'])} chars")

            if not apply:
                print("  (dry run — no write)\n")
                success += 1
                continue

            new_id = await upsert_brand_context(conn, client_id, client, next_version)
            print(f"  → wrote client_brand_context.id = {new_id}\n")
            success += 1

        print(f"── Done. Processed: {success}, skipped: {skipped} ──")
        if not apply and success > 0:
            print("Re-run with --apply to write the changes to the database.")
        return 0 if skipped == 0 else 2
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to the DB. Default is dry-run.")
    parser.add_argument("--client", type=str, default=None,
                        help="Limit to a single client folder name (case-insensitive). "
                             "Default: process every folder.")
    args = parser.parse_args()

    _load_env()
    return asyncio.run(run(apply=args.apply, client_filter=args.client))


if __name__ == "__main__":
    sys.exit(main())
