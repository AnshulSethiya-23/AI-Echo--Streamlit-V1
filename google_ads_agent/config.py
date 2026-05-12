import os

# ── Model & GCP config ────────────────────────────────────────────────────────
MODEL_NAME      = "gemini-2.5-pro"
LLM_PROJECT     = os.getenv("GCP_PROJECT_ID", "generative-insights-poc-bi")
VERTEX_LOCATION = "us-central1"
APP_NAME        = "brookfield_google_ads_agent"

# ── Google Ads config ─────────────────────────────────────────────────────────
# These can be set via environment variables or a google-ads.yaml file.
# See: https://developers.google.com/google-ads/api/docs/client-libs/python/configuration
GOOGLE_ADS_DEVELOPER_TOKEN   = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
GOOGLE_ADS_LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")  # MCC account ID
GOOGLE_ADS_USE_PROTO_PLUS    = True
