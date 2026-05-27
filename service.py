"""FastAPI service wrapper for rapid-agent — hosted entrypoint for Cloud Run.

Exposes:
- POST /brief       run the governed agent over a topic + URL list
- GET  /            human-readable landing page with usage + live demo
- GET  /healthz     liveness/readiness probe
- GET  /demo        runs a no-LLM stub for hackathon judges to click

Environment:
    GOOGLE_CLOUD_PROJECT   required, the project for Vertex AI init
    VERTEX_LOCATION        optional, defaults to "us-central1"
    ALLOWED_HOSTS          comma-separated egress allowlist, defaults
                           to a safe demo set
    MAX_USD                per-run budget cap, defaults to "0.10"
    MODEL                  Vertex model name, defaults "gemini-2.5-flash"
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rapid_agent import RapidAgent, BudgetCap, EgressAllowlist
from rapid_agent.client import StubClient


# In-memory pages so /demo runs offline — same shape the examples/run.py
# demo uses. Lets hackathon judges click /demo and see all four governance
# layers in action without configuring URLs that point at the real internet.
class _DemoResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:  # noqa: D401
        pass


class _DemoSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages

    def get(self, url: str, timeout: int | None = None, headers: dict | None = None):
        if url in self._pages:
            return _DemoResponse(self._pages[url])
        raise RuntimeError(f"demo session has no page for {url}")


_DEMO_PAGES = {
    "https://example.com/agents-overview": (
        "<html><head><title>Agents on Google Cloud</title></head>"
        "<body><p>Agents combine an LLM with tools. Vertex AI is the managed "
        "surface for production deploys; Cloud Run is a common host for the "
        "HTTP front door.</p></body></html>"
    ),
    "https://example.com/vertex-ai-gemini": (
        "<html><head><title>Vertex AI and Gemini</title></head>"
        "<body><p>Vertex AI exposes Gemini through a stable region-aware "
        "endpoint with IAM, quotas, and audit logs. The standard path for "
        "production agent workloads.</p></body></html>"
    ),
    "https://example.com/cloud-run-deploy": (
        "<html><head><title>Cloud Run for agent backends</title></head>"
        "<body><p>Cloud Run autoscales container workloads to zero and bills "
        "only when requests are active. Well suited to agent HTTP "
        "endpoints.</p></body></html>"
    ),
}

_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
_MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
_DEFAULT_HOSTS = "cloud.google.com,ai.google.dev,example.com"
_ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", _DEFAULT_HOSTS).split(",")
    if h.strip()
]
_MAX_USD = float(os.environ.get("MAX_USD", "0.10"))


def _make_client() -> Any:
    """Pick Vertex when a project is configured, otherwise the deterministic
    stub so the service still boots and serves /demo without billing."""
    if not _PROJECT:
        return StubClient()
    from rapid_agent.vertex_client import VertexClient
    return VertexClient(project=_PROJECT, location=_LOCATION, model=_MODEL)


_CLIENT = _make_client()


app = FastAPI(
    title="rapid-agent",
    description=(
        "Gemini-powered research-brief agent with four governance layers: "
        "typed output, budget cap, egress allowlist, per-call trace. "
        "Built for the Google Cloud Rapid Agent Hackathon."
    ),
    version="0.1.0",
)


class BriefRequest(BaseModel):
    topic: str
    urls: list[str]
    max_usd: float | None = None
    allowed_hosts: list[str] | None = None


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "project": _PROJECT or None,
        "location": _LOCATION,
        "model": _MODEL,
        "client": _CLIENT.__class__.__name__,
        "default_allowed_hosts": _ALLOWED_HOSTS,
        "default_max_usd": _MAX_USD,
    }


@app.post("/brief")
def brief(req: BriefRequest) -> dict[str, Any]:
    """Run the governed agent. Body: {topic, urls, max_usd?, allowed_hosts?}.
    Returns {brief, trace}."""
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="topic must be non-empty")
    if not req.urls:
        raise HTTPException(status_code=400, detail="urls must be non-empty")

    hosts = req.allowed_hosts or _ALLOWED_HOSTS
    max_usd = req.max_usd if req.max_usd is not None else _MAX_USD

    agent = RapidAgent(
        client=_CLIENT,
        budget=BudgetCap(max_usd=max_usd),
        allowlist=EgressAllowlist(allowed_hosts=hosts),
    )
    result = agent.run(topic=req.topic, urls=req.urls)
    return {
        "brief": result.brief.model_dump(),
        "trace": result.trace.to_dict(),
    }


@app.get("/demo")
def demo() -> dict[str, Any]:
    """One-click demo that always runs (uses StubClient so judges don't pay).
    Same governance layers; only the LLM call and HTTP fetch are stubbed."""
    agent = RapidAgent(
        client=StubClient(),
        budget=BudgetCap(max_usd=0.05),
        allowlist=EgressAllowlist(allowed_hosts=["example.com"]),
        session=_DemoSession(_DEMO_PAGES),
    )
    result = agent.run(
        topic="Building agents on Google Cloud",
        urls=list(_DEMO_PAGES.keys()),
    )
    return {
        "brief": result.brief.model_dump(),
        "trace": result.trace.to_dict(),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    healthz_json = json.dumps(healthz(), indent=2)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<title>rapid-agent — production governance for Gemini</title>
<meta name="description" content="Live demo of rapid-agent: a Gemini agent with budget cap, egress allowlist, typed output, and per-call traces. Built for the Google Cloud Rapid Agent Hackathon (Arize track)." />
<style>
body{{font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:780px;margin:2.5rem auto;padding:0 1.25rem;color:#222}}
h1{{margin:0 0 .25rem;font-size:1.6rem}}
h2{{margin-top:2rem;font-size:1.15rem;border-bottom:1px solid #ddd;padding-bottom:.25rem}}
code,pre{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#f6f6f6;padding:.1rem .3rem;border-radius:4px}}
pre{{padding:.75rem;overflow-x:auto;font-size:.9rem}}
a{{color:#0a58ca}}
.tag{{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:4px;padding:.1rem .5rem;font-size:.8rem;margin-right:.25rem;margin-bottom:.5rem}}
</style></head><body>
<h1>rapid-agent</h1>
<p><span class="tag">Google Cloud Rapid Agent Hackathon</span><span class="tag">Arize track</span><span class="tag">Gemini · Vertex AI · Cloud Run</span></p>
<p>A small Gemini-powered research-brief agent with the four pieces of governance you actually want in production: typed output, a budget cap, an egress allowlist, and a per-call trace.</p>

<h2>Try it</h2>
<p>One-click stub demo (no LLM cost, exercises all four governance layers):</p>
<p><a href="/demo"><code>GET /demo</code> →</a></p>

<p>Full run (uses Vertex AI, requires POST body):</p>
<pre>curl -X POST {os.environ.get('SELF_URL', 'https://<this-service>')}/brief \\
  -H 'content-type: application/json' \\
  -d '{{"topic": "Building agents on Google Cloud", "urls": ["https://cloud.google.com/vertex-ai/docs/generative-ai/learn/overview", "https://ai.google.dev/gemini-api/docs"]}}'</pre>

<h2>Source</h2>
<ul>
  <li><a href="https://github.com/MukundaKatta/rapid-agent">github.com/MukundaKatta/rapid-agent</a> (MIT)</li>
  <li><a href="https://github.com/MukundaKatta/rapid-agent/blob/main/DEPLOY.md">DEPLOY.md</a> — full Cloud Run + Vertex AI walkthrough</li>
  <li><a href="https://youtu.be/8DwP8H6HD8I">Demo video</a></li>
</ul>

<h2>Health</h2>
<pre>{healthz_json}</pre>
</body></html>
"""
