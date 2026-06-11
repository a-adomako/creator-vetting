"""
llm_client.py — Abstraction layer for LLM providers.

Supports Ollama (local, free) and Anthropic Claude API.
Switch providers by setting LLM_PROVIDER in your .env file:

  LLM_PROVIDER=ollama       (default, free)
  LLM_PROVIDER=anthropic    (Claude API, requires ANTHROPIC_API_KEY)
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_llm_client(provider: str = None, model: str = None):
    """Return the appropriate LLM client based on LLM_PROVIDER env var."""
    provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
    model = model or os.getenv("LLM_MODEL", "llama3.2")

    if provider == "anthropic":
        return AnthropicClient(model=model)
    else:
        return OllamaClient(model=model)


class OllamaClient:
    """Local Ollama client — free, runs on your machine."""

    def __init__(self, model: str = "llama3.2"):
        self.model = model
        try:
            import ollama as _ollama
            self._ollama = _ollama
        except ImportError:
            raise ImportError(
                "ollama package not installed. Run: pip install ollama"
            )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] = None,
        system: str = None,
        max_tokens: int = 2048,  # ignored by Ollama provider; here for API parity
        tool_choice: dict = None,  # ignored by Ollama provider; here for API parity
    ) -> dict:
        """
        Send messages and return response dict with:
          - content: str (text reply)
          - tool_calls: list of {name, arguments} dicts (may be empty)
          - stop_reason: str

        max_tokens is accepted for API parity with AnthropicClient but Ollama
        clients don't enforce it the same way; the local model will run to its
        own stop condition.
        """
        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        ollama_messages.extend(messages)

        kwargs: dict[str, Any] = {"model": self.model, "messages": ollama_messages}
        if tools:
            kwargs["tools"] = tools

        response = self._ollama.chat(**kwargs)
        msg = response.message

        tool_calls = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or {},
                })

        return {
            "content": msg.content or "",
            "tool_calls": tool_calls,
            "stop_reason": "tool_use" if tool_calls else "end_turn",
        }

    def __str__(self):
        return f"Ollama/{self.model}"


class AnthropicClient:
    """Anthropic Claude API client."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model
        try:
            import anthropic as _anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not set in .env — required for Anthropic provider"
                )
            self._client = _anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] = None,
        system: str = None,
        max_tokens: int = 2048,
        tool_choice: dict = None,
    ) -> dict:
        """
        Send messages and return response dict.

        max_tokens defaults to 2048 (fine for the per-creator LLM analyzer pass).
        Callers like Build Shortlist that need long structured JSON output
        should bump this to ~8000 to avoid mid-response truncation.

        tool_choice (e.g. {"type": "tool", "name": "record_vetting_verdict"})
        forces the model to respond via that tool — guarantees schema-valid
        structured output with no JSON parsing. Used by the campaign vetter.
        Message content may be a list of content blocks (text + image) for
        vision calls; blocks are passed through to the API verbatim.
        """
        import time
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        for attempt in range(5):
            try:
                response = self._client.messages.create(**kwargs)
                break
            except Exception as e:
                if "rate_limit" in str(e).lower() or "529" in str(e) or "429" in str(e):
                    wait = 60 * (attempt + 1)
                    print(f"\n[Rate limit hit — waiting {wait}s before retry...]\n")
                    time.sleep(wait)
                else:
                    raise

        content_text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": block.name,
                    "arguments": block.input or {},
                    "id": block.id,
                })

        return {
            "content": content_text,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
        }

    def __str__(self):
        return f"Anthropic/{self.model}"
