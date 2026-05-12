"""
Brookfield ADK Agent
====================
Uses official google-adk package:
  - Agent (LlmAgent)            — the agent definition
  - Runner                      — manages the agentic loop
  - InMemorySessionService      — conversation history per session
  - Plain Python functions       — auto-wrapped as FunctionTools by ADK

ADK automatically:
  - Generates tool schemas from function signatures + docstrings
  - Decides when to call which tool
  - Handles the tool call → result → next step loop
  - Maintains conversation state via sessions
"""

import time
import asyncio
import pandas as pd
from datetime import date
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.cloud import bigquery
from google.auth import default as google_auth_default
from config import (
    BQ_PROJECT, BQ_BILLING_PROJECT, LLM_PROJECT,
    VERTEX_LOCATION, DATASET_ID, MODEL_NAME, TABLE_DESCRIPTIONS,
)

APP_NAME = "brookfield_marketing_agent"


# ── Build system instruction ───────────────────────────────
def _build_instruction() -> str:
    table_context = "\n".join([
        f"- `{BQ_PROJECT}.{DATASET_ID}.{name}`: {info['description']}\n"
        f"  Columns: {', '.join(info['key_columns'])}\n"
        f"  {info['filter_note']}"
        for name, info in TABLE_DESCRIPTIONS.items()
    ])

    return f"""You are a senior performance marketing analyst assistant for Brookfield.
You have access to BigQuery tables with paid media data across Search, Social, and Programmatic.

Available tables:
{table_context}

SQL rules:
- IMPORTANT: Always call run_bq_query with just the SQL string — never wrap in Python code
- Fully qualified table names: `{BQ_PROJECT}.{DATASET_ID}.table_name`
- When asked for channel-wise or all-channel data, ALWAYS use Brookfield_1H_Executive_Summary_ table — it has all channels in one place. Never query individual channel tables separately for cross-channel questions.
- Only query individual tables (Social, Search, Programmatic) when asked specifically about one channel.
- Date column is `Date` (capital D), use BETWEEN for ranges
- Use SAFE_DIVIDE() for ratios, IFNULL(col, 0) for aggregations
- Apply Data_Source_name or Data_Source filters as noted above
- Aggregate data — don't return raw keyword-level rows for summary questions.
- CPV (Cost Per View) = SAFE_DIVIDE(SUM(Cost), SUM(Video_Completed_Views__Display__Video_360)) — only applicable for Programmatic table.
- For Programmatic queries involving Channels_DV360, if the user asks about a specific channel, first run: SELECT DISTINCT Channels_DV360 
  FROM `funnel-data.brookfield_dashboard.Brookfield_1H_Programmatic` to discover valid values, then match the user's intent to the closest value and filter accordingly.
- For period comparisons use UNION ALL (long format), NOT CROSS JOIN or FULL JOIN. Structure like:
    WITH curr AS (
      SELECT [aggregated metrics]
      FROM `table`
      WHERE DATE(Date) BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
    ),
    prev AS (
      SELECT [aggregated metrics]
      FROM `table`
      WHERE DATE(Date) BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
    )
    SELECT 'Previous Month' AS period, [all metric columns] FROM prev
    UNION ALL
    SELECT 'Last Month'     AS period, [all metric columns] FROM curr
  Rules:
  - Always wrap the Date column in DATE() e.g. DATE(Date) — the column may be DATETIME or TIMESTAMP
  - Always use BETWEEN with full 'YYYY-MM-DD' dates (e.g. '2026-03-01' AND '2026-03-31'), never year-month only
  - Always list metric columns explicitly in both SELECT statements — never use SELECT *
  - Always put 'Previous Month' row first and 'Last Month' row second so charts display chronologically left-to-right
  - Never use CROSS JOIN or FULL JOIN for period comparisons — they produce duplicate column names that break charts
  - For metrics like CPC, CPM an increase is negative and decrease is positive. As we have to spend more for clicks and impressions. 
  - So, if CPC and CPM are increasing for a period as compared to last period it should be red. Only these two for now will show opposite trend.

 Response rules:
 - Use only numbers from query results — never hallucinate
 - <5% = stable/flat | 5-15% = slightly improved/softened | >15% = sharply increased/decreased
 - Never mention SQL, tables, or databases in your final answer
 - run_bq_query returns either "QUERY_SUCCESS" or "QUERY_FAILED" as the first word
 - If ANY call this request returned QUERY_SUCCESS, present those results — never tell the user it failed
 - If ALL calls returned QUERY_FAILED, report the error and suggest rephrasing
 - If the same question was successfully answered earlier in this conversation, use that data without re-querying
 - Always attempt a fresh query for every new request — never skip based on a past failure
 - If asked for a chart, add [CHART_REQUESTED] at the end of your response.
 - Only add the chart if asked or you feel it's required.

Metric formatting — use this EXACT structure for every metric line:
  **MetricName:** ↑/↓X% <span style="...">current_value vs previous_value</span>

Rules:
- The percentage change (↑X% or ↓X%) comes FIRST, before the span
- The span contains ONLY the two raw values: current vs previous
- Do NOT put any value or percentage outside/before the span in prose
- Do NOT use backtick or code formatting for numbers

Color for the span — choose based on metric AND direction:
- GOOD change → green span:
  <span style="background:#d4edda;color:#155724;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">current vs previous</span>
- BAD change → red span:
  <span style="background:#fde8e8;color:#c0392b;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">current vs previous</span>

Which metrics are GOOD when they increase (use green for ↑, red for ↓):
  Clicks, Impressions, CTR, Conversions, Conversion Rate, ROAS, Internal Link Clicks

Which metrics are BAD when they increase (use red for ↑, green for ↓):
  CPC, CPM, Cost, Spend, CPV

Concrete examples — each metric on its own bullet point:
- **Clicks:** ↑110% <span style="background:#d4edda;color:#155724;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">19,989 vs 9,528</span>
- **CPC:** ↑33% <span style="background:#fde8e8;color:#c0392b;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">5.75 vs 4.32</span>
- **Impressions:** ↑657% <span style="background:#d4edda;color:#155724;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">1,229,415 vs 162,450</span>
- **Cost:** ↑179% <span style="background:#fde8e8;color:#c0392b;padding:1px 8px;border-radius:4px;font-family:monospace;font-weight:600;">114,857 vs 41,154</span>

Always format the full response as a bulleted list — one metric per bullet. Never put multiple metrics on the same line.

"""


# ── Tools — plain Python functions, ADK auto-wraps these ──
def get_today_date() -> str:
    """
    Returns today's date as a string in YYYY-MM-DD format.
    Always call this before computing date ranges like 'last month',
    'last quarter', 'year to date', 'last 30 days', etc.
    """
    return str(date.today())


def get_schema() -> str:
    """
    Returns the schema and column descriptions for all available
    BigQuery tables. Call this when you need to understand what
    data is available before writing a SQL query.
    """
    lines = [f"Dataset: `{BQ_PROJECT}.{DATASET_ID}`\n"]
    for table_name, info in TABLE_DESCRIPTIONS.items():
        lines.append(f"Table: `{BQ_PROJECT}.{DATASET_ID}.{table_name}`")
        lines.append(f"  {info['description']}")
        lines.append(f"  Columns: {', '.join(info['key_columns'])}")
        if info["filter_note"]:
            lines.append(f"  Filter required: {info['filter_note']}")
        lines.append("")
    return "\n".join(lines)


def run_bq_query(sql: str) -> str:
    """
    Executes a BigQuery SQL query and returns the results as a
    formatted text table. Use this to fetch data needed to answer
    the user's question. Write complete, valid BigQuery Standard SQL
    with fully qualified table names.

    Args:
        sql: A complete, valid BigQuery Standard SQL query string.

    Returns:
        Query results as a pipe-separated text table, or an error message.
    """
    try:
        credentials, _ = google_auth_default()
        client  = bigquery.Client(
            project=BQ_BILLING_PROJECT,
            credentials=credentials,
        )
        t0      = time.time()
        df      = client.query(sql).result().to_dataframe(
            create_bqstorage_client=False
        )
        elapsed = time.time() - t0

        if df.empty:
            return "Query returned no results."

        # Round numerics, fill NAs
        num_cols = df.select_dtypes(include="number").columns
        df[num_cols] = df[num_cols].round(2).fillna(0)
        df = df.fillna("—")

        # Pipe-separated table (max 100 rows to LLM)
        display_df = df.head(100)
        col_widths = {
            col: max(len(str(col)), display_df[col].astype(str).str.len().max())
            for col in display_df.columns
        }
        header    = " | ".join(str(c).ljust(col_widths[c]) for c in display_df.columns)
        separator = "-+-".join("-" * col_widths[c] for c in display_df.columns)
        rows      = [
            " | ".join(
                str(v).ljust(col_widths[c])
                for c, v in zip(display_df.columns, row)
            )
            for row in display_df.itertuples(index=False)
        ]
        text = "\n".join([header, separator] + rows)
        if len(df) > 100:
            text += f"\n... ({len(df)} rows total, showing 100)"

        return f"QUERY_SUCCESS [{len(df)} rows in {elapsed:.1f}s]\n\n{text}"

    except Exception as e:
        print(f"BQ ERROR: {e}")
        return f"QUERY_FAILED: {str(e)}"


# ── ADK Agent definition ───────────────────────────────────
root_agent = Agent(
    name="brookfield_analyst",
    model=MODEL_NAME,
    description="Senior performance marketing analyst for Brookfield. Queries BigQuery and generates insights.",
    instruction=_build_instruction(),
    tools=[
        get_today_date,
        get_schema,
        run_bq_query,
    ],
)

# ── Session service — manages conversation history ─────────
session_service = InMemorySessionService()

# ── Runner — manages the agentic loop ──────────────────────
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


# ── Helper: sync wrapper for Streamlit ─────────────────────
def create_session(user_id: str, session_id: str):
    """Creates a new ADK session for a user."""
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
) -> dict:
    """
    Sends a message to the ADK agent and returns the response.

    Returns:
        {
          "text":       str,           final response text
          "tool_calls": list[str],     names of tools called
          "df":         DataFrame,     last BQ query result (for charts/tables)
          "sql":        str,           last SQL executed
          "chart":      bool,          True if LLM wants a chart rendered
        }
    """
    async def _run():
        content = types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        )

        final_text  = ""
        tool_calls  = []
        last_sql    = ""
        last_df     = None

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
                            if part.function_call.name == "run_bq_query":
                                args = dict(part.function_call.args or {})
                                last_sql = args.get("sql", "")
                    except Exception:
                        pass

            if event.is_final_response():
                try:
                    for part in event.content.parts:
                        if part.text:
                            final_text += part.text
                except Exception:
                    pass

        # Re-run the last SQL to get the DataFrame for display
        if last_sql:
            try:
                credentials, _ = google_auth_default()
                client  = bigquery.Client(
                    project=BQ_BILLING_PROJECT,
                    credentials=credentials,
                )
                last_df = client.query(last_sql).result().to_dataframe(
                    create_bqstorage_client=False
                )
                num_cols = last_df.select_dtypes(include="number").columns
                last_df[num_cols] = last_df[num_cols].round(4)
            except Exception:
                pass

        return final_text.strip(), tool_calls, last_df, last_sql

    final_text, tool_calls, last_df, last_sql = asyncio.run(_run())

    chart_requested = "[CHART_REQUESTED]" in final_text
    final_text      = final_text.replace("[CHART_REQUESTED]", "").strip()

    return {
        "text":       final_text,
        "tool_calls": tool_calls,
        "df":         last_df,
        "sql":        last_sql,
        "chart":      chart_requested,
    }
