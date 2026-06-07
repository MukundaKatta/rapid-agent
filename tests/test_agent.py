"""End-to-end agent tests using a fake HTTP session + stub LLM.

Standard-library ``unittest`` only. The agent imports ``requests`` and
``pydantic``; these tests are skipped (not failed) when those are absent.
"""

from __future__ import annotations

import json
import unittest

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_PYDANTIC = False

try:
    import requests  # noqa: F401

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_REQUESTS = False

HAS_DEPS = HAS_PYDANTIC and HAS_REQUESTS

if HAS_DEPS:
    from rapid_agent.agent import RapidAgent, run_brief
    from rapid_agent.brief import Brief
    from rapid_agent.client import StubClient
    from rapid_agent.governance import BudgetCap, BudgetExceeded, EgressAllowlist


# ---------------------------------------------------------------------------
# Fake HTTP session so tests never touch the network.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    """Returns a canned HTML page per URL."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, timeout=None, headers=None):
        self.calls.append(url)
        if url in self.pages:
            return _FakeResponse(self.pages[url])
        return _FakeResponse("<html><title>missing</title></html>", status=404)


PAGES = {
    "https://example.com/a": (
        "<html><head><title>Page A</title></head>"
        "<body><p>Agents are programs that act in an environment.</p></body></html>"
    ),
    "https://example.com/b": (
        "<html><head><title>Page B</title></head>"
        "<body><p>Vertex AI hosts Gemini models for production use.</p></body></html>"
    ),
}


@unittest.skipUnless(HAS_DEPS, "requires pydantic and requests")
class AgentTests(unittest.TestCase):
    def _agent(self, allowed=("example.com",), max_usd=0.05):
        return RapidAgent(
            client=StubClient(),
            budget=BudgetCap(max_usd=max_usd),
            allowlist=EgressAllowlist(allowed_hosts=list(allowed)),
            session=FakeSession(PAGES),
        )

    def test_returns_typed_brief_with_stub_client(self):
        result = self._agent().run(
            topic="agents on gcp",
            urls=["https://example.com/a", "https://example.com/b"],
        )
        self.assertIsInstance(result.brief, Brief)
        self.assertEqual(result.brief.topic, "agents on gcp")
        self.assertEqual(len(result.brief.items), 2)
        self.assertEqual(
            {it.url for it in result.brief.items},
            {"https://example.com/a", "https://example.com/b"},
        )
        names = [e.name for e in result.trace.events]
        self.assertTrue(any(n.startswith("fetch:") for n in names))
        self.assertIn("llm:complete", names)

    def test_skips_disallowed_url_and_continues(self):
        result = self._agent().run(
            topic="mixed",
            urls=["https://example.com/a", "https://evil.test/x"],
        )
        urls_in_brief = {it.url for it in result.brief.items}
        self.assertIn("https://example.com/a", urls_in_brief)
        self.assertNotIn("https://evil.test/x", urls_in_brief)
        blocked = [
            e
            for e in result.trace.events
            if e.meta.get("url") == "https://evil.test/x"
        ]
        self.assertTrue(blocked)
        self.assertIn("EgressDenied", blocked[0].meta.get("error", ""))

    def test_raises_when_all_sources_blocked(self):
        agent = self._agent(allowed=("only-this.test",))
        with self.assertRaisesRegex(RuntimeError, "no sources"):
            agent.run(topic="x", urls=["https://example.com/a"])

    def test_budget_cap_blocks_oversized_call(self):
        agent = self._agent(max_usd=0.000000001)  # 1 nano-dollar
        with self.assertRaises(BudgetExceeded):
            agent.run(topic="x", urls=["https://example.com/a"])

    def test_trace_totals_are_consistent(self):
        result = self._agent().run(topic="x", urls=["https://example.com/a"])
        serialized = json.dumps(result.trace.to_dict())
        self.assertIn("events", serialized)
        summed = sum(e.usd for e in result.trace.events)
        self.assertAlmostEqual(result.trace.total_usd, summed)


@unittest.skipUnless(HAS_DEPS, "requires pydantic and requests")
class RunBriefHelperTests(unittest.TestCase):
    def test_rejects_unknown_host(self):
        # Host not on _DEFAULT_ALLOWED_HOSTS and no extra_hosts -> every URL
        # is blocked, so the agent raises before any network call.
        with self.assertRaisesRegex(RuntimeError, "no sources"):
            run_brief(
                topic="t",
                urls=["https://not-on-allowlist.invalid/x"],
                max_usd=0.05,
                client=StubClient(),
            )


if __name__ == "__main__":
    unittest.main()
