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

You can use them on their own. `BudgetCap`, `EgressAllowlist` and `Trace`
are pure standard library: importing them never pulls in `pydantic` or
`requests`, so they work in environments where those extras are not
installed. (`cast_json` is the one exception — it imports `pydantic`
lazily, on first call, with a clear error if it is missing.)

```python
from rapid_agent import BudgetCap, BudgetExceeded

cap = BudgetCap(max_usd=0.05)
cap.reserve(0.012)   # ok
cap.commit(0.012)
cap.reserve(0.05)    # BudgetExceeded
```

## API reference

Everything below is exported from the top-level `rapid_agent` package.

### `run_brief(topic, urls, *, max_usd=0.05, extra_hosts=None, client=None) -> AgentResult`

Run the whole pipeline with sensible defaults. `urls` are fetched only if
their host passes the default allowlist (extend it with `extra_hosts`).
`max_usd` is the hard spend cap for the run. Pass a custom `client` (for
example `StubClient()`) to avoid a live model call. Returns an
`AgentResult` with `.brief`, `.trace` and `.fetched`. Raises `RuntimeError`
if no source could be fetched and `BudgetExceeded` if the cap is hit.

### `RapidAgent(client, budget, allowlist, session=None)`

The agent object behind `run_brief`, for when you want to supply the three
governance layers yourself. Call `.run(topic, urls)` to get an
`AgentResult`. `session` is an optional `requests.Session` (or any object
with a compatible `get`) used for fetching.

### `Brief` / `BriefItem`

pydantic models for the typed output. `Brief` has `.topic: str`,
`.items: list[BriefItem]` and `.overall_takeaway: str`. Each `BriefItem`
has `.url`, `.title`, `.summary` and `.key_points: list[str]`.

### `BudgetCap(max_usd, spent_usd=0.0)`

USD spend cap. `reserve(projected_usd)` raises `BudgetExceeded` if the call
would push total spend past `max_usd`; `commit(actual_usd)` records actual
spend; `remaining_usd` is the (non-negative) headroom left.

### `EgressAllowlist(allowed_hosts=[])`

Host allowlist. `check(url)` raises `EgressDenied` unless the URL host
matches an entry exactly or is a subdomain of one. `with_extra(hosts)`
returns a new allowlist with extra hosts (the original is unchanged).

### `cast_json(text, schema, *, retry=None, max_retries=1) -> BaseModel`

Parse model output into a pydantic `schema`. Strips ```` ```json ````
fences, and if parsing or validation fails it calls `retry(repair_prompt)`
(up to `max_retries` times) with the schema and the error embedded, so a
model can self-correct. Raises `OutputCastError` if every attempt fails.
Requires `pydantic`.

### `Trace` / `TraceEvent`

Per-run event log. `start(name)` then `finish(name, *, usd=, input_tokens=,
output_tokens=, meta=)` records one `TraceEvent`. `total_usd`, `total_ms`
and `to_dict()` (JSON-serializable) summarize the run.

### `GeminiClient` / `StubClient` / `get_default_client(api_key=None)`

`GeminiClient` wraps `google-generativeai`. `StubClient` returns a
deterministic, schema-valid `Brief` with no network call. `get_default_client`
returns a `GeminiClient` if a `GEMINI_API_KEY` / `GOOGLE_API_KEY` is set
(and the SDK is installed) and a `StubClient` otherwise.

## Project layout

```
rapid-agent/
├── examples/run.py            # 60-90s demo, no key required
├── src/rapid_agent/
│   ├── agent.py               # RapidAgent: fetch + LLM + cast + trace
│   ├── brief.py               # Brief / BriefItem pydantic models
│   ├── client.py              # GeminiClient + StubClient
│   ├── governance.py          # cast_json, BudgetCap, EgressAllowlist, Trace
│   └── py.typed               # PEP 561 marker: inline type hints ship
├── tests/                     # 42 unittest tests, <1s
├── .github/workflows/ci.yml   # py_compile + unittest on 3.9-3.12
├── DEPLOY.md                  # Cloud Run + Vertex AI walkthrough
└── pyproject.toml
```

## Run the tests

The test suite is written with the Python standard-library `unittest`
module, so it needs no extra tooling beyond the package itself:

```bash
python -m pip install -e .
python -m unittest discover -s tests
```

pytest works too, if you prefer it:

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

42 tests, well under a second. The full suite runs without network and
without a Gemini key. Tests that require an optional dependency
(`pydantic` for typed output, `requests` for fetching) skip cleanly when
that dependency is not installed, so the governance primitives can be
tested on their own.

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
