"""Four small governance primitives used by the rapid agent.

Each one mirrors a published sibling library so the production swap is
documented:

  cast_json   <- agentcast      (validate-and-retry for LLM JSON)
  BudgetCap   <- agentleash     (USD/call budget cap)
  EgressAllowlist <- agentguard (domain allowlist for tool egress)
  Trace       <- agenttrace     (cost + latency tracking)

We inline minimal versions so the demo runs with zero PyPI pulls. In
production, install the sibling libs and swap the imports.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Type
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# 1. Structured output enforcement (mirrors agentcast)
# ---------------------------------------------------------------------------


class OutputCastError(ValueError):
    """Raised when the model output cannot be cast to the requested schema."""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Strip ```json ... ``` fences if the model wrapped its output."""
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def cast_json(
    text: str,
    schema: Type[BaseModel],
    *,
    retry: Optional[Callable[[str], str]] = None,
    max_retries: int = 1,
) -> BaseModel:
    """Parse `text` into a pydantic model of type `schema`.

    If the text is not valid JSON or fails schema validation, optionally call
    `retry(repair_prompt)` up to `max_retries` times. The repair prompt
    contains the validation error so a model can self-correct.

    Raises OutputCastError if no attempt succeeds.
    """
    last_err: Optional[str] = None
    attempt_text = text

    for _ in range(max_retries + 1):
        cleaned = _strip_fences(attempt_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_err = f"invalid JSON: {e.msg}"
            if retry is None:
                break
            attempt_text = retry(_repair_prompt(cleaned, last_err, schema))
            continue

        try:
            return schema.model_validate(data)
        except ValidationError as e:
            last_err = f"schema validation failed: {e.errors()[:3]}"
            if retry is None:
                break
            attempt_text = retry(_repair_prompt(cleaned, last_err, schema))

    raise OutputCastError(last_err or "unknown cast failure")


def _repair_prompt(raw: str, err: str, schema: Type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        "Your previous response could not be parsed.\n"
        f"Error: {err}\n\n"
        "Required JSON schema:\n"
        f"{schema_json}\n\n"
        "Previous response:\n"
        f"{raw}\n\n"
        "Respond with corrected JSON only, no commentary, no fences."
    )


# ---------------------------------------------------------------------------
# 2. Budget cap (mirrors agentleash)
# ---------------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    """Raised when an LLM call would push spend past the configured cap."""


@dataclass
class BudgetCap:
    """Simple USD spend cap with reserve/commit semantics."""

    max_usd: float
    spent_usd: float = 0.0

    def reserve(self, projected_usd: float) -> None:
        if self.spent_usd + projected_usd > self.max_usd:
            raise BudgetExceeded(
                f"projected ${projected_usd:.4f} would exceed cap "
                f"${self.max_usd:.2f} (already spent ${self.spent_usd:.4f})"
            )

    def commit(self, actual_usd: float) -> None:
        self.spent_usd += actual_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.spent_usd)


# ---------------------------------------------------------------------------
# 3. Egress allowlist (mirrors agentguard)
# ---------------------------------------------------------------------------


class EgressDenied(PermissionError):
    """Raised when a tool tries to fetch a URL outside the allowlist."""


@dataclass
class EgressAllowlist:
    """Domain allowlist. Matches exact host or any subdomain of host."""

    allowed_hosts: List[str] = field(default_factory=list)

    def check(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        host = host.lower()
        for allowed in self.allowed_hosts:
            a = allowed.lower().lstrip(".")
            if host == a or host.endswith("." + a):
                return
        raise EgressDenied(f"host '{host}' not in allowlist {self.allowed_hosts}")

    def with_extra(self, hosts: Iterable[str]) -> "EgressAllowlist":
        return EgressAllowlist(self.allowed_hosts + list(hosts))


# ---------------------------------------------------------------------------
# 4. Per-call trace (mirrors agenttrace)
# ---------------------------------------------------------------------------


@dataclass
class TraceEvent:
    name: str
    started_at: float
    duration_ms: float
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at,
            "duration_ms": round(self.duration_ms, 2),
            "usd": round(self.usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "meta": self.meta,
        }


class Trace:
    """Collect events from one agent run."""

    def __init__(self) -> None:
        self.events: List[TraceEvent] = []
        self._open: Dict[str, float] = {}

    def start(self, name: str) -> None:
        self._open[name] = time.perf_counter()

    def finish(
        self,
        name: str,
        *,
        usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        started = self._open.pop(name, time.perf_counter())
        ev = TraceEvent(
            name=name,
            started_at=started,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            usd=usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            meta=meta or {},
        )
        self.events.append(ev)
        return ev

    @property
    def total_usd(self) -> float:
        return sum(e.usd for e in self.events)

    @property
    def total_ms(self) -> float:
        return sum(e.duration_ms for e in self.events)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_usd": round(self.total_usd, 6),
            "total_ms": round(self.total_ms, 2),
            "events": [e.to_dict() for e in self.events],
        }
