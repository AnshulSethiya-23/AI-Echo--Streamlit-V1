"""
Google Ads ADK Agent
====================
ADK agent that answers natural-language questions about Google Ads performance.
Mirrors the chatbot/agent.py pattern exactly.

Tools:
  get_today_date()          — current date for relative date ranges
  list_customer_accounts()  — enumerate accessible Google Ads accounts
  get_gaql_schema()         — reference for common GAQL fields
  run_gaql_query(...)       — execute a GAQL query and return results

Authentication:
  The agent uses the google-ads Python client, which reads credentials from:
    1. Environment variables (GOOGLE_ADS_DEVELOPER_TOKEN, etc.)
    2. A google-ads.yaml file in the working directory or home folder
    3. GOOGLE_ADS_JSON env var (JSON string of google-ads.yaml contents)

  See: https://developers.google.com/google-ads/api/docs/client-libs/python/configuration

Usage (from Streamlit tab):
  from google_ads_agent.agent import chat, create_session

  create_session(user_id, session_id)
  result = chat(user_message, user_id, session_id, customer_id, start_date, end_date)
  # result = {"text": str, "tool_calls": list[str], "df": DataFrame|None, "chart": bool}
"""

from __future__ import annotations

import os
import yaml
import asyncio
import pandas as pd
from datetime import date

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

try:
    from .config import (
        MODEL_NAME, LLM_PROJECT, VERTEX_LOCATION, APP_NAME,
        GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_LOGIN_CUSTOMER_ID,
        GOOGLE_ADS_USE_PROTO_PLUS,
    )
except ImportError:
    from config import (
        MODEL_NAME, LLM_PROJECT, VERTEX_LOCATION, APP_NAME,
        GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_LOGIN_CUSTOMER_ID,
        GOOGLE_ADS_USE_PROTO_PLUS,
    )


# ── Google Ads client factory ─────────────────────────────────────────────────

def _build_ads_client(login_customer_id: str = ""):
    """
    Build a GoogleAdsClient from env vars, GOOGLE_ADS_JSON env var, or google-ads.yaml.
    Raises ImportError if google-ads library not installed.
    Raises ValueError if credentials are not configured.
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        raise ImportError(
            "google-ads library not installed. "
            "Run: pip install google-ads"
        )

    # Option 1: JSON string in env var (easiest for Cloud Run / Docker)
    ads_json = os.getenv("GOOGLE_ADS_JSON", "")
    if ads_json:
        import json
        cfg = json.loads(ads_json)
        if login_customer_id:
            cfg["login_customer_id"] = login_customer_id.replace("-", "")
        return GoogleAdsClient.load_from_dict(cfg, version="v17")

    # Option 2: Individual env vars
    dev_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", GOOGLE_ADS_DEVELOPER_TOKEN)
    if dev_token:
        cfg = {
            "developer_token": dev_token,
            "use_proto_plus": GOOGLE_ADS_USE_PROTO_PLUS,
        }
        # OAuth2 service account (recommended for server-side)
        svc_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
        if svc_json:
            import json
            info = json.loads(svc_json)
            cfg["json_key_file_path"] = None
            cfg["impersonated_email"] = os.getenv("GOOGLE_ADS_IMPERSONATED_EMAIL", "")
            # Use service account credentials directly
            from google.oauth2 import service_account
            scopes = ["https://www.googleapis.com/auth/adwords"]
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=scopes
            )
            return GoogleAdsClient(
                credentials=creds,
                developer_token=dev_token,
                login_customer_id=(login_customer_id or GOOGLE_ADS_LOGIN_CUSTOMER_ID).replace("-", ""),
                use_proto_plus=GOOGLE_ADS_USE_PROTO_PLUS,
            )

        # OAuth2 refresh token (desktop flow)
        cfg["client_id"]     = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
        cfg["client_secret"] = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
        cfg["refresh_token"] = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
        lid = (login_customer_id or GOOGLE_ADS_LOGIN_CUSTOMER_ID).replace("-", "")
        if lid:
            cfg["login_customer_id"] = lid
        return GoogleAdsClient.load_from_dict(cfg, version="v17")

    # Option 3: google-ads.yaml file
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google-ads.yaml")
    if not os.path.exists(yaml_path):
        yaml_path = os.path.expanduser("~/google-ads.yaml")
    if os.path.exists(yaml_path):
        client = GoogleAdsClient.load_from_storage(yaml_path, version="v17")
        if login_customer_id:
            client.login_customer_id = login_customer_id.replace("-", "")
        return client

    raise ValueError(
        "Google Ads credentials not configured. Set one of:\n"
        "  • GOOGLE_ADS_JSON env var (JSON string)\n"
        "  • GOOGLE_ADS_DEVELOPER_TOKEN + GOOGLE_ADS_REFRESH_TOKEN env vars\n"
        "  • google-ads.yaml file in the agent folder or home directory"
    )


# ── System instruction ────────────────────────────────────────────────────────

_INSTRUCTION = """You are a senior Google Ads performance analyst for Brookfield.
You help marketing teams understand their paid search and paid social campaign performance
via the Google Ads API.

You have access to the Google Ads API via GAQL (Google Ads Query Language).

Workflow for answering questions:
1. If the user hasn't specified which account, call list_customer_accounts() first.
2. If you need to know what fields to use, call get_gaql_schema().
3. Always call get_today_date() before computing relative date ranges.
4. Call run_gaql_query() with the customer_id and a valid GAQL query.
5. Interpret the results and present them clearly.

GAQL rules:
- GAQL syntax: SELECT fields FROM resource WHERE conditions ORDER BY field DESC LIMIT N
- ALWAYS wrap dates like: segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
- Customer ID format: numeric only, no dashes (e.g. '1234567890')
- Resources: campaign, ad_group, ad_group_ad, keyword_view, campaign_budget, search_term_view
- For date segments, always include: segments.date in SELECT for time-series queries
- Use metrics.cost_micros / 1000000 to get cost in dollars
- Metrics are pre-aggregated by the resource — use LIMIT to control row count

Common GAQL patterns:
  Campaign performance:
    SELECT campaign.name, metrics.impressions, metrics.clicks,
           metrics.cost_micros, metrics.ctr, metrics.average_cpc
    FROM campaign
    WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
      AND campaign.status = 'ENABLED'
    ORDER BY metrics.cost_micros DESC
    LIMIT 20

  Ad group performance:
    SELECT campaign.name, ad_group.name,
           metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.ctr
    FROM ad_group
    WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
    ORDER BY metrics.impressions DESC
    LIMIT 20

  Top keywords:
    SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
           metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.ctr,
           metrics.average_cpc
    FROM keyword_view
    WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
      AND ad_group_criterion.status = 'ENABLED'
    ORDER BY metrics.impressions DESC
    LIMIT 30

  Search terms report:
    SELECT search_term_view.search_term, metrics.impressions,
           metrics.clicks, metrics.cost_micros, metrics.ctr
    FROM search_term_view
    WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
    ORDER BY metrics.clicks DESC
    LIMIT 50

  Daily spend trend:
    SELECT segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks
    FROM campaign
    WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
    ORDER BY segments.date ASC

Response rules:
- Never mention 'GAQL', 'API', 'query', or technical implementation details
- Format cost: divide cost_micros by 1,000,000 → show as $X,XXX.XX
- Format CPC/CPM: always in dollars
- Format CTR: as percentage (multiply by 100)
- Use bold for metric names and key numbers
- Note trends for time series (improving, declining, stable)
- Add [CHART_REQUESTED] at the end only for time-series data or comparisons
  that benefit from a chart — not for simple ranked tables
- Always present results as a narrative with key takeaways, not just raw numbers

Metric formatting for comparisons:
- ↑/↓ for direction
- <5% = stable | 5–15% = moderate | >15% = significant
- Cost/CPC/CPM: BAD if increasing (red), GOOD if decreasing (green)
- CTR/Conversions/Clicks: GOOD if increasing (green), BAD if decreasing (red)
"""


# ── Tools ─────────────────────────────────────────────────────────────────────

def get_today_date() -> str:
    """
    Returns today's date as a string in YYYY-MM-DD format.
    Always call this before computing relative date ranges such as
    'last 7 days', 'last month', 'year to date', 'last 30 days'.
    """
    return str(date.today())


def list_customer_accounts() -> str:
    """
    Lists all Google Ads customer accounts accessible via the configured credentials.
    Returns customer IDs, names, and currency codes.
    Call this when the user wants to see which accounts are available,
    or when a customer_id has not been provided.
    """
    try:
        client = _build_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        # Use the top-level MCC to list accessible customers
        customer_service = client.get_service("CustomerService")
        accessible = customer_service.list_accessible_customers()

        lines = ["Accessible Google Ads Accounts:\n"]
        for resource_name in accessible.resource_names:
            customer_id = resource_name.split("/")[-1]
            try:
                query = f"""
                    SELECT customer.id, customer.descriptive_name, customer.currency_code,
                           customer.time_zone
                    FROM customer
                    WHERE customer.id = {customer_id}
                    LIMIT 1
                """
                response = ga_service.search(customer_id=customer_id, query=query)
                for row in response:
                    c = row.customer
                    lines.append(
                        f"  Customer ID: {c.id}"
                        f" | Name: {c.descriptive_name}"
                        f" | Currency: {c.currency_code}"
                        f" | Timezone: {c.time_zone}"
                    )
            except Exception:
                lines.append(f"  Customer ID: {customer_id} (details unavailable)")

        return "\n".join(lines) if len(lines) > 1 else "No accessible Google Ads accounts found."

    except ImportError as e:
        return f"FAILED: {str(e)}"
    except Exception as e:
        return f"FAILED to list accounts: {str(e)}"


def get_gaql_schema() -> str:
    """
    Returns a reference guide for commonly used GAQL resources, fields, and metrics.
    Call this when you need to look up exact field names before writing a GAQL query.
    """
    return """GAQL Quick Reference

RESOURCES & KEY FIELDS:
  campaign
    campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type
    campaign.bidding_strategy_type, campaign.budget_amount_micros

  ad_group
    ad_group.id, ad_group.name, ad_group.status, campaign.name

  keyword_view (search keywords)
    ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type
    ad_group_criterion.status, campaign.name, ad_group.name

  search_term_view (actual search queries)
    search_term_view.search_term, search_term_view.status
    campaign.name, ad_group.name

  ad_group_ad (ads)
    ad_group_ad.ad.type, ad_group_ad.ad.final_urls
    ad_group_ad.policy_summary.approval_status

  campaign_budget
    campaign_budget.amount_micros, campaign_budget.delivery_method

COMMON METRICS (available on most resources):
  metrics.impressions          — Total impressions
  metrics.clicks               — Total clicks
  metrics.cost_micros          — Cost in micros (divide by 1,000,000 for $)
  metrics.ctr                  — Click-through rate (0–1, multiply by 100 for %)
  metrics.average_cpc          — Avg cost per click in micros
  metrics.conversions          — Total conversions
  metrics.conversion_rate      — Conversions / clicks (0–1)
  metrics.cost_per_conversion  — Cost per conversion in micros
  metrics.view_through_conversions — View-through conversions
  metrics.search_impression_share — % of eligible search impressions received
  metrics.quality_score        — Quality score (keyword_view only, 1–10)

SEGMENTS:
  segments.date                — Date (YYYY-MM-DD) — use for time series
  segments.device              — DESKTOP, MOBILE, TABLET
  segments.ad_network_type     — SEARCH, SEARCH_PARTNERS, CONTENT, YOUTUBE_WATCH

DATE FILTER (always required for metrics):
  WHERE segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'

STATUS FILTERS:
  campaign.status = 'ENABLED'           (ENABLED, PAUSED, REMOVED)
  ad_group.status = 'ENABLED'
  ad_group_criterion.status = 'ENABLED' (for keywords)

COST CONVERSION:
  metrics.cost_micros / 1000000 = dollars
  metrics.average_cpc / 1000000 = dollars per click
"""


def run_gaql_query(customer_id: str, gaql: str) -> str:
    """
    Executes a Google Ads Query Language (GAQL) query and returns results as a text table.

    Args:
        customer_id:  Numeric Google Ads customer ID without dashes (e.g. '1234567890').
                      This is the account you want to query — NOT the MCC manager account.
        gaql:         A complete, valid GAQL query string. Must include a WHERE clause
                      with a date filter (segments.date BETWEEN ...) whenever querying metrics.
                      Example:
                        SELECT campaign.name, metrics.impressions, metrics.clicks,
                               metrics.cost_micros, metrics.ctr
                        FROM campaign
                        WHERE segments.date BETWEEN '2025-01-01' AND '2025-01-31'
                          AND campaign.status = 'ENABLED'
                        ORDER BY metrics.cost_micros DESC
                        LIMIT 20

    Returns:
        Pipe-separated text table starting with QUERY_SUCCESS,
        or an error message starting with FAILED.
    """
    try:
        clean_id = customer_id.strip().replace("-", "")
        client = _build_ads_client(login_customer_id=clean_id)
        ga_service = client.get_service("GoogleAdsService")

        import time
        t0 = time.time()
        response = ga_service.search(customer_id=clean_id, query=gaql.strip())
        elapsed = time.time() - t0

        # Convert response to list of dicts
        rows = []
        for google_ads_row in response:
            row_dict = {}
            # Flatten the protobuf row into field_name: value pairs
            row_dict = _flatten_google_ads_row(google_ads_row, gaql)
            rows.append(row_dict)

        if not rows:
            return "QUERY_SUCCESS [0 rows]\nNo data returned for this query and date range."

        df = pd.DataFrame(rows)

        # Auto-convert cost_micros columns to dollars
        for col in df.columns:
            if "cost_micros" in col or "average_cpc" in col or "cost_per_conversion" in col:
                try:
                    df[col] = (pd.to_numeric(df[col]) / 1_000_000).round(2)
                    df.rename(columns={col: col.replace("_micros", "_usd")}, inplace=True)
                except (ValueError, TypeError):
                    pass

        # Round other numeric columns
        for col in df.select_dtypes(include="number").columns:
            if "ctr" in col or "rate" in col:
                df[col] = (df[col] * 100).round(2)  # show as %
            elif "impressions" in col or "clicks" in col or "conversions" in col:
                df[col] = df[col].round(0).astype(int)
            else:
                df[col] = df[col].round(4)

        # Build pipe-separated table
        col_widths = {
            col: max(len(str(col)), df[col].astype(str).str.len().max())
            for col in df.columns
        }
        header    = " | ".join(str(c).ljust(col_widths[c]) for c in df.columns)
        separator = "-+-".join("-" * col_widths[c] for c in df.columns)
        row_strs  = [
            " | ".join(str(v).ljust(col_widths[c]) for c, v in zip(df.columns, r))
            for r in df.itertuples(index=False)
        ]
        table = "\n".join([header, separator] + row_strs)

        return f"QUERY_SUCCESS [{len(rows)} rows in {elapsed:.1f}s]\n\n{table}"

    except ImportError as e:
        return f"FAILED: {str(e)}"
    except Exception as e:
        return f"FAILED: {str(e)}"


def _flatten_google_ads_row(row, gaql: str) -> dict:
    """Flatten a Google Ads API row proto into a flat dict, using SELECT field names."""
    import re
    # Extract selected fields from the GAQL query
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", gaql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return {}

    fields = [f.strip() for f in select_match.group(1).split(",")]
    result = {}

    for field in fields:
        try:
            # Navigate the proto object: field = "metrics.clicks" → row.metrics.clicks
            parts = field.split(".")
            obj = row
            for part in parts:
                obj = getattr(obj, part, None)
                if obj is None:
                    break
            # Convert proto enum values to strings
            if hasattr(obj, "name"):  # enum
                result[field] = obj.name
            elif obj is None:
                result[field] = ""
            else:
                result[field] = obj
        except Exception:
            result[field] = ""

    return result


# ── ADK Agent definition ──────────────────────────────────────────────────────

root_agent = Agent(
    name="brookfield_google_ads_analyst",
    model=MODEL_NAME,
    description="Google Ads performance analyst for Brookfield. Runs GAQL queries and generates campaign insights.",
    instruction=_INSTRUCTION,
    tools=[
        get_today_date,
        list_customer_accounts,
        get_gaql_schema,
        run_gaql_query,
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
    customer_id: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """
    Sends a message to the Google Ads ADK agent and returns the response.

    Args:
        user_message:  The natural-language question from the user.
        user_id:       Unique identifier for the user (for session management).
        session_id:    Unique session ID for conversation continuity.
        customer_id:   Google Ads customer ID (injected as context).
        start_date:    Reporting start date YYYY-MM-DD (injected as context).
        end_date:      Reporting end date YYYY-MM-DD (injected as context).

    Returns:
        {
          "text":       str,          final response text
          "tool_calls": list[str],    names of tools called
          "df":         DataFrame,    last query result (for chart/table display)
          "chart":      bool,         True if LLM wants a chart rendered
        }
    """
    # Inject context
    context_prefix = ""
    if customer_id:
        context_prefix += f"[Context] Google Ads Customer ID: {customer_id}\n"
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
        last_query_result = ""

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
                        if part.function_response and part.function_response.name == "run_gaql_query":
                            resp = part.function_response.response
                            if isinstance(resp, dict):
                                last_query_result = resp.get("result", "")
                            elif isinstance(resp, str):
                                last_query_result = resp
                    except Exception:
                        pass

            if event.is_final_response():
                try:
                    for part in event.content.parts:
                        if part.text:
                            final_text += part.text
                except Exception:
                    pass

        return final_text.strip(), tool_calls, last_query_result

    final_text, tool_calls, last_query_result = asyncio.run(_run())

    # Parse last GAQL result into DataFrame for display
    last_df = None
    if last_query_result and last_query_result.startswith("QUERY_SUCCESS"):
        try:
            lines = last_query_result.split("\n")
            data_lines = [l for l in lines if " | " in l]
            if len(data_lines) >= 2:
                headers = [h.strip() for h in data_lines[0].split(" | ")]
                rows = []
                for line in data_lines[2:]:
                    row = [v.strip() for v in line.split(" | ")]
                    rows.append(row)
                last_df = pd.DataFrame(rows, columns=headers)
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
