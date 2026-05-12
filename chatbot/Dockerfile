# ── Build stage ────────────────────────────────────────────
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY config.py agent.py charts.py app.py logo.png brainlabs_logo.png ./

# Cloud Run injects $PORT at runtime (default 8080)
ENV PORT=8080

EXPOSE 8080

# Run Streamlit — bind to 0.0.0.0 so Cloud Run can reach it
CMD streamlit run app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false