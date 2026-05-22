"""End-to-end agent tests using a fake HTTP session + stub LLM."""

from __future__ import annotations

import json

import pytest

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


# ---------------------------------------------------------------------------
# Happy path: stub LLM returns a valid Brief.
# ---------------------------------------------------------------------------


def test_agent_returns_typed_brief_with_stub_client():
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.05),
        allowlist=EgressAllowlist(allowed_hosts=["example.com"]),
        session=FakeSession(PAGES),
    )
    result = agent.run(
        topic="agents on gcp",
        urls=["https://example.com/a", "https://example.com/b"],
    )
    assert isinstance(result.brief, Brief)
    assert result.brief.topic == "agents on gcp"
    assert len(result.brief.items) == 2
    assert {it.url for it in result.brief.items} == {
        "https://example.com/a",
        "https://example.com/b",
    }
    # Trace recorded both fetches and one LLM call.
    names = [e.name for e in result.trace.events]
    assert any(n.startswith("fetch:") for n in names)
    assert "llm:complete" in names


def test_agent_skips_disallowed_url_and_continues():
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.05),
        allowlist=EgressAllowlist(allowed_hosts=["example.com"]),
        session=FakeSession(PAGES),
    )
    result = agent.run(
        topic="mixed",
        urls=["https://example.com/a", "https://evil.test/x"],
    )
    # Only the allowed source ends up in the brief.
    urls_in_brief = {it.url for it in result.brief.items}
    assert "https://example.com/a" in urls_in_brief
    assert "https://evil.test/x" not in urls_in_brief
    # The blocked event was traced with an error.
    blocked = [
        e for e in result.trace.events if e.meta.get("url") == "https://evil.test/x"
    ]
    assert blocked and "EgressDenied" in blocked[0].meta.get("error", "")


def test_agent_raises_when_all_sources_blocked():
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.05),
        allowlist=EgressAllowlist(allowed_hosts=["only-this.test"]),
        session=FakeSession(PAGES),
    )
    with pytest.raises(RuntimeError, match="no sources"):
        agent.run(topic="x", urls=["https://example.com/a"])


def test_agent_budget_cap_blocks_oversized_call():
    """A microscopic cap forces BudgetExceeded before the model is called."""
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.000000001),  # 1 nano-dollar
        allowlist=EgressAllowlist(allowed_hosts=["example.com"]),
        session=FakeSession(PAGES),
    )
    with pytest.raises(BudgetExceeded):
        agent.run(topic="x", urls=["https://example.com/a"])


def test_agent_trace_totals_are_consistent():
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.05),
        allowlist=EgressAllowlist(allowed_hosts=["example.com"]),
        session=FakeSession(PAGES),
    )
    result = agent.run(topic="x", urls=["https://example.com/a"])
    serialized = json.dumps(result.trace.to_dict())
    assert "events" in serialized
    # total_usd equals sum of per-event usd.
    summed = sum(e.usd for e in result.trace.events)
    assert result.trace.total_usd == pytest.approx(summed)


def test_run_brief_helper_rejects_unknown_host():
    """run_brief should deny hosts not on the default allowlist."""
    # Using a host not on _DEFAULT_ALLOWED_HOSTS and no extra_hosts. Every
    # URL is blocked, so the agent raises before any network call happens.
    with pytest.raises(RuntimeError, match="no sources"):
        run_brief(
            topic="t",
            urls=["https://not-on-allowlist.invalid/x"],
            max_usd=0.05,
            client=StubClient(),
        )
