"""Vertex AI client using the google-genai unified SDK.

Drops in for GeminiClient so the four governance layers (BudgetCap,
EgressAllowlist, Trace, cast_json) sit unchanged above this client.

Uses google-genai's Vertex backend (GOOGLE_GENAI_USE_VERTEXAI=true) which
hits the v1beta1 endpoint, matching the pattern used by the sibling
gemini-* services already deployed in this project.
"""
from __future__ import annotations

from typing import Any

from rapid_agent.client import LLMResponse, _rough_token_count


class VertexClient:
    """Vertex AI generative-model client matching the GeminiClient interface."""

    def __init__(
        self,
        *,
        project: str,
        location: str = "us-central1",
        model: str = "gemini-2.5-flash",
    ) -> None:
        from google import genai

        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        self._model = model
        self.name = model

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        from google.genai import types

        resp: Any = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", None) or _rough_token_count(prompt)
        out_tok = getattr(usage, "candidates_token_count", None) or _rough_token_count(text)
        return LLMResponse(text=text, input_tokens=in_tok, output_tokens=out_tok)
