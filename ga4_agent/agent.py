"""
GA4 ADK Agent
=============
ADK agent that answers natural-language questions about Google Analytics 4 data.
Mirrors the chatbot/agent.py pattern exactly.

Tools:
  get_today_date()                    — current date for relative date ranges
  list_ga4_properties()               — enumerate accessible GA4 properties
  get_available_dimensions_metrics()  — curated list of valid GA4 API fields
  run_ga4_report(...)                 — execute a GA4 Data API report

Usage (from Streamlit tab):
  from ga4_agent.agent import chat, create_session

  create_session(user_id, session_id)
  result = chat(user_message, user_id, session_id, property_id, start_date, end_date)
  # result = {"text": str, "tool_calls": list[str], "df": DataFrame|None, "chart": bool}
"""

from __future__ import annotations

import os
import json
import asyncio
import pandas as pd
from datetime import date

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

try:
    from .config import MODEL_NAME, LLM_PROJECT, VERTEX_LOCATION, APP_NAME
except ImportError:
    from config import MODEL_NAME, LLM_PROJECT, VERTEX_LOCATION, APP_NAME


# ── Auth helper ───────────────────────────────────────────────────────────────

def _make_credentials():
    """Return GA4-scoped credentials from env var or ADC."""
    svc_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
    if svc_json:
        try:
            from google.oauth2 import service_account
            info = json.loads(svc_json)
            scopes = [
                "https://www.googleapis.com/auth/analytics.readonly",
            ]
            return service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
        except Exception:
            pass
    from google.auth import default as google_auth_default
    creds, _ = google_auth_default()
    return creds


# ── System instruction ────────────────────────────────────────────────────────

_INSTRUCTION = """You are a Google Analytics 4 expert analyst assistant for Brookfield.
You help marketing and analytics teams understand their website and app performance data.

You have access to GA4 reporting via the Google Analytics Data API.

Workflow for answering questions:
1. If you don't know what properties are available, call list_ga4_properties().
2. If you need to know what dimensions/metrics to use, call get_available_dimensions_metrics().
3. Always call get_today_date() before computing relative date ranges like 'last 7 days',
   'last month', 'year to date'. Use it as your reference point.
4. Call run_ga4_report() with the correct property_id, date range, dimensions, and metrics.
   The property_id and date range are usually provided in the user's message context.
5. Interpret the results and present them clearly.

GA4 API rules:
- property_id is numeric only — strip 'properties/' prefix if present
- Dimension and metric names must be exact camelCase GA4 API names
  (e.g. 'sessionDefaultChannelGroup', not 'Channel Group')
- For date trends, use dimension 'date' (returns YYYYMMDD format)
- Date format for run_ga4_report: YYYY-MM-DD or special values like 'today', 'yesterday', '7daysAgo'
- To filter by dimension value, use dimension_filter like 'country==United States'
- order_by_metric sorts descending — useful for 'top X' questions
- limit caps row count — default 20, increase for time series

Common GA4 report patterns:
- "Sessions over time"       → dimensions='date',   metrics='sessions,activeUsers'
- "Channel breakdown"        → dimensions='sessionDefaultChannelGroup', metrics='sessions,engagementRate'
- "Top pages"                → dimensions='pagePath', metrics='screenPageViews,sessions', order_by_metric='screenPageViews'
- "Device split"             → dimensions='deviceCategory', metrics='sessions,activeUsers'
- "Country performance"      → dimensions='country', metrics='sessions,activeUsers', order_by_metric='sessions', limit=20
- "Campaign traffic"         → dimensions='sessionCampaignName', metrics='sessions,activeUsers', order_by_metric='sessions'
- "Engagement"               → dimensions='date', metrics='engagementRate,averageSessionDuration,bounceRate'
- "Top events"               → dimensions='eventName', metrics='eventCount', order_by_metric='eventCount'

Response rules:
- Never mention 'API', 'GA4 API', 'Data API' or technical implementation details
- Present numbers with appropriate formatting: commas for large numbers, % for rates
- For bounce rate and engagement rate, multiply by 100 to show as percentage
- For averageSessionDuration, show in minutes:seconds format
- Use bold for metric names and key numbers
- If data is a time series (dimension=date), note trends (up, down, stable)
- If no data returned, suggest checking the property ID, date range, or metric names
- Add [CHART_REQUESTED] at the end ONLY when showing time series data or comparisons
  that would benefit from a visual chart. For tables of top items, no chart needed.
- Always present results as a clear narrative, not just raw numbers

Metric formatting (for comparison questions):
- Use ↑/↓ to indicate direction
- Use <5% = stable | 5–15% = moderate change | >15% = significant change
"""


# ── Tools ─────────────────────────────────────────────────────────────────────

def get_today_date() -> str:
    """
    Returns today's date as a string in YYYY-MM-DD format.
    Always call this before computing relative date ranges such as
    'last 7 days', 'last month', 'year to date', 'last 30 days'.
    """
    return str(date.today())


def list_ga4_properties() -> str:
    """
    Lists all Google Analytics 4 properties the credentials have access to.
    Returns property IDs, display names, and account names.
    Call this when the user wants to know which GA4 properties are available,
    or when a property_id has not been provided.
    """
    try:
        from google.analytics.admin import AnalyticsAdminServiceClient
        creds = _make_credentials()
        client = AnalyticsAdminServiceClient(credentials=creds)
        summaries = client.list_account_summaries(request={})
        lines = ["Available GA4 Properties:\n"]
        count = 0
        for account in summaries:
            for prop in account.property_summaries:
                prop_id = prop.property.replace("properties/", "")
                lines.append(
                    f"  Property ID: {prop_id}"
                    f" | Name: {prop.display_name}"
                    f" | Account: {account.display_name}"
                )
                count += 1
        if count == 0:
            return "No GA4 properties found. Check that the service account has been granted Viewer access."
        return "\n".join(lines)
    except ImportError:
        return "FAILED: google-analytics-admin library not installed. Run: pip install google-analytics-admin"
    except Exception as e:
        return f"FAILED to list properties: {str(e)}"


def get_available_dimensions_metrics() -> str:
    """
    Returns a curated reference list of the most commonly used GA4 dimensions
    and metrics for the Data API. Call this when you need to look up the exact
    camelCase API name for a dimension or metric before calling run_ga4_report().
    """
    return """Common GA4 Dimensions (use exact names in run_ga4_report):
  date                         — Date in YYYYMMDD format
  sessionDefaultChannelGroup   — Traffic channel (Organic Search, Paid Search, Direct, Referral, etc.)
  country                      — Country of user
  city                         — City of user
  deviceCategory               — Device type: desktop, mobile, tablet
  operatingSystem              — OS: iOS, Android, Windows, macOS, etc.
  browser                      — Browser: Chrome, Safari, Firefox, etc.
  pagePath                     — Page URL path (without domain)
  pageTitle                    — Page title
  landingPage                  — First page of session (path only)
  landingPagePlusQueryString   — First page with query params
  sessionSource                — Session traffic source (google, facebook, etc.)
  sessionMedium                — Session medium (organic, cpc, email, etc.)
  sessionCampaignName          — UTM campaign name
  eventName                    — GA4 event name (page_view, click, scroll, etc.)
  newVsReturning               — 'new' or 'returning'
  userAgeBracket               — Age bracket (if enabled)
  userGender                   — Gender (if enabled)

Common GA4 Metrics (use exact names in run_ga4_report):
  sessions                     — Total sessions
  totalUsers                   — Unique users
  newUsers                     — First-time users
  activeUsers                  — Users who triggered an engagement event
  screenPageViews              — Total page/screen views
  averageSessionDuration       — Avg session length in seconds
  bounceRate                   — Bounce rate (0–1, multiply by 100 for %)
  engagementRate               — Sessions with engagement / total sessions (0–1)
  engagedSessions              — Sessions with 1+ engagement events
  eventsPerSession             — Average events per session
  eventCount                   — Total events fired
  conversions                  — Total conversion events
  sessionConversionRate        — Conversions / sessions (0–1)
  totalRevenue                 — Total e-commerce revenue
  transactions                 — E-commerce transaction count

Date shorthand accepted by run_ga4_report:
  'today'        — current day
  'yesterday'    — previous day
  '7daysAgo'     — 7 days ago
  '30daysAgo'    — 30 days ago
  '90daysAgo'    — 90 days ago
  'YYYY-MM-DD'   — specific date
"""


def run_ga4_report(
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: str,
    metrics: str,
    dimension_filter: str = "",
    order_by_metric: str = "",
    limit: int = 20,
) -> str:
    """
    Executes a Google Analytics 4 Data API report and returns results as a text table.

    Args:
        property_id:      Numeric GA4 property ID only (e.g. '123456789').
                          Do NOT include 'properties/' prefix.
        start_date:       Start of date range. Use YYYY-MM-DD or shortcuts:
                          'today', 'yesterday', '7daysAgo', '30daysAgo', '90daysAgo'.
        end_date:         End of date range. Use YYYY-MM-DD or 'today', 'yesterday'.
        dimensions:       Comma-separated GA4 dimension names (camelCase).
                          Example: 'date,sessionDefaultChannelGroup'
        metrics:          Comma-separated GA4 metric names (camelCase).
                          Example: 'sessions,activeUsers,bounceRate'
        dimension_filter: Optional filter as 'dimensionName==value'.
                          Example: 'country==United States' or 'deviceCategory==mobile'
                          Leave empty for no filtering.
        order_by_metric:  Optional metric name to order results by (descending).
                          Example: 'sessions' — useful for 'top X' queries.
                          Leave empty for default ordering.
        limit:            Max rows to return. Default 20, maximum 100.
                          Use 90 for day-by-day time series over 3 months.

    Returns:
        Pipe-separated text table of results starting with QUERY_SUCCESS,
        or error message starting with FAILED.
    """
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Dimension, Metric,
            OrderBy, FilterExpression, Filter,
        )
    except ImportError:
        return (
            "FAILED: google-analytics-data library not installed. "
            "Run: pip install google-analytics-data"
        )

    try:
        creds = _make_credentials()
        client = BetaAnalyticsDataClient(credentials=creds)

        # Parse inputs
        prop_id = property_id.strip().replace("properties/", "")
        dim_list = [Dimension(name=d.strip()) for d in dimensions.split(",") if d.strip()]
        met_list = [Metric(name=m.strip()) for m in metrics.split(",") if m.strip()]
        row_limit = min(int(limit), 100)

        request = RunReportRequest(
            property=f"properties/{prop_id}",
            date_ranges=[DateRange(start_date=start_date.strip(), end_date=end_date.strip())],
            dimensions=dim_list,
            metrics=met_list,
            limit=row_limit,
        )

        # Optional ordering
        if order_by_metric.strip():
            request.order_bys = [
                OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name=order_by_metric.strip()),
                    desc=True,
                )
            ]

        # Optional dimension filter: "dimensionName==value"
        if dimension_filter.strip() and "==" in dimension_filter:
            parts = dimension_filter.split("==", 1)
            request.dimension_filter = FilterExpression(
                filter=Filter(
                    field_name=parts[0].strip(),
                    string_filter=Filter.StringFilter(
                        value=parts[1].strip(),
                        match_type=Filter.StringFilter.MatchType.EXACT,
                    ),
                )
            )

        response = client.run_report(request=request)

        if not response.rows:
            return (
                "QUERY_SUCCESS [0 rows]\n"
                "No data returned for these parameters. "
                "The property may have no data in this date range, or the "
                "dimension/metric names may be incorrect."
            )

        # Build DataFrame
        dim_headers = [h.name for h in response.dimension_headers]
        met_headers = [h.name for h in response.metric_headers]
        all_headers = dim_headers + met_headers

        rows = []
        for row in response.rows:
            r = [dv.value for dv in row.dimension_values]
            r += [mv.value for mv in row.metric_values]
            rows.append(r)

        df = pd.DataFrame(rows, columns=all_headers)

        # Convert numeric columns
        for col in met_headers:
            try:
                df[col] = pd.to_numeric(df[col]).round(4)
            except (ValueError, TypeError):
                pass

        # Build pipe-separated table (matches BQ chatbot format)
        col_widths = {
            col: max(len(str(col)), df[col].astype(str).str.len().max())
            for col in df.columns
        }
        header    = " | ".join(str(c).ljust(col_widths[c]) for c in df.columns)
        separator = "-+-".join("-" * col_widths[c] for c in df.columns)
        row_strs  = [
            " | ".join(str(v).ljust(col_widths[c]) for c, v in zip(df.columns, row))
            for row in df.itertuples(index=False)
        ]
        table = "\n".join([header, separator] + row_strs)

        return f"QUERY_SUCCESS [{len(rows)} rows]\n\n{table}"

    except Exception as e:
        return f"FAILED: {str(e)}"


# ── ADK Agent definition ──────────────────────────────────────────────────────

root_agent = Agent(
    name="brookfield_ga4_analyst",
    model=MODEL_NAME,
    description="GA4 analytics expert for Brookfield. Queries Google Analytics 4 Data API and generates insights.",
    instruction=_INSTRUCTION,
    tools=[
        get_today_date,
        list_ga4_properties,
        get_available_dimensions_metrics,
        run_ga4_report,
    ],
)

# ── Session service ───────────────────────────────────────────────────────────

session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


# ── Sync helpers for Streamlit ────────────────────────────────────────────────

def create_session(user_id: str, session_id: str) -> None:
    """Creates a new ADK session. Call once per conversation."""
    async def _create():
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
    asyncio.run(_create())


def chat(
    user_message: str,
    user_id: str,
    session_id: str,
    property_id: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """
    Sends a message to the GA4 ADK agent and returns the response.

    The property_id, start_date, and end_date are injected as context so the
    agent always knows which property/period the user is asking about without
    requiring them to repeat it every time.

    Returns:
        {
          "text":       str,          final response text (may contain HTML spans)
          "tool_calls": list[str],    names of tools called
          "df":         DataFrame,    last GA4 report result (for chart/table display)
          "chart":      bool,         True if LLM wants a chart rendered
        }
    """
    # Inject context so the agent always knows the property and date range
    context_prefix = ""
    if property_id:
        context_prefix += f"[Context] GA4 Property ID: {property_id}\n"
    if start_date and end_date:
        context_prefix += f"[Context] Date range: {start_date} to {end_date}\n"
    if context_prefix:
        context_prefix += "\n"

    full_message = context_prefix + user_message

    async def _run():
        content = types.Content(
            role="user",
            parts=[types.Part(text=full_message)],
        )

        final_text = ""
        tool_calls = []
        last_report_result = ""

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    try:
                        if part.function_call and part.function_call.name:
                            tool_calls.append(part.function_call.name)
                        # Capture run_ga4_report results so we can parse them into a DataFrame
                        if part.function_response and part.function_response.name == "run_ga4_report":
                            resp = part.function_response.response
                            if isinstance(resp, dict):
                                last_report_result = resp.get("result", "")
                            elif isinstance(resp, str):
                                last_report_result = resp
                    except Exception:
                        pass

            if event.is_final_response():
                try:
                    for part in event.content.parts:
                        if part.text:
                            final_text += part.text
                except Exception:
                    pass

        return final_text.strip(), tool_calls, last_report_result

    final_text, tool_calls, last_report_result = asyncio.run(_run())

    # Parse the last GA4 report result into a DataFrame for display
    last_df = None
    if last_report_result and last_report_result.startswith("QUERY_SUCCESS"):
        try:
            lines = last_report_result.split("\n")
            # Find the header line (after the QUERY_SUCCESS line and blank line)
            data_lines = [l for l in lines if " | " in l]
            if len(data_lines) >= 2:
                headers = [h.strip() for h in data_lines[0].split(" | ")]
                rows = []
                for line in data_lines[2:]:  # skip header and separator
                    row = [v.strip() for v in line.split(" | ")]
                    rows.append(row)
                last_df = pd.DataFrame(rows, columns=headers)
                # Convert numeric columns
                for col in last_df.columns:
                    try:
                        last_df[col] = pd.to_numeric(last_df[col])
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    chart_requested = "[CHART_REQUESTED]" in final_text
    final_text      = final_text.replace("[CHART_REQUESTED]", "").strip()

    return {
        "text":       final_text,
        "tool_calls": tool_calls,
        "df":         last_df,
        "chart":      chart_requested,
    }
