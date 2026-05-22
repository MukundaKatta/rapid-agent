"""60-90 second demo: with governance vs without.

Run:
    python examples/run.py

Set GEMINI_API_KEY in your environment to hit the real free-tier model.
With no key set, a deterministic stub is used so the demo still produces
the same shape of output. The governance layers behave identically either
way.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path

# Make `python examples/run.py` work without `pip install -e .`.
HERE = Path(__file__).resolve()
SRC = HERE.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rapid_agent import (  # noqa: E402
    BudgetCap,
    BudgetExceeded,
    EgressAllowlist,
    EgressDenied,
    RapidAgent,
    StubClient,
    get_default_client,
)


# ---------------------------------------------------------------------------
# Fake HTTP session so the demo is deterministic and offline-safe.
# Real sites with stable content (wikipedia, etc.) sometimes change. The
# stub here keeps the demo reproducible. Swap in `requests.Session()` to
# hit the real allowlist.
# ---------------------------------------------------------------------------


class _DemoResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class DemoSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout=None, headers=None):
        if url in self.pages:
            return _DemoResponse(self.pages[url])
        raise RuntimeError(f"demo session has no page for {url}")


DEMO_PAGES = {
    "https://example.com/agents-overview": (
        "<html><head><title>Agents on Google Cloud</title></head>"
        "<body><p>Agents combine an LLM with tools. Google Cloud offers "
        "Vertex AI as the managed surface for production deploys, with "
        "Cloud Run as a common host for the agent HTTP front door.</p>"
        "</body></html>"
    ),
    "https://example.com/vertex-ai-gemini": (
        "<html><head><title>Vertex AI and Gemini</title></head>"
        "<body><p>Vertex AI exposes Gemini 1.5 Flash and Pro through a "
        "stable, region-aware endpoint with IAM, quotas, and audit logs. "
        "This is the standard path for production agent workloads.</p>"
        "</body></html>"
    ),
    "https://example.com/cloud-run-deploy": (
        "<html><head><title>Cloud Run for agent backends</title></head>"
        "<body><p>Cloud Run autoscales container workloads to zero. It is "
        "well suited to agent HTTP endpoints because it bills only when "
        "requests are active and supports per-revision concurrency.</p>"
        "</body></html>"
    ),
}


URLS = list(DEMO_PAGES.keys())
TOPIC = "Building agents on Google Cloud"


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------


def banner(label: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{label}\n{bar}")


def hr(label: str) -> None:
    print(f"\n--- {label} ---")


def wrap(text: str, width: int = 70) -> str:
    return textwrap.fill(text, width=width)


# ---------------------------------------------------------------------------
# Scene 1: WITHOUT governance
# ---------------------------------------------------------------------------


def scene_without_governance(client) -> None:
    banner("SCENE 1  -  Without governance")

    # 1a. Hostile URL is fetched anyway (no allowlist).
    hr("1a. No allowlist. A typo URL gets requested.")
    bad_url = "https://internal-corp-admin.invalid/secret"
    print(f"agent tries: {bad_url}")
    print("result:      request would be sent, no host check")

    # 1b. No budget cap. The cost keeps climbing across calls.
    hr("1b. No budget cap. Cost accumulates without bound.")
    fake_spend = 0.0
    for i in range(3):
        fake_spend += 0.012
        print(f"call {i + 1}: spent so far ${fake_spend:.4f}")
    print("nothing stops the next call from running")

    # 1c. Output is just a blob of text. Caller has to grep it.
    hr("1c. Free-text output. Downstream has to parse by hand.")
    prompt = f"TOPIC: {TOPIC}\nWrite a brief about it."
    t0 = time.perf_counter()
    raw = client.complete(prompt).text
    dt = (time.perf_counter() - t0) * 1000
    print(f"model returned {len(raw)} chars in {dt:.0f}ms")
    print(wrap(raw[:300] + ("..." if len(raw) > 300 else "")))

    # 1d. No trace.
    hr("1d. No trace. No record of what happened, what it cost.")
    print("you only know it ran if it did not crash")


# ---------------------------------------------------------------------------
# Scene 2: WITH governance
# ---------------------------------------------------------------------------


def scene_with_governance(client) -> None:
    banner("SCENE 2  -  With governance")

    allow = EgressAllowlist(allowed_hosts=["example.com"])
    budget = BudgetCap(max_usd=0.05)
    agent = RapidAgent(
        client=client,
        budget=budget,
        allowlist=allow,
        session=DemoSession(DEMO_PAGES),
    )

    # 2a. Allowlist blocks the bad URL before fetch.
    hr("2a. Egress allowlist blocks unknown hosts.")
    try:
        allow.check("https://internal-corp-admin.invalid/secret")
    except EgressDenied as e:
        print(f"blocked: {e}")

    # 2b. Budget cap blocks an oversized call before it happens.
    hr("2b. Budget cap reserves before each call.")
    try:
        tiny = BudgetCap(max_usd=0.000001)
        tiny.reserve(0.01)
    except BudgetExceeded as e:
        print(f"refused: {e}")

    # 2c. Full agent run with all four layers active.
    hr("2c. Real run. Fetch + LLM + cast + trace.")
    result = agent.run(topic=TOPIC, urls=URLS)

    # 2d. Typed output.
    hr("2d. Typed Brief. Downstream code can index .items[].url etc.")
    brief = result.brief
    print(f"topic:   {brief.topic}")
    print(f"items:   {len(brief.items)}")
    for it in brief.items:
        print(f"  - {it.title} ({it.url})")
        print(wrap(it.summary, width=68).replace("\n", "\n    "))
    print(f"\ntakeaway: {wrap(brief.overall_takeaway, 68)}")

    # 2e. Trace summary.
    hr("2e. Per-call trace.")
    t = result.trace
    print(f"total cost:   ${t.total_usd:.6f}")
    print(f"total time:   {t.total_ms:.0f} ms")
    print(f"events:       {len(t.events)}")
    print(f"budget left:  ${budget.remaining_usd:.6f}")

    # 2f. Write the trace to disk for later inspection.
    out = Path("rapid_agent_trace.json")
    out.write_text(json.dumps(t.to_dict(), indent=2))
    print(f"\nwrote trace: {out.resolve()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    using_stub = not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    client = get_default_client()
    backend = "STUB (deterministic, no key set)" if using_stub else f"Gemini ({client.name})"
    banner(f"rapid-agent demo  -  backend: {backend}")
    print(
        "Two scenes follow. Same task. First without governance, then with.\n"
        "Watch for the four labeled layers in scene 2."
    )

    scene_without_governance(StubClient())  # always stub here so output is short
    scene_with_governance(client)

    banner("done")
    print(
        "To run against the real Gemini API:\n"
        "  pip install 'rapid-agent[gemini]'\n"
        "  export GEMINI_API_KEY=...\n"
        "  python examples/run.py\n"
        "\n"
        "For production on Vertex AI, see DEPLOY.md."
    )


if __name__ == "__main__":
    main()
