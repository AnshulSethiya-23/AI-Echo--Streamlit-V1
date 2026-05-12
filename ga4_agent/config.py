import os

# ── Model & GCP config ────────────────────────────────────────────────────────
MODEL_NAME      = "gemini-2.5-pro"
LLM_PROJECT     = os.getenv("GCP_PROJECT_ID", "generative-insights-poc-bi")
VERTEX_LOCATION = "us-central1"
APP_NAME        = "brookfield_ga4_agent"
