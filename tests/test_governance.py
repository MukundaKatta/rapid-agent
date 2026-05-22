"""Tests for the four governance primitives."""

from __future__ import annotations

import json
from typing import List

import pytest
from pydantic import BaseModel

from rapid_agent.governance import (
    BudgetCap,
    BudgetExceeded,
    EgressAllowlist,
    EgressDenied,
    OutputCastError,
    Trace,
    cast_json,
)


# ---------------------------------------------------------------------------
# cast_json
# ---------------------------------------------------------------------------


class _Tiny(BaseModel):
    name: str
    count: int


def test_cast_json_accepts_clean_json():
    out = cast_json('{"name": "alpha", "count": 3}', _Tiny)
    assert isinstance(out, _Tiny)
    assert out.name == "alpha"
    assert out.count == 3


def test_cast_json_strips_fences():
    text = "```json\n{\"name\": \"beta\", \"count\": 5}\n```"
    out = cast_json(text, _Tiny)
    assert out.count == 5


def test_cast_json_retries_on_invalid_and_recovers():
    calls: List[str] = []

    def retry(repair_prompt: str) -> str:
        calls.append(repair_prompt)
        return '{"name": "gamma", "count": 7}'

    out = cast_json("not json at all", _Tiny, retry=retry, max_retries=1)
    assert out.count == 7
    assert len(calls) == 1
    assert "schema" in calls[0].lower()


def test_cast_json_raises_when_retry_exhausted():
    with pytest.raises(OutputCastError):
        cast_json("not json", _Tiny)


# ---------------------------------------------------------------------------
# BudgetCap
# ---------------------------------------------------------------------------


def test_budget_reserve_under_cap_passes():
    cap = BudgetCap(max_usd=0.05)
    cap.reserve(0.01)  # no commit yet
    assert cap.remaining_usd == pytest.approx(0.05)
    cap.commit(0.01)
    assert cap.remaining_usd == pytest.approx(0.04)


def test_budget_reserve_over_cap_raises():
    cap = BudgetCap(max_usd=0.001)
    with pytest.raises(BudgetExceeded):
        cap.reserve(0.01)


def test_budget_running_total_enforced_across_calls():
    cap = BudgetCap(max_usd=0.03)
    cap.reserve(0.02)
    cap.commit(0.02)
    with pytest.raises(BudgetExceeded):
        cap.reserve(0.02)


# ---------------------------------------------------------------------------
# EgressAllowlist
# ---------------------------------------------------------------------------


def test_allowlist_accepts_exact_host():
    allow = EgressAllowlist(allowed_hosts=["example.com"])
    allow.check("https://example.com/path")


def test_allowlist_accepts_subdomain():
    allow = EgressAllowlist(allowed_hosts=["wikipedia.org"])
    allow.check("https://en.wikipedia.org/wiki/Agent")


def test_allowlist_denies_unrelated_host():
    allow = EgressAllowlist(allowed_hosts=["example.com"])
    with pytest.raises(EgressDenied):
        allow.check("https://evil.example.io/")


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


def test_trace_records_one_event():
    t = Trace()
    t.start("step")
    t.finish("step", usd=0.001, input_tokens=10, output_tokens=5)
    assert len(t.events) == 1
    ev = t.events[0]
    assert ev.name == "step"
    assert ev.usd == 0.001
    assert ev.duration_ms >= 0


def test_trace_totals_and_serialize():
    t = Trace()
    t.start("a")
    t.finish("a", usd=0.002)
    t.start("b")
    t.finish("b", usd=0.003)
    assert t.total_usd == pytest.approx(0.005)
    blob = json.dumps(t.to_dict())
    assert "events" in blob and "total_usd" in blob
