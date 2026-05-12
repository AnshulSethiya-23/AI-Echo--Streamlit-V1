FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ── System dependencies ─────────────────────────────────────────────────────────
# build-essential + python3-dev are required by Prophet (CmdStan compilation)
# curl is used by CmdStan installer
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ─────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Application code ────────────────────────────────────────────────────────────
COPY . .

# ── Cloud Run expects the container to listen on $PORT (default 8080) ───────────
EXPOSE 8080

# ── Streamlit server config ─────────────────────────────────────────────────────
CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]
