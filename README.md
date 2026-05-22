# rapid-agent

A small Gemini-powered research-brief agent with the four pieces of
governance you actually want in production: typed output, a budget cap,
an egress allowlist, and a per-call trace.

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/).
Designed to lift cleanly from a Gemini API free-tier demo into a Vertex AI +
Cloud Run deploy.

## Quickstart

```bash
git clone https://github.com/MukundaKatta/rapid-agent.git
cd rapid-agent
python -m pip install -e .

# Optional: use the real model. Without a key, a deterministic stub runs.
pip install 'rapid-agent[gemini]'
export GEMINI_API_KEY=...   # free-tier key from https://aistudio.google.com/

python examples/run.py
```

That is the whole loop. The demo runs in under 90 seconds and writes a
JSON trace to `rapid_agent_trace.json`.

## Demo output

```
========================================================================
SCENE 2  -  With governance
========================================================================

--- 2a. Egress allowlist blocks unknown hosts. ---
blocked: host 'internal-corp-admin.invalid' not in allowlist ['example.com']

--- 2b. Budget cap reserves before each call. ---
refused: projected $0.0100 would exceed cap $0.00 (already spent $0.0000)

--- 2c. Real run. Fetch + LLM + cast + trace. ---

--- 2d. Typed Brief. ---
topic:   Building agents on Google Cloud
items:   3
  - Agents on Google Cloud (https://example.com/agents-overview)
  - Vertex AI and Gemini (https://example.com/vertex-ai-gemini)
  - Cloud Run for agent backends (https://example.com/cloud-run-deploy)
takeaway: ...

--- 2e. Per-call trace. ---
total cost:   $0.000115
total time:   1 ms
events:       4
budget left:  $0.049885
```

## What it does

Given a topic and a list of URLs, `rapid-agent`:

1. Fetches each URL, but only if the host passes an explicit allowlist.
2. Builds one structured prompt for Gemini.
3. Reserves the projected cost against a USD cap before any model call.
4. Casts the model output into a typed `Brief` (pydantic) with one
   automatic repair retry if the JSON is malformed.
5. Writes a per-call trace with token counts, cost in USD, and latency.

The output is a `Brief` you can index into. Downstream code does not have
to grep prose.

```python
from rapid_agent import run_brief

result = run_brief(
    topic="Building agents on Google Cloud",
    urls=[
        "https://cloud.google.com/vertex-ai/docs/generative-ai/learn/overview",
        "https://ai.google.dev/gemini-api/docs",
    ],
    max_usd=0.05,
)

print(result.brief.overall_takeaway)
for item in result.brief.items:
    print(item.url, item.summary[:80])

print("cost:", result.trace.total_usd, "USD")
```

## The four governance layers

Each layer is a tiny primitive in `src/rapid_agent/governance.py`. They
mirror four published sibling libraries; the inline versions here keep
the demo dependency-light. The README notes the production swap.

| Layer | What it does | Sibling lib |
|-------|--------------|-------------|
| `cast_json` | Parse model output into pydantic. One auto-repair retry with the schema in the prompt. | `agentcast` |
| `BudgetCap` | Reserve projected cost before the call, commit actuals after. Raises `BudgetExceeded`. | `agentleash` |
| `EgressAllowlist` | Host check by exact match or subdomain. Raises `EgressDenied`. | `agentguard` |
| `Trace` | Records per-event start, duration, tokens, USD. Serializes to JSON. | `agenttrace` |

You can use them on their own. They do not depend on the rest of the
package.

```python
from rapid_agent import BudgetCap, BudgetExceeded

cap = BudgetCap(max_usd=0.05)
cap.reserve(0.012)   # ok
cap.commit(0.012)
cap.reserve(0.05)    # BudgetExceeded
```

## Project layout

```
rapid-agent/
├── examples/run.py            # 60-90s demo, no key required
├── src/rapid_agent/
│   ├── agent.py               # RapidAgent: fetch + LLM + cast + trace
│   ├── brief.py               # Brief / BriefItem pydantic models
│   ├── client.py              # GeminiClient + StubClient
│   └── governance.py          # cast_json, BudgetCap, EgressAllowlist, Trace
├── tests/                     # 24 tests, ~0.2s
├── DEPLOY.md                  # Cloud Run + Vertex AI walkthrough
└── pyproject.toml
```

## Run the tests

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

24 tests, around 200 ms. The full suite runs without network and
without a Gemini key.

## Swap to Vertex AI for production

The Gemini free-tier API is great for the demo. For production agents
you want region-aware endpoints, IAM, audit logging, and quotas. That is
Vertex AI's job. See [DEPLOY.md](DEPLOY.md) for:

- A 20-line `vertex_client.py` that drops in for `GeminiClient`
- A Dockerfile and Cloud Run service spec
- An IAM bootstrap script that grants only what is needed

The four governance layers do not change. They sit above the client.

## Why these four layers

In real agent deploys the failure modes are mundane:

- The model returned text with a stray paragraph, downstream JSON parse
  threw, the worker retried in a loop, the bill spiked.
- A tool got a malformed URL, fetched an internal admin host, leaked a
  header.
- Cost on one request was the same as 200 other requests. Nobody saw
  it. The trail was lost.
- A pricing change made every call cost 8% more. Nobody noticed for two
  weeks.

Each governance layer in this repo answers one of those. They are
small, composable, and you can wire them into any Gemini or Vertex
agent. They do not require a framework.

## License

MIT.
