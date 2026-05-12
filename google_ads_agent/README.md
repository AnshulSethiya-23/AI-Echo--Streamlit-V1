# Google Ads ADK Agent

An ADK-powered Google Ads analyst agent. Use it to add a **Google Ads** chat tab to the dashboard, or call it standalone.

## What it does

Accepts natural-language questions about Google Ads performance and translates them into GAQL (Google Ads Query Language) queries via an ADK agent loop. Returns formatted campaign insights, keyword data, and spend analysis.

## Tools

| Tool | Description |
|---|---|
| `get_today_date()` | Returns today's date for relative date range computation |
| `list_customer_accounts()` | Lists all accessible Google Ads accounts |
| `get_gaql_schema()` | Returns a GAQL field reference guide |
| `run_gaql_query(customer_id, gaql)` | Executes a GAQL query and returns a text table |

## Setup

### 1. Install dependencies

```bash
pip install google-adk google-ads>=24.0.0 google-auth
```

### 2. Configure credentials

Google Ads requires both **API credentials** and a **developer token**.

**Option A — JSON env var (recommended for Cloud Run)**
```bash
export GOOGLE_ADS_JSON='{"developer_token":"...","client_id":"...","client_secret":"...","refresh_token":"...","login_customer_id":"..."}'
```

**Option B — Individual env vars**
```bash
export GOOGLE_ADS_DEVELOPER_TOKEN="your-developer-token"
export GOOGLE_ADS_CLIENT_ID="your-oauth2-client-id"
export GOOGLE_ADS_CLIENT_SECRET="your-oauth2-client-secret"
export GOOGLE_ADS_REFRESH_TOKEN="your-refresh-token"
export GOOGLE_ADS_LOGIN_CUSTOMER_ID="1234567890"  # MCC/manager account
```

**Option C — google-ads.yaml file**

Place a `google-ads.yaml` in this folder or in your home directory:
```yaml
developer_token: "your-developer-token"
client_id: "your-client-id"
client_secret: "your-client-secret"
refresh_token: "your-refresh-token"
login_customer_id: "1234567890"
use_proto_plus: true
```

See [Google Ads API Python client configuration](https://developers.google.com/google-ads/api/docs/client-libs/python/configuration) for full options.

### 3. Test the agent

```python
from google_ads_agent.agent import create_session, chat

create_session("test_user", "test_session")
result = chat(
    user_message="Show me top campaigns by spend last 30 days",
    user_id="test_user",
    session_id="test_session",
    customer_id="1234567890",
    start_date="2025-01-01",
    end_date="2025-01-31",
)
print(result["text"])
```

## Adding a Google Ads tab to the dashboard

1. Add `from google_ads_agent.agent import chat as gads_chat, create_session as gads_create_session` to your tab file
2. Create a new `tabs/tab_google_ads.py` following the same pattern as `tabs/tab_ga4.py`
3. Register it in `app.py`:
   ```python
   from tabs import tab_google_ads
   # ...
   with tabs[7]:
       tab_google_ads.render(start_str, end_str)
   ```

## Developer token

A Google Ads developer token is required. Apply at:
https://developers.google.com/google-ads/api/docs/first-call/dev-token
