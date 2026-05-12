# ── GA4 Agent — standalone Streamlit app (optional) ──────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent files
COPY config.py agent.py __init__.py ./

# Cloud Run injects $PORT at runtime
ENV PORT=8080
EXPOSE 8080

# If you create a standalone app.py for this agent, run it here:
# CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
CMD ["python", "-c", "from agent import chat; print('GA4 agent loaded OK')"]
