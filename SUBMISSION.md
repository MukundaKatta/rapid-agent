# rapid-agent

A small Gemini-powered research-brief agent with the four pieces of
governance you actually want in production: typed output, a budget cap,
an egress allowlist, and a per-call trace.

## The problem

Most agent demos look great in a notebook and fall over in production.
The same failure modes repeat:

- Model returns prose, downstream JSON parse throws, retry loop runs at
  full cost, bill spikes.
- Tool fetches a URL with a typo, hits an internal host, leaks a header.
- One call costs as much as two hundred others. Nobody saw it. The
  audit trail is a wall of stdout.

These are what break the second a real agent ships.

## The approach

rapid-agent is a small Python project that wires a Gemini call into a
useful task and surrounds it with four governance layers. The task is a
research-brief agent. Give it a topic and a list of URLs. It fetches
each, sends one prompt to Gemini, and returns a typed `Brief` object
you can index into. The loop runs in under 90 seconds and the code
fits in roughly 600 lines.

The four layers are not magic. Each is a small primitive that lives on
its own. You can pull them apart and use them in any agent.

## The four governance layers

**Structured output enforcement (`cast_json`).** The model is told to
return JSON. If it returns something else, the cast function builds a
repair prompt that includes the schema and the error, and calls the
model exactly once more. If repair still fails, the agent raises a
typed error instead of returning garbage.

**Budget cap (`BudgetCap`).** Before each call, the agent projects a
cost based on prompt length and reserves it against a USD cap. If the
projection would overshoot, the call never happens. After the call,
the actual cost is committed. The cap is shared across the run, so the
second call cannot push the total past the limit.

**Egress allowlist (`EgressAllowlist`).** The fetcher checks every URL
against a list of allowed hosts before opening a socket. Exact match or
any subdomain is allowed. Anything else raises `EgressDenied` and the
URL is skipped, with the denial recorded in the trace.

**Per-call trace (`Trace`).** Every fetch and every model call writes
an event with start time, duration, input tokens, output tokens, and
USD cost. The trace serializes to JSON. In production you pipe it to
Cloud Logging by printing it, or push cost to Cloud Monitoring as a
custom metric.

## Demo

The demo runs two scenes back to back. Same task in both. First
without governance, then with.

In scene one, an internal admin URL gets requested with no allowlist
check. Cost climbs across calls with nothing to stop it. The model
returns prose and any downstream code has to grep it. There is no
record of what just happened.

In scene two, the same task runs through `RapidAgent`. The bad URL is
blocked before the socket opens. An oversized budget request is
refused. The model output comes back as a typed `Brief` with three
items, each with a title, summary, and key points. The trace shows
four events, total cost, total time, and how much budget is left. A
JSON trace file is written for later inspection.

## Deploy story

The demo runs locally against the free-tier Gemini API. For production
you swap the client for a Vertex AI client. The four governance layers
do not change. `DEPLOY.md` in the repo has the full walkthrough: a
20-line `vertex_client.py` that drops in for `GeminiClient`, a
Dockerfile, Cloud Run deploy commands with `--no-traffic` for safe
rollouts, IAM that grants only `roles/aiplatform.user`, and a
production checklist.

Two observability hooks are documented. Printing the trace as a JSON
line forwards into Cloud Logging. Pushing `trace.total_usd` as a custom
metric gives a daily spend chart per caller. No extra stack required.

## Why it matters

The hackathon is about rapid agents on Google Cloud. Rapid does not
have to mean fragile. The four governance layers add roughly 200 lines
of code and get the agent ready for real production deployment. Same
agent, same prompt, now with a cost cap, a domain allowlist, a typed
output, and a trace.

## Repository

[github.com/MukundaKatta/rapid-agent](https://github.com/MukundaKatta/rapid-agent)

24 passing tests, runs in 0.2 seconds. The demo runs in 90 seconds
with no key required. Tested on Python 3.9 through 3.11.

## What is next

The Vertex deploy is documented but not run. Once a project is
configured, the steps in DEPLOY.md take about 20 minutes end to end. A
sandbox project with an alert on `BudgetExceeded` in Cloud Logging
would be the natural first deploy target. The same shape works for
tool-using agents (replace the URL fetch with a function call loop),
and the four governance layers carry over without changes.
