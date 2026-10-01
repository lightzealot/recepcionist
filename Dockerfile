# AIReceptionist: worker (default CMD) or dashboard API (override command).
# Build context: repo root (AIReceptionist/).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY receptionist ./receptionist
COPY api_server.py start.sh ./
RUN pip install -e . && chmod +x start.sh

COPY config ./config

VOLUME ["/app/messages", "/app/transcripts"]

# Production worker. On Easypanel, set the start command to `bash start.sh`
# to run worker + dashboard API sharing /app/messages and /app/transcripts.
CMD ["python", "-m", "receptionist.agent", "start"]
