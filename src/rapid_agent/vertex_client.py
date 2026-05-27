"""Vertex AI client. Drop-in replacement for GeminiClient for production
deploys on Cloud Run. No agent changes required — the governance layers
(BudgetCap, EgressAllowlist, Trace, cast_json) sit above this client and
stay unchanged."""
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
        model: str = "gemini-1.5-flash-002",
    ) -> None:
        # Import inside __init__ so test environments without the SDK can still
        # import this module for type checking.
        from vertexai import init as vertex_init
        from vertexai.generative_models import GenerativeModel

        vertex_init(project=project, location=location)
        self._model = GenerativeModel(model)
        self.name = model

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        resp: Any = self._model.generate_content(
            prompt,
            generation_config={"temperature": temperature},
        )
        text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", _rough_token_count(prompt))
        out_tok = getattr(usage, "candidates_token_count", _rough_token_count(text))
        return LLMResponse(text=text, input_tokens=in_tok, output_tokens=out_tok)
