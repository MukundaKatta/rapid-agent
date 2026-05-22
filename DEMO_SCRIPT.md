# 3-Minute Demo Video Script

Target length: 3:00. Hard cap 3:30.
Tone: matter of fact, no slogans, no enthusiasm-bait.
Recording: screen capture at 1080p with a single voice track.

## Shot 1 - Setup (0:00 - 0:30, 30s)

**Visual**

- Open the README in the browser (or terminal preview).
- Cursor on the title line.
- Show repo URL in the address bar.

**Narration**

> rapid-agent is a small Python project I built for the Google Cloud
> Rapid Agent Hackathon. It is a research-brief agent. You give it a
> topic and a list of URLs. It calls Gemini and returns a typed Brief
> you can index into. The interesting part is what wraps the model
> call. There are four governance layers, and they are the difference
> between a notebook demo and something you would deploy.

## Shot 2 - The code (0:30 - 1:15, 45s)

**Visual**

- Cut to terminal showing the project layout.
- `tree src/rapid_agent` (or `ls src/rapid_agent`).
- Open `governance.py` and scroll past the four section dividers
  (cast_json, BudgetCap, EgressAllowlist, Trace).
- Briefly show `agent.py` `run()` method.

**Narration**

> The package is small. Four files in `src/rapid_agent`. `governance.py`
> has the four primitives. Each one is independent. `cast_json` parses
> model output into pydantic with one auto-repair retry. `BudgetCap`
> reserves projected cost before the call and commits the actual after.
> `EgressAllowlist` checks the host before opening a socket. `Trace`
> records start, duration, tokens, and USD for every event. The agent
> in `agent.py` just wires them together around a Gemini call.

## Shot 3 - The demo run (1:15 - 2:30, 75s)

**Visual**

- Terminal: `python examples/run.py`
- Let the full output play through. The output has two clearly
  labeled scenes. Scene 1 is "without governance," scene 2 is "with
  governance."
- Zoom on the four labeled sub-shots in scene 2 (2a, 2b, 2c, 2e).
- End on the line that says where the trace file was written.

**Narration**

> The demo runs two scenes back to back. Same task in both. Scene one
> is what happens without governance. A bad URL gets requested. Cost
> climbs with no cap. Output is prose any downstream code has to grep.
> No record of what happened.

> Scene two is the same task through `RapidAgent`. Scene 2a: the bad
> URL is blocked before the socket opens. 2b: a microscopic budget
> refuses an oversized call. 2c: the real run. 2d: the output is a
> typed Brief with three items, each with title, summary, and key
> points. 2e: the trace records four events, total cost, total time,
> and remaining budget. A JSON trace file lands on disk for later
> inspection.

## Shot 4 - Deploy and close (2:30 - 3:00, 30s)

**Visual**

- Open `DEPLOY.md`.
- Scroll past the `vertex_client.py` snippet.
- Scroll past the Dockerfile and the `gcloud run deploy` command.
- Cut back to the repo URL on screen.

**Narration**

> Deploy is documented in DEPLOY.md. You swap `GeminiClient` for a
> 20-line Vertex AI client. The four governance layers do not change.
> Cloud Run command, IAM bootstrap, and an observability hook to Cloud
> Logging are in there. The full path from this demo to a running
> Cloud Run service is about 20 minutes. Repo is
> github dot com slash MukundaKatta slash rapid-agent. Twenty-four
> tests, runs in two-tenths of a second. Thanks for watching.

## Recording notes

- Run `python examples/run.py` once before recording to warm up. The
  first run can be slightly slower because of import time.
- Set terminal to a readable font (16pt+).
- Keep the window narrow so the boxed banners do not wrap.
- If recording with a real Gemini key, set `GEMINI_API_KEY` before the
  demo so the backend banner shows the model name. Otherwise the
  stub banner is fine and the output is still meaningful.
- The video does not need a face cam. Voice + screen is enough.

## What to upload

- 1080p MP4, H.264, AAC audio.
- Devpost requires a public link (YouTube or Vimeo). Set it to
  unlisted, not private, so judges can open it without a login.
