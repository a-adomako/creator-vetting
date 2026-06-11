"""
evidence.py — Evidence intake + distillation for client training.

The training principle (decided 2026-06-11): client briefs are GENERATED
from evidence, not typed into blank boxes. This module handles the three
evidence routes and the distillation step:

  1. UPLOADS — decks, briefs, transcripts, sheets dropped into
     knowledge/clients/<name>/evidence/.
  2. FETCH — Claude goes and gets it: brand website, the client's
     #internal-* Slack channel, Fathom call transcripts. Credentials load
     from the workspace root .env (SLACK_BOT_TOKEN / FATHOM_API_KEY).
  3. DISTILL — Claude extracts judgment-relevant claims from any evidence
     text, with provenance, as a draft the human confirms before it lands
     in my_style.md.

Raw evidence NEVER goes into judgment prompts — only the distilled brief
does. Uploads are stored verbatim for provenance.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
WORKSPACE_ENV = PROJECT_ROOT.parent.parent / ".env"

_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".yaml", ".yml", ".json"}


def _workspace_env(key: str) -> Optional[str]:
    """Read a credential from the env, falling back to the workspace .env."""
    if os.getenv(key):
        return os.getenv(key)
    if WORKSPACE_ENV.exists():
        for line in WORKSPACE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    return None


def evidence_dir(client_dir: Path) -> Path:
    d = Path(client_dir) / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(client_dir: Path, filename: str, data: bytes) -> Path:
    safe = re.sub(r"[^\w.\- ]+", "_", filename)
    path = evidence_dir(client_dir) / safe
    path.write_bytes(data)
    return path


def read_evidence_text(path: Path, max_chars: int = 60_000) -> str:
    """Extract text from one evidence file. PDFs need pypdf; others read raw."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            return "[PDF support needs: pip install pypdf]"
        except Exception as e:
            return f"[Could not read PDF: {e}]"
    elif path.suffix.lower() in _TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Could not read file: {e}]"
    else:
        return f"[Unsupported file type: {path.suffix}]"
    return text[:max_chars]


# ── Fetch routes ─────────────────────────────────────────────────────────────

def fetch_website_text(url: str, max_chars: int = 40_000) -> str:
    """Fetch a brand page and strip it to readable text."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    resp = requests.get(
        url, timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (CreatorVetter evidence fetch)"},
    )
    resp.raise_for_status()
    html = resp.text
    html = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", html).strip()
    return text[:max_chars]


def fetch_slack_channel_text(
    channel_hint: str, max_messages: int = 400, max_chars: int = 60_000
) -> str:
    """
    Pull recent messages from the client's Slack channel (e.g.
    'internal-thrivin'). Needs SLACK_BOT_TOKEN with the bot in the channel.
    """
    token = _workspace_env("SLACK_BOT_TOKEN") or _workspace_env("SLACK_USER_TOKEN")
    if not token:
        return "[No SLACK_BOT_TOKEN / SLACK_USER_TOKEN available]"
    headers = {"Authorization": f"Bearer {token}"}
    hint = channel_hint.lstrip("#").lower()

    # Resolve channel id by name
    channel_id, cursor = None, None
    for _ in range(10):
        params = {"limit": 200, "types": "public_channel,private_channel"}
        if cursor:
            params["cursor"] = cursor
        r = requests.get("https://slack.com/api/conversations.list",
                         headers=headers, params=params, timeout=20)
        data = r.json()
        if not data.get("ok"):
            return f"[Slack error: {data.get('error')}]"
        for ch in data.get("channels", []):
            if ch.get("name", "").lower() == hint:
                channel_id = ch["id"]
                break
        if channel_id:
            break
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    if not channel_id:
        return f"[Slack channel '#{hint}' not found or bot not a member]"

    # Pull history
    messages, cursor = [], None
    while len(messages) < max_messages:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get("https://slack.com/api/conversations.history",
                         headers=headers, params=params, timeout=20)
        data = r.json()
        if not data.get("ok"):
            return f"[Slack history error: {data.get('error')}]"
        for m in data.get("messages", []):
            text = (m.get("text") or "").strip()
            if text:
                messages.append(text)
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    return "\n---\n".join(messages)[:max_chars] or "[Channel is empty]"


def fetch_fathom_transcripts(
    client_name: str, max_meetings: int = 5, max_chars: int = 60_000
) -> str:
    """Recent Fathom meetings whose title mentions the client."""
    key = _workspace_env("FATHOM_API_KEY")
    if not key:
        return "[No FATHOM_API_KEY available]"
    headers = {"X-Api-Key": key}
    needle = client_name.lower().split("-")[0]

    matches, cursor = [], None
    for _ in range(5):
        params = {"include_transcript": "true"}
        if cursor:
            params["cursor"] = cursor
        r = requests.get("https://api.fathom.ai/external/v1/meetings",
                         headers=headers, params=params, timeout=120)
        if r.status_code != 200:
            return f"[Fathom error: HTTP {r.status_code}]"
        data = r.json()
        for m in data.get("items", []):
            title = (m.get("title") or m.get("meeting_title") or "").lower()
            if needle in title:
                transcript = m.get("transcript") or []
                if isinstance(transcript, list):
                    text = "\n".join(
                        f"{(t.get('speaker') or {}).get('display_name', '?')}: "
                        f"{t.get('text', '')}"
                        for t in transcript
                    )
                else:
                    text = str(transcript)
                matches.append(f"## {m.get('title', 'meeting')}\n{text}")
                if len(matches) >= max_meetings:
                    break
        if len(matches) >= max_meetings:
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break

    if not matches:
        return f"[No Fathom meetings found mentioning '{needle}']"
    return "\n\n".join(matches)[:max_chars]


# ── Distillation ─────────────────────────────────────────────────────────────

_DISTILL_SYSTEM = """\
You are extracting CREATOR-VETTING rules from raw client evidence for an
influencer marketing agency. From the evidence, pull ONLY claims that change
how a creator should be judged for this client: target audience, geography,
follower/engagement expectations, aesthetic references (on-brand and
off-brand neighbours), niches in and out of scope, deal-breakers, things to
flag for human review, named approved/rejected example creators.

Output clean markdown bullet groups under short headings. Each bullet must
be a judgment rule, phrased as an instruction. Note the source in brackets
at the end of each heading, e.g. "(from: onboarding deck)". Ignore
pleasantries, scheduling chatter, and anything that doesn't affect vetting.
If the evidence contains nothing useful, say exactly: NO_VETTING_SIGNAL
"""


def distill(client_name: str, source_label: str, evidence_text: str) -> str:
    """One Claude call: raw evidence → draft judgment rules with provenance."""
    from .llm_client import AnthropicClient
    model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    client = AnthropicClient(model=model)
    response = client.chat(
        messages=[{
            "role": "user",
            "content": (
                f"Client: {client_name}\nSource: {source_label}\n\n"
                f"--- EVIDENCE ---\n{evidence_text[:50_000]}\n--- END ---\n\n"
                f"Extract the vetting rules."
            ),
        }],
        system=_DISTILL_SYSTEM,
        max_tokens=2000,
    )
    return (response.get("content") or "").strip()


def append_to_style(client_dir: Path, source_label: str, distilled_md: str) -> Path:
    """Merge confirmed distilled rules into my_style.md with provenance."""
    path = Path(client_dir) / "my_style.md"
    stamp = datetime.now().strftime("%Y-%m-%d")
    block = (
        f"\n\n## Distilled from {source_label} ({stamp})\n\n"
        f"{distilled_md.strip()}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return path
