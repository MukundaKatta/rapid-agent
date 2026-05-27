FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY service.py ./

# Install with the vertex extra so VertexClient resolves, plus FastAPI runtime.
RUN pip install --no-cache-dir -e '.[vertex]' \
        fastapi 'uvicorn[standard]'

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD exec uvicorn service:app --host 0.0.0.0 --port $PORT
