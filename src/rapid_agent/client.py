"""Gemini API client wrapper, with a deterministic stub fallback.

The real client uses `google-generativeai` (free-tier API key).
The stub returns a deterministic, schema-conformant response so tests and the
demo can run without network or a key.

For production, swap GeminiClient for a Vertex AI client; see DEPLOY.md.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


# Approximate free-tier Gemini 1.5 Flash pricing (per 1k tokens).
# Real free tier is $0, but we still track projected cost so the
# BudgetCap is exercised under the demo.
PRICE_INPUT_PER_1K_USD = 0.000075
PRICE_OUTPUT_PER_1K_USD = 0.0003


@dataclass
class LLMResponse:
    """Raw text plus token counts from one model call."""

    text: str
    input_tokens: int
    output_tokens: int

    @property
    def usd(self) -> float:
        return (
            self.input_tokens / 1000.0 * PRICE_INPUT_PER_1K_USD
            + self.output_tokens / 1000.0 * PRICE_OUTPUT_PER_1K_USD
        )


class LLMClient(Protocol):
    """Anything that maps a prompt to an LLMResponse."""

    name: str

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse: ...


def _rough_token_count(text: str) -> int:
    """Cheap token estimate: 4 chars per token. Good enough for budget gating."""
    return max(1, len(text) // 4)


class GeminiClient:
    """Thin wrapper over google-generativeai with safe defaults."""

    name = "gemini-1.5-flash"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
    ) -> None:
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai is not installed. "
                "Run: pip install 'rapid-agent[gemini]'"
            ) from e

        genai.configure(api_key=api_key)
        self._genai = genai
        self.model_name = model
        self._model = genai.GenerativeModel(model)
        self.name = model

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        resp = self._model.generate_content(
            prompt,
            generation_config={"temperature": temperature},
        )
        text = _safe_text(resp)
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", _rough_token_count(prompt))
        out_tok = getattr(usage, "candidates_token_count", _rough_token_count(text))
        return LLMResponse(text=text, input_tokens=in_tok, output_tokens=out_tok)


def _safe_text(resp: Any) -> str:
    """Pull the text out of a Gemini response across SDK versions."""
    text = getattr(resp, "text", None)
    if text:
        return text
    cands = getattr(resp, "candidates", None) or []
    for c in cands:
        content = getattr(c, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if parts:
            joined = "".join(getattr(p, "text", "") for p in parts)
            if joined:
                return joined
    return ""


class StubClient:
    """Deterministic stub used when GEMINI_API_KEY is not set.

    Produces a valid Brief JSON given the standard prompt format. This keeps
    tests and the demo runnable without billing or network.
    """

    name = "stub-deterministic"

    def __init__(self) -> None:
        self.calls: List[str] = []

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        self.calls.append(prompt)

        # Parse the structured prompt to extract sources + topic.
        topic, sources = _parse_prompt(prompt)
        items = [
            {
                "url": s["url"],
                "title": s["title"] or s["url"],
                "summary": (
                    f"Stub summary of {s['title'] or s['url']}. "
                    "This text is generated locally with no model call."
                ),
                "key_points": [
                    f"First key point from {s['title'][:40] or 'source'}",
                    "Second key point covering the main argument.",
                    "Third key point about implications.",
                ],
            }
            for s in sources
        ]
        payload: Dict[str, Any] = {
            "topic": topic,
            "items": items,
            "overall_takeaway": (
                f"Across {len(items)} source(s) on '{topic}', "
                "the stub agent confirms the governance pipeline is wired correctly."
            ),
        }
        text = json.dumps(payload)
        return LLMResponse(
            text=text,
            input_tokens=_rough_token_count(prompt),
            output_tokens=_rough_token_count(text),
        )


def _parse_prompt(prompt: str) -> tuple:
    """Extract topic + sources from the agent prompt the stub will see."""
    topic = "unknown topic"
    sources: List[Dict[str, str]] = []

    for line in prompt.splitlines():
        if line.startswith("TOPIC:"):
            topic = line[len("TOPIC:") :].strip() or topic

    # Sources are emitted as `### SOURCE n` blocks. See agent.py.
    import re

    blocks = re.split(r"### SOURCE \d+", prompt)
    for block in blocks[1:]:
        url_m = re.search(r"URL:\s*(\S+)", block)
        title_m = re.search(r"TITLE:\s*(.+)", block)
        if url_m:
            sources.append(
                {
                    "url": url_m.group(1).strip(),
                    "title": (title_m.group(1).strip() if title_m else ""),
                }
            )
    return topic, sources


def get_default_client(*, api_key: Optional[str] = None) -> LLMClient:
    """Return a real GeminiClient if a key is available, else a StubClient."""
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
        "GOOGLE_API_KEY"
    )
    if key:
        try:
            return GeminiClient(api_key=key)
        except RuntimeError:
            # SDK not installed; fall through to stub.
            return StubClient()
    return StubClient()
