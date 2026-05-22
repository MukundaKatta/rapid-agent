"""RapidAgent: orchestrates fetch + LLM under four governance layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import requests

from rapid_agent.brief import Brief, FetchedSource, fetch_source
from rapid_agent.client import LLMClient, LLMResponse, get_default_client
from rapid_agent.governance import (
    BudgetCap,
    EgressAllowlist,
    OutputCastError,
    Trace,
    cast_json,
)


_DEFAULT_ALLOWED_HOSTS = [
    # Stable, well-known hosts we trust for the demo.
    "example.com",
    "wikipedia.org",
    "developers.google.com",
    "cloud.google.com",
    "ai.google.dev",
    "docs.python.org",
]


@dataclass
class AgentResult:
    """What one full agent run returns."""

    brief: Brief
    trace: Trace
    fetched: List[FetchedSource] = field(default_factory=list)


@dataclass
class RapidAgent:
    """A research-brief agent with four governance layers."""

    client: LLMClient
    budget: BudgetCap
    allowlist: EgressAllowlist
    session: Optional[requests.Session] = None

    def run(self, topic: str, urls: List[str]) -> AgentResult:
        """Fetch each URL, call the model, return a typed Brief."""
        trace = Trace()
        fetched: List[FetchedSource] = []

        # Phase 1: fetch each source under the allowlist.
        for url in urls:
            label = f"fetch:{_short(url)}"
            trace.start(label)
            try:
                src = fetch_source(
                    url, self.allowlist, session=self.session, timeout=10.0
                )
                fetched.append(src)
                trace.finish(label, meta={"url": url, "chars": len(src.text)})
            except Exception as e:  # noqa: BLE001  - record and skip
                trace.finish(
                    label,
                    meta={"url": url, "error": f"{type(e).__name__}: {e}"},
                )

        if not fetched:
            raise RuntimeError(
                "no sources could be fetched (all denied or failed)"
            )

        # Phase 2: build a single structured prompt.
        prompt = _build_prompt(topic, fetched)

        # Phase 3: budget reserve based on projected cost, then call model.
        projected_in = max(1, len(prompt) // 4)
        # Cheap upper bound: assume model returns ~25% of input as output.
        projected_out = max(1, projected_in // 4)
        projected_usd = _projected_cost(projected_in, projected_out)
        self.budget.reserve(projected_usd)

        trace.start("llm:complete")
        resp: LLMResponse = self.client.complete(prompt)
        trace.finish(
            "llm:complete",
            usd=resp.usd,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            meta={"model": getattr(self.client, "name", "unknown")},
        )
        self.budget.commit(resp.usd)

        # Phase 4: cast model output to Brief, with one repair retry.
        def _repair(repair_prompt: str) -> str:
            trace.start("llm:repair")
            self.budget.reserve(projected_usd)
            r = self.client.complete(repair_prompt)
            trace.finish(
                "llm:repair",
                usd=r.usd,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
            )
            self.budget.commit(r.usd)
            return r.text

        try:
            brief = cast_json(resp.text, Brief, retry=_repair, max_retries=1)
        except OutputCastError as e:
            raise RuntimeError(f"model output could not be cast to Brief: {e}") from e

        if not isinstance(brief, Brief):  # pragma: no cover - belt and suspenders
            raise RuntimeError("cast_json returned wrong type")

        return AgentResult(brief=brief, trace=trace, fetched=fetched)


def _short(url: str) -> str:
    return url.replace("https://", "").replace("http://", "")[:40]


def _projected_cost(in_tok: int, out_tok: int) -> float:
    from rapid_agent.client import PRICE_INPUT_PER_1K_USD, PRICE_OUTPUT_PER_1K_USD

    return (
        in_tok / 1000.0 * PRICE_INPUT_PER_1K_USD
        + out_tok / 1000.0 * PRICE_OUTPUT_PER_1K_USD
    )


def _build_prompt(topic: str, sources: List[FetchedSource]) -> str:
    parts = [
        "You are a careful research assistant.",
        "Read every source and write a brief in JSON.",
        "",
        f"TOPIC: {topic}",
        "",
        "REQUIRED JSON SHAPE:",
        "{",
        '  "topic": str,',
        '  "items": [ { "url": str, "title": str, "summary": str, '
        '"key_points": [str, ...] } ],',
        '  "overall_takeaway": str',
        "}",
        "",
        "Respond with JSON only. No prose. No fences.",
        "",
    ]
    for i, s in enumerate(sources, start=1):
        parts.extend(
            [
                f"### SOURCE {i}",
                f"URL: {s.url}",
                f"TITLE: {s.title}",
                "TEXT:",
                s.text,
                "",
            ]
        )
    return "\n".join(parts)


# Convenience entry point used by examples/run.py
def run_brief(
    topic: str,
    urls: List[str],
    *,
    max_usd: float = 0.05,
    extra_hosts: Optional[List[str]] = None,
    client: Optional[LLMClient] = None,
) -> AgentResult:
    """Run the agent end-to-end with sensible defaults."""
    allow = EgressAllowlist(allowed_hosts=list(_DEFAULT_ALLOWED_HOSTS))
    if extra_hosts:
        allow = allow.with_extra(extra_hosts)
    agent = RapidAgent(
        client=client or get_default_client(),
        budget=BudgetCap(max_usd=max_usd),
        allowlist=allow,
    )
    return agent.run(topic=topic, urls=urls)
