# Deploy rapid-agent on Google Cloud

This guide takes the local demo and turns it into a Vertex AI + Cloud Run
service. The four governance layers move unchanged. Only the client
swaps.

Cost notice: nothing in this repo runs against billable Google Cloud
surfaces by default. Following the steps below will create billable
resources. Do not run them in a project you do not own.

## 0. One-time setup

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

Pick a region. The rest of this guide uses `us-central1`.

## 1. Swap GeminiClient for a Vertex client

Create `src/rapid_agent/vertex_client.py`:

```python
"""Vertex AI client. Drops in for GeminiClient with no agent changes."""
from typing import Any
from vertexai import init as vertex_init
from vertexai.generative_models import GenerativeModel

from rapid_agent.client import LLMResponse, _rough_token_count


class VertexClient:
    def __init__(
        self,
        *,
        project: str,
        location: str = "us-central1",
        model: str = "gemini-1.5-flash-002",
    ) -> None:
        vertex_init(project=project, location=location)
        self._model = GenerativeModel(model)
        self.name = model

    def complete(self, prompt: str, *, temperature: float = 0.2) -> LLMResponse:
        resp: Any = self._model.generate_content(
            prompt, generation_config={"temperature": temperature}
        )
        text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", _rough_token_count(prompt))
        out_tok = getattr(usage, "candidates_token_count", _rough_token_count(text))
        return LLMResponse(text=text, input_tokens=in_tok, output_tokens=out_tok)
```

Then wire it into your service:

```python
from rapid_agent import RapidAgent, BudgetCap, EgressAllowlist
from rapid_agent.vertex_client import VertexClient

agent = RapidAgent(
    client=VertexClient(project="YOUR_PROJECT_ID"),
    budget=BudgetCap(max_usd=0.05),
    allowlist=EgressAllowlist(allowed_hosts=["cloud.google.com", "ai.google.dev"]),
)
```

Note: Vertex AI pricing differs from the free-tier Gemini API. Update
the constants in `client.py` (`PRICE_INPUT_PER_1K_USD`,
`PRICE_OUTPUT_PER_1K_USD`) to match the model you use, or pull live
pricing from the Vertex pricing page.

## 2. Service wrapper

Create `service.py` next to `pyproject.toml`:

```python
import os
from fastapi import FastAPI
from pydantic import BaseModel
from rapid_agent import RapidAgent, BudgetCap, EgressAllowlist
from rapid_agent.vertex_client import VertexClient

class BriefRequest(BaseModel):
    topic: str
    urls: list[str]

app = FastAPI()
client = VertexClient(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("VERTEX_LOCATION", "us-central1"),
)

ALLOWLIST = EgressAllowlist(allowed_hosts=os.environ["ALLOWED_HOSTS"].split(","))

@app.post("/brief")
def brief(req: BriefRequest):
    agent = RapidAgent(
        client=client,
        budget=BudgetCap(max_usd=float(os.environ.get("MAX_USD", "0.05"))),
        allowlist=ALLOWLIST,
    )
    result = agent.run(topic=req.topic, urls=req.urls)
    return {
        "brief": result.brief.model_dump(),
        "trace": result.trace.to_dict(),
    }
```

Add `fastapi` and `uvicorn[standard]` to `pyproject.toml`.

## 3. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY service.py ./

RUN pip install --no-cache-dir -e '.[vertex]' fastapi 'uvicorn[standard]'

ENV PORT=8080
CMD exec uvicorn service:app --host 0.0.0.0 --port $PORT
```

## 4. Build and deploy

Push to Artifact Registry, then deploy to Cloud Run. The `--no-traffic`
flag puts the revision in cold storage so it does not start serving
until you flip traffic.

```bash
PROJECT=$(gcloud config get-value project)
REGION=us-central1
REPO=rapid-agent
SERVICE=rapid-agent

gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION || true

gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:latest .

gcloud run deploy $SERVICE \
  --image $REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:latest \
  --region $REGION \
  --no-allow-unauthenticated \
  --concurrency 4 \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 5 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,VERTEX_LOCATION=$REGION,ALLOWED_HOSTS=cloud.google.com,ai.google.dev,MAX_USD=0.10" \
  --no-traffic
```

When you are ready to flip:

```bash
gcloud run services update-traffic $SERVICE --to-latest --region $REGION
```

## 5. IAM, the minimum that works

The Cloud Run service account needs Vertex AI access only. Nothing
else.

```bash
SA=$(gcloud run services describe $SERVICE --region $REGION \
  --format='value(spec.template.spec.serviceAccountName)')

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/aiplatform.user"
```

## 6. Observability without an extra stack

The `Trace` object already emits a serializable record per run. Two easy
hooks:

- **Cloud Logging:** `print(json.dumps({"severity":"INFO", "trace": trace.to_dict()}))`. Cloud Run forwards stdout to Cloud Logging as JSON.
- **Cost dashboard:** push `trace.total_usd` to Cloud Monitoring with a
  custom metric. One value per run gives you a daily spend chart per
  agent caller.

## 7. Production checklist

- [ ] Replace pricing constants in `client.py` with Vertex pricing for
      your model.
- [ ] Set `MAX_USD` on the service to a number tied to your monthly
      budget alert.
- [ ] Lock `ALLOWED_HOSTS` to the smallest set the agent really needs.
- [ ] Turn on Cloud Logging-based alert when `BudgetExceeded` or
      `EgressDenied` shows up in logs.
- [ ] Keep a copy of the request topic + URLs alongside the trace for
      audit.
- [ ] Add an integration test that runs against a sandbox Vertex
      project before each deploy.

That is the full path from `examples/run.py` to a running Cloud Run
service. Every layer of governance comes along unchanged.
