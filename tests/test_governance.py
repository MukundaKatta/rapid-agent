"""Tests for the four governance primitives.

Standard-library ``unittest`` only, so the suite runs with::

    python -m unittest discover -s tests

The budget / egress / trace primitives are pure stdlib and are always
exercised. The ``cast_json`` tests need ``pydantic`` and are skipped (not
failed) when it is not installed.
"""

from __future__ import annotations

import json
import unittest
from typing import List

from rapid_agent.governance import (
    BudgetCap,
    BudgetExceeded,
    EgressAllowlist,
    EgressDenied,
    OutputCastError,
    Trace,
    cast_json,
)

try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - depends on environment
    BaseModel = object  # type: ignore[assignment,misc]
    HAS_PYDANTIC = False


# ---------------------------------------------------------------------------
# cast_json (requires pydantic)
# ---------------------------------------------------------------------------


if HAS_PYDANTIC:

    class _Tiny(BaseModel):
        name: str
        count: int


@unittest.skipUnless(HAS_PYDANTIC, "pydantic not installed")
class CastJsonTests(unittest.TestCase):
    def test_accepts_clean_json(self):
        out = cast_json('{"name": "alpha", "count": 3}', _Tiny)
        self.assertIsInstance(out, _Tiny)
        self.assertEqual(out.name, "alpha")
        self.assertEqual(out.count, 3)

    def test_strips_fences(self):
        text = '```json\n{"name": "beta", "count": 5}\n```'
        out = cast_json(text, _Tiny)
        self.assertEqual(out.count, 5)

    def test_retries_on_invalid_and_recovers(self):
        calls: List[str] = []

        def retry(repair_prompt: str) -> str:
            calls.append(repair_prompt)
            return '{"name": "gamma", "count": 7}'

        out = cast_json("not json at all", _Tiny, retry=retry, max_retries=1)
        self.assertEqual(out.count, 7)
        self.assertEqual(len(calls), 1)
        self.assertIn("schema", calls[0].lower())

    def test_retry_runs_on_schema_validation_failure(self):
        """Valid JSON that fails schema validation should trigger a repair."""
        calls: List[str] = []

        def retry(repair_prompt: str) -> str:
            calls.append(repair_prompt)
            return '{"name": "delta", "count": 9}'

        # Missing the required "count" field -> schema validation error.
        out = cast_json('{"name": "delta"}', _Tiny, retry=retry, max_retries=1)
        self.assertEqual(out.count, 9)
        self.assertEqual(len(calls), 1)

    def test_raises_when_retry_exhausted(self):
        with self.assertRaises(OutputCastError):
            cast_json("not json", _Tiny)


@unittest.skipIf(HAS_PYDANTIC, "only meaningful when pydantic is absent")
class CastJsonWithoutPydanticTests(unittest.TestCase):
    def test_clear_error_when_pydantic_missing(self):
        with self.assertRaises(OutputCastError) as ctx:
            cast_json("{}", object)
        self.assertIn("pydantic", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# BudgetCap
# ---------------------------------------------------------------------------


class BudgetCapTests(unittest.TestCase):
    def test_reserve_under_cap_passes(self):
        cap = BudgetCap(max_usd=0.05)
        cap.reserve(0.01)  # no commit yet
        self.assertAlmostEqual(cap.remaining_usd, 0.05)
        cap.commit(0.01)
        self.assertAlmostEqual(cap.remaining_usd, 0.04)

    def test_reserve_over_cap_raises(self):
        cap = BudgetCap(max_usd=0.001)
        with self.assertRaises(BudgetExceeded):
            cap.reserve(0.01)

    def test_running_total_enforced_across_calls(self):
        cap = BudgetCap(max_usd=0.03)
        cap.reserve(0.02)
        cap.commit(0.02)
        with self.assertRaises(BudgetExceeded):
            cap.reserve(0.02)

    def test_reserve_exactly_at_cap_is_allowed(self):
        cap = BudgetCap(max_usd=0.02)
        cap.reserve(0.02)  # equal to cap -> not exceeded
        cap.commit(0.02)
        self.assertEqual(cap.remaining_usd, 0.0)

    def test_remaining_never_negative(self):
        cap = BudgetCap(max_usd=0.01)
        cap.commit(0.05)  # over-committed
        self.assertEqual(cap.remaining_usd, 0.0)


# ---------------------------------------------------------------------------
# EgressAllowlist
# ---------------------------------------------------------------------------


class EgressAllowlistTests(unittest.TestCase):
    def test_accepts_exact_host(self):
        allow = EgressAllowlist(allowed_hosts=["example.com"])
        allow.check("https://example.com/path")  # should not raise

    def test_accepts_subdomain(self):
        allow = EgressAllowlist(allowed_hosts=["wikipedia.org"])
        allow.check("https://en.wikipedia.org/wiki/Agent")

    def test_denies_unrelated_host(self):
        allow = EgressAllowlist(allowed_hosts=["example.com"])
        with self.assertRaises(EgressDenied):
            allow.check("https://evil.example.io/")

    def test_lookalike_suffix_is_denied(self):
        """notexample.com must not match example.com."""
        allow = EgressAllowlist(allowed_hosts=["example.com"])
        with self.assertRaises(EgressDenied):
            allow.check("https://notexample.com/")

    def test_host_match_is_case_insensitive(self):
        allow = EgressAllowlist(allowed_hosts=["Example.COM"])
        allow.check("https://EXAMPLE.com/x")

    def test_leading_dot_in_allowed_host_is_tolerated(self):
        allow = EgressAllowlist(allowed_hosts=[".example.com"])
        allow.check("https://a.example.com/x")

    def test_with_extra_returns_new_independent_allowlist(self):
        base = EgressAllowlist(allowed_hosts=["example.com"])
        extended = base.with_extra(["python.org"])
        extended.check("https://docs.python.org/3/")
        # base is unchanged
        with self.assertRaises(EgressDenied):
            base.check("https://docs.python.org/3/")


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class TraceTests(unittest.TestCase):
    def test_records_one_event(self):
        t = Trace()
        t.start("step")
        t.finish("step", usd=0.001, input_tokens=10, output_tokens=5)
        self.assertEqual(len(t.events), 1)
        ev = t.events[0]
        self.assertEqual(ev.name, "step")
        self.assertEqual(ev.usd, 0.001)
        self.assertGreaterEqual(ev.duration_ms, 0)
        self.assertEqual(ev.input_tokens, 10)
        self.assertEqual(ev.output_tokens, 5)

    def test_totals_and_serialize(self):
        t = Trace()
        t.start("a")
        t.finish("a", usd=0.002)
        t.start("b")
        t.finish("b", usd=0.003)
        self.assertAlmostEqual(t.total_usd, 0.005)
        self.assertGreaterEqual(t.total_ms, 0)
        blob = json.dumps(t.to_dict())
        self.assertIn("events", blob)
        self.assertIn("total_usd", blob)

    def test_finish_without_start_does_not_crash(self):
        """finish() on an unstarted event still records a (near-zero) event."""
        t = Trace()
        ev = t.finish("orphan", usd=0.0)
        self.assertEqual(ev.name, "orphan")
        self.assertGreaterEqual(ev.duration_ms, 0)

    def test_event_to_dict_round_trips_through_json(self):
        t = Trace()
        t.start("x")
        ev = t.finish("x", usd=0.001, input_tokens=2, output_tokens=4, meta={"k": "v"})
        d = ev.to_dict()
        self.assertEqual(d["meta"], {"k": "v"})
        # serializable
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()
