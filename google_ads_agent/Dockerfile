# ── Google Ads Agent — container build ───────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent files
COPY config.py agent.py __init__.py ./

# Optional: copy google-ads.yaml if using file-based credentials
# COPY google-ads.yaml ./

# Required env vars at runtime:
#   GOOGLE_ADS_DEVELOPER_TOKEN
#   GOOGLE_ADS_JSON  (or individual OAuth2 vars)
#   GCP_PROJECT_ID

ENV PORT=8080
EXPOSE 8080

CMD ["python", "-c", "from agent import chat; print('Google Ads agent loaded OK')"]
