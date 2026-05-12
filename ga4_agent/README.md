# GA4 ADK Agent

An ADK-powered Google Analytics 4 analyst agent used by the dashboard's **Google Analytics** tab.

## What it does

Accepts natural-language questions and translates them into GA4 Data API calls via an ADK agent loop. Returns formatted analysis with charts and data tables.

## Tools

| Tool | Description |
|---|---|
| `get_today_date()` | Returns today's date for relative date range computation |
| `list_ga4_properties()` | Lists all GA4 properties accessible via credentials |
| `get_available_dimensions_metrics()` | Returns a reference list of GA4 API field names |
| `run_ga4_report(...)` | Executes a GA4 Data API report and returns a text table |

## Setup

### 1. Install dependencies

```bash
pip install google-adk google-analytics-data google-analytics-admin google-auth
```

Or from the main dashboard root:
```bash
pip install -r requirements.txt
```

### 2. Configure credentials

The agent uses one of the following (checked in this order):

**Option A — Service account JSON (recommended for Cloud Run)**
```
GCP_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":...}'
```
Set this environment variable to the full JSON content of your service account key.
The service account needs **Viewer** access granted in GA4 Admin → Property Access Management.

**Option B — Application Default Credentials (local dev)**
```bash
gcloud auth application-default login
```

### 3. Test the agent

```python
from ga4_agent.agent import create_session, chat

create_session("test_user", "test_session")
result = chat(
    user_message="Show me sessions by channel for last 7 days",
    user_id="test_user",
    session_id="test_session",
    property_id="123456789",
    start_date="2025-01-01",
    end_date="2025-01-31",
)
print(result["text"])
```

## Integration

The agent is automatically used by `tabs/tab_ga4.py` when imported successfully.
If `google-adk` is not installed, the tab falls back to a simpler regex-based query pattern.

An **"🤖 AI Agent active"** badge appears next to the connected property when the agent is running.
A **"⚡ Pattern mode"** badge appears when the agent is unavailable.
