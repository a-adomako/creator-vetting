#!/usr/bin/env python3
"""
agent.py — Conversational influencer selection agent.

The agent reads your creator database and helps you build shortlists
through natural conversation — just like briefing a team member.

Usage:
  python agent.py --db output/enriched_20260412_090138.csv

Commands during chat:
  Type anything naturally. Examples:
    "Find me 50 fitness creators with over 50k followers"
    "Show me the full profile for @username"
    "Add @username to the shortlist — great nutrition content"
    "Remove @username"
    "Show my shortlist"
    "Export the shortlist as spring_wellness"
    "exit" or "quit" to end the session

Provider is set by LLM_PROVIDER in your .env file:
  LLM_PROVIDER=ollama      (default, free local)
  LLM_PROVIDER=anthropic   (Claude API)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Tool definitions (sent to the LLM so it knows what it can call) ──────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_creators",
            "description": (
                "Search and filter the creator database. Returns ranked creators matching "
                "the given criteria. Use this whenever the user asks to find, search, or "
                "show creators. All parameters are optional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "niches": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by niche(s). Options: Health & Wellness, Fitness, Fashion, Lifestyle, Beauty & Skincare, Food & Beverage",
                    },
                    "min_followers": {"type": "integer", "description": "Minimum follower count"},
                    "max_followers": {"type": "integer", "description": "Maximum follower count"},
                    "min_engagement_rate": {"type": "number", "description": "Minimum engagement rate as a percentage (e.g. 2.0 means 2%)"},
                    "min_tier": {"type": "string", "enum": ["A", "B", "C", "D"], "description": "Minimum quality tier (A is best)"},
                    "min_brand_fit_score": {"type": "number", "description": "Minimum brand fit score 0-100"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords that must appear in the creator's transcript or content summary",
                    },
                    "exclude_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exclude creators with these flags. Common flags: private_account, low_engagement, stale_Xd",
                    },
                    "limit": {"type": "integer", "description": "Max number of results to return (default 20)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_creator_profile",
            "description": (
                "Load the full detailed profile for a specific creator — includes complete "
                "transcripts from all their reels, CLIP visual scores, production quality, "
                "and all engagement metrics. Use this when the user wants to know more about "
                "a specific creator or when you need to make a nuanced judgment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Instagram username (with or without @)"},
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_shortlist",
            "description": "Add a creator to the session shortlist with a reason explaining why they are a good fit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Instagram username"},
                    "reason": {"type": "string", "description": "2-3 sentence explanation of why this creator fits the campaign"},
                },
                "required": ["username", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_shortlist",
            "description": "Remove a creator from the session shortlist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Instagram username to remove"},
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shortlist",
            "description": "Return the current shortlist of selected creators.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_shortlist",
            "description": "Export the current shortlist to a CSV file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "Name for the campaign / output file"},
                },
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_creator_for_campaign",
            "description": (
                "Use AI to deeply analyze a specific creator's profile content against a campaign brief. "
                "Reads their full transcript and visual scene data, then returns qualitative scores for "
                "brand fit, authenticity, content consistency, brand safety, and production quality — "
                "plus a list of strengths, concerns, and a yes/maybe/no recommendation. "
                "Use this when the user wants a detailed AI-powered evaluation of a specific creator, "
                "or before adding someone to the shortlist when you want deeper confidence in the match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Instagram username (with or without @)"},
                    "campaign_brief": {
                        "type": "string",
                        "description": (
                            "Description of the campaign — what brand, product, target audience, "
                            "and what you're looking for in a creator"
                        ),
                    },
                },
                "required": ["username", "campaign_brief"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_creators",
            "description": (
                "Search the Influencers.Club database of 200M+ creators using flexible filters. "
                "Returns a list of matching profiles with follower counts and engagement rates. "
                "Use this to discover new creators for campaigns. Filters are flexible — try any combination: "
                "followers_min, followers_max, engagement_min, engagement_max, niche, category, location, language. "
                "After discovery, call queue_for_vetting to process selected creators through the full pipeline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["instagram", "tiktok", "youtube", "twitch", "twitter", "onlyfans"],
                        "description": "Platform to search (default: instagram)",
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "Flexible filter dict passed directly to the API. Try any of these keys: "
                            "followers_min, followers_max, engagement_min, engagement_max, niche, category, "
                            "location, language. Experiment freely."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max profiles to return (default 20, max 100)",
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": (
                            "If set, creators already used in this campaign are automatically excluded from results"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_for_vetting",
            "description": (
                "Queue a list of usernames to be processed by the full vetting pipeline "
                "(Apify scrape, CLIP analysis, LLM scoring). After calling this, "
                "go to the Pipeline page, select the queued CSV file, and run it. "
                "Analyzed creators will appear in the Browse page when done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "usernames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Instagram usernames to queue for vetting",
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": "Optional campaign name for tracking",
                    },
                },
                "required": ["usernames"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_briefs",
            "description": (
                "List all available campaign briefs stored in knowledge/briefs/. "
                "Each brief contains campaign goals, target audience, niche, follower tier, "
                "location, engagement requirements, and brand safety notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_brief",
            "description": (
                "Read the full content of a campaign brief by name. "
                "Use this to review a brief before running discovery from it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brief_name": {
                        "type": "string",
                        "description": "Name of the brief file (with or without .md extension)",
                    },
                },
                "required": ["brief_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_via_modash",
            "description": (
                "Discover creators via Modash API with flexible filters. "
                "Modash provides access to a vast database of Instagram creators with detailed metrics. "
                "Filters: followers {min/max}, engagementRate {min/max}, location {country codes}, "
                "language, categories (niches), bio keywords. "
                "After discovery, queue results for vetting via queue_for_vetting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Modash search filters. Keys: followers, engagementRate, location, language, categories, bio",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results to return (default 20, max 100)",
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": "Optional campaign name for tracking",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brief_to_discovery",
            "description": (
                "Extract Modash filters from a campaign brief and run discovery. "
                "This tool reads a brief file, uses Claude to parse the brief into structured Modash filters, "
                "then automatically searches Modash for matching creators. "
                "This is the main brief-driven discovery workflow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brief_name": {
                        "type": "string",
                        "description": "Name of the brief file (with or without .md extension)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results to return (default 20, max 100)",
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": "Optional campaign name for tracking",
                    },
                },
                "required": ["brief_name"],
            },
        },
    },
]

# Anthropic-style tool format (used when provider=anthropic)
TOOLS_ANTHROPIC = [
    {
        "name": "search_creators",
        "description": TOOLS[0]["function"]["description"],
        "input_schema": TOOLS[0]["function"]["parameters"],
    },
    {
        "name": "get_creator_profile",
        "description": TOOLS[1]["function"]["description"],
        "input_schema": TOOLS[1]["function"]["parameters"],
    },
    {
        "name": "add_to_shortlist",
        "description": TOOLS[2]["function"]["description"],
        "input_schema": TOOLS[2]["function"]["parameters"],
    },
    {
        "name": "remove_from_shortlist",
        "description": TOOLS[3]["function"]["description"],
        "input_schema": TOOLS[3]["function"]["parameters"],
    },
    {
        "name": "get_shortlist",
        "description": TOOLS[4]["function"]["description"],
        "input_schema": TOOLS[4]["function"]["parameters"],
    },
    {
        "name": "export_shortlist",
        "description": TOOLS[5]["function"]["description"],
        "input_schema": TOOLS[5]["function"]["parameters"],
    },
    {
        "name": "analyze_creator_for_campaign",
        "description": TOOLS[6]["function"]["description"],
        "input_schema": TOOLS[6]["function"]["parameters"],
    },
    {
        "name": "discover_creators",
        "description": TOOLS[7]["function"]["description"],
        "input_schema": TOOLS[7]["function"]["parameters"],
    },
    {
        "name": "queue_for_vetting",
        "description": TOOLS[8]["function"]["description"],
        "input_schema": TOOLS[8]["function"]["parameters"],
    },
    {
        "name": "list_briefs",
        "description": TOOLS[9]["function"]["description"],
        "input_schema": TOOLS[9]["function"]["parameters"],
    },
    {
        "name": "read_brief",
        "description": TOOLS[10]["function"]["description"],
        "input_schema": TOOLS[10]["function"]["parameters"],
    },
    {
        "name": "discover_via_modash",
        "description": TOOLS[11]["function"]["description"],
        "input_schema": TOOLS[11]["function"]["parameters"],
    },
    {
        "name": "brief_to_discovery",
        "description": TOOLS[12]["function"]["description"],
        "input_schema": TOOLS[12]["function"]["parameters"],
    },
]


def load_expertise() -> str:
    """Load the expertise file from knowledge/expertise.md."""
    expertise_path = Path("knowledge/expertise.md")
    if expertise_path.exists():
        return expertise_path.read_text(encoding="utf-8")
    return ""


def build_system_prompt(db, expertise: str) -> str:
    stats = db.summary_stats()
    stats_str = json.dumps(stats, indent=2)
    return f"""You are an experienced influencer selection specialist working with a creator database.
Your job is to help find and shortlist the right creators for specific campaigns.

{expertise}

---

## Current Database

{stats_str}

---

## How to work

**Discovery workflow:**
- Prefer brief-driven discovery via brief_to_discovery for new campaigns — it reads a brief and automatically searches Modash
- Use list_briefs to show available briefs, read_brief to review a brief's contents before running discovery
- For manual discovery, use discover_via_modash (Modash API) over discover_creators (Influencers.Club) — Modash has richer demographic data
- After any discovery, offer to queue matching creators for vetting via queue_for_vetting

**Modash search parameters (for discover_via_modash):**
Use these keys in the filters dict. All are optional — combine them for precision:
  - `followers`: {min: 5000, max: 100000} — follower count range
  - `engagementRate`: {min: 2.0} — minimum engagement % (e.g. 2.0 = 2%)
  - `categories`: ["fitness", "health", "wellness"] — niche keywords (case-sensitive; common: fitness, health, beauty, fashion, lifestyle, food, travel, gaming, tech)
  - `language`: ["en"] — language codes (en, es, fr, de, it)
  - `location`: {country: ["GB", "US", "CA"]} — ISO 3166-1 alpha-2 country codes
  - `bio`: {keywords: ["organic", "certified", "sustainable"]} — must-have bio keywords
  - `isVerified`: true/false — verified badge filter
When the user mentions a campaign, extract these filters thoughtfully from the campaign context. Start broad if unsure, then refine based on feedback.

**Shortlisting workflow:**
- ALWAYS call get_creator_profile before calling add_to_shortlist — no exceptions. You must read the full transcript and visual data before recommending anyone. Never shortlist based on CSV numbers alone.
- Use analyze_creator_for_campaign when the user wants a deep AI-powered evaluation of a specific creator, or when you want higher confidence before shortlisting
- When recommending someone, cite what you actually read in their profile (transcript content, scenes, tone) — not just their scores

**General principles:**
- Be direct and opinionated — give real recommendations, not just data dumps
- Explain your reasoning in plain English, the way you'd brief a colleague
- If a creator's metrics look good but their content doesn't match, say so
- The user may push back — take feedback seriously and adjust your recommendations
"""


def dispatch_tool(db, tool_name: str, arguments: dict, client_dir=None) -> str:
    """Call the appropriate database tool and return result as JSON string."""
    try:
        if tool_name == "search_creators":
            result = db.search_creators(**arguments)
        elif tool_name == "get_creator_profile":
            result = db.get_creator_profile(**arguments)
        elif tool_name == "add_to_shortlist":
            result = db.add_to_shortlist(**arguments)
        elif tool_name == "remove_from_shortlist":
            result = db.remove_from_shortlist(**arguments)
        elif tool_name == "get_shortlist":
            result = db.get_shortlist()
        elif tool_name == "export_shortlist":
            result = db.export_shortlist(**arguments)
        elif tool_name == "analyze_creator_for_campaign":
            result = db.analyze_creator_for_campaign(**arguments, client_dir=client_dir)
        elif tool_name == "discover_creators":
            result = db.discover_creators(**arguments)
        elif tool_name == "queue_for_vetting":
            result = db.queue_for_vetting(**arguments)
        elif tool_name == "list_briefs":
            result = db.list_briefs()
        elif tool_name == "read_brief":
            result = db.read_brief(**arguments)
        elif tool_name == "discover_via_modash":
            result = db.discover_via_modash(**arguments)
        elif tool_name == "brief_to_discovery":
            result = db.brief_to_discovery(**arguments)
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": str(e)}

    return json.dumps(result, default=str)


def chat_loop(db, llm, provider: str):
    """Main conversation loop."""
    expertise = load_expertise()
    system_prompt = build_system_prompt(db, expertise)
    messages = []
    tools = TOOLS_ANTHROPIC if provider == "anthropic" else TOOLS

    print(f"\n  Influencer Selection Agent  ({llm})")
    print(f"  Database: {len(db.df):,} creators loaded")
    print("  Type your request, or 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            shortlist_size = len(db.shortlist)
            if shortlist_size > 0:
                print(f"\nYou have {shortlist_size} creators on your shortlist.")
                save = input("Export before exiting? (y/n): ").strip().lower()
                if save == "y":
                    name = input("Campaign name: ").strip() or "session"
                    result = db.export_shortlist(name)
                    print(f"Exported to: {result.get('path', 'unknown')}")
            print("Goodbye.")
            break

        messages.append({"role": "user", "content": user_input})

        # Agentic loop — keep going until the model stops calling tools
        while True:
            response = llm.chat(messages=messages, tools=tools, system=system_prompt)

            # If there are tool calls, dispatch them and feed results back
            if response["tool_calls"]:
                # Add assistant message with tool calls
                if provider == "anthropic":
                    # Anthropic expects content blocks
                    assistant_content = []
                    if response["content"]:
                        assistant_content.append({"type": "text", "text": response["content"]})
                    for tc in response["tool_calls"]:
                        assistant_content.append({
                            "type": "tool_use",
                            "id": tc.get("id", f"tool_{tc['name']}"),
                            "name": tc["name"],
                            "input": tc["arguments"],
                        })
                    messages.append({"role": "assistant", "content": assistant_content})

                    # Tool results
                    tool_results = []
                    for tc in response["tool_calls"]:
                        result_str = dispatch_tool(db, tc["name"], tc["arguments"])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.get("id", f"tool_{tc['name']}"),
                            "content": result_str,
                        })
                    messages.append({"role": "user", "content": tool_results})

                else:
                    # Ollama format
                    messages.append({"role": "assistant", "content": response["content"], "tool_calls": [
                        {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in response["tool_calls"]
                    ]})
                    for tc in response["tool_calls"]:
                        result_str = dispatch_tool(db, tc["name"], tc["arguments"])
                        messages.append({
                            "role": "tool",
                            "content": result_str,
                        })

                # Continue the loop to get the model's response after tool results
                continue

            # No tool calls — this is the final response to show the user
            reply = response["content"].strip()
            if reply:
                print(f"\nAgent: {reply}\n")
            messages.append({"role": "assistant", "content": reply})
            break


def main():
    parser = argparse.ArgumentParser(
        description="Influencer Selection Agent — conversational creator database search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db", required=True,
        help="Path to enriched CSV (output of run.py)",
    )
    parser.add_argument(
        "--provider",
        help="LLM provider: ollama or anthropic (overrides LLM_PROVIDER in .env)",
    )
    parser.add_argument(
        "--model",
        help="Model name (overrides LLM_MODEL in .env)",
    )
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Error: Database file not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    provider = (args.provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
    model = args.model or os.getenv("LLM_MODEL", "llama3.2")

    # Load database
    from src.agent_tools import CreatorDatabase
    db = CreatorDatabase(args.db)

    # Load LLM client
    from src.llm_client import get_llm_client
    try:
        llm = get_llm_client(provider=provider, model=model)
    except (ImportError, ValueError) as e:
        print(f"Error loading LLM client: {e}", file=sys.stderr)
        sys.exit(1)

    # Wire LLM into database so analyze_creator_for_campaign works
    db.llm = llm

    chat_loop(db, llm, provider)


if __name__ == "__main__":
    main()
