# The server image for Cloud Run. deploy/deploy.sh builds it with Cloud Build; see docs/DEPLOY.md.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=America/Denver
# Pango and HarfBuzz are what WeasyPrint needs to draw the chat-summary PDF; DejaVu covers characters the
# bundled fonts don't (arrows, symbols).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app app
COPY web web
COPY data/docs.json data/docs.json

CMD exec uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --timeout-graceful-shutdown 8
