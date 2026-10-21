# The server image for Cloud Run. deploy/deploy.sh builds it with Cloud Build; see docs/DEPLOY.md.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=America/Denver
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app app
COPY web web
COPY data/docs.json data/docs.json

CMD exec uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --timeout-graceful-shutdown 8
