# -*- coding: utf-8 -*-
"""
Brookfield Automated Insights
==============================
Refactored from Google Colab notebook.

Usage
-----
  # Run the full pipeline (queries BQ, calls Gemini, saves results to BQ)
  from insights.brookfield_automated_insights import run_insights_pipeline
  run_insights_pipeline()

  # Read stored insights for display in the dashboard
  from insights.brookfield_automated_insights import fetch_insights
  df = fetch_insights(comparison_type="MoM", channel="Search")

Auth
----
  Uses Application Default Credentials (ADC) — same as the chatbot agent.
  Locally: gcloud auth application-default login
  Cloud Run: attached service account

LLM
---
  Uses google.genai.Client() with GOOGLE_GENAI_USE_VERTEXAI=1 — same client
  as chatbot/charts.py. LangChain dependency removed.
"""

import os
import re
import time
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from google.auth import default as google_auth_default
from google.cloud import bigquery
from google import genai
from google.genai import types

# ── Tell genai to route through Vertex AI ────────────────────
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "generative-insights-poc-bi")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# ── CONFIG ───────────────────────────────────────────────────
BQ_Project         = "funnel-data"
BQ_Billing_Project = "funnel-data"
LLM_Project        = "generative-insights-poc-bi"

Dest_Project  = "funnel-data"
Dest_Dataset  = "brookfield_dashboard"
Dest_Table    = "Automated_insights"

MODEL_NAME      = "gemini-2.5-pro"
VERTEX_LOCATION = "us-central1"
DATASET_ID      = "brookfield_dashboard"

# ── Comparison types ─────────────────────────────────────────
RUN_MOM = True
RUN_QOQ = True
RUN_YOY = True

# ── Table references ─────────────────────────────────────────
social_table    = f"{BQ_Project}.{DATASET_ID}.Brookfield_1H_Social"
search_table    = f"{BQ_Project}.{DATASET_ID}.Brookfield_1H_Search"
display_table   = f"{BQ_Project}.{DATASET_ID}.Brookfield_1H_Programmatic"
executive_table = f"{BQ_Project}.{DATASET_ID}.Brookfield_1H_Executive_Summary_"


# ============================================================
# CLIENTS (lazy, authenticated via ADC)
# ============================================================

def _get_bq_client() -> bigquery.Client:
    """Returns an authenticated BigQuery client billed to BQ_Billing_Project."""
    credentials, _ = google_auth_default()
    return bigquery.Client(project=BQ_Billing_Project, credentials=credentials)


def _get_genai_client() -> genai.Client:
    """Returns a Gemini client routed through Vertex AI (reads env vars)."""
    return genai.Client()


# ============================================================
# DATE RANGES
# ============================================================

def compute_date_ranges() -> dict:
    """
    Computes MoM, QoQ, and YoY date ranges relative to today.
    All ranges use the last FULLY COMPLETED period (no partial periods).

    Returns
    -------
    dict keyed by "MoM" / "QoQ" / "YoY", each value containing:
        comparison_type, current_label, previous_label,
        current_start, current_end, previous_start, previous_end,
        current_start_str, current_end_str, previous_start_str, previous_end_str,
        description
    """
    today            = date.today()
    this_month_first = today.replace(day=1)

    # ── MoM ──────────────────────────────────────────────────
    mom_curr_end   = this_month_first - relativedelta(days=1)
    mom_curr_start = mom_curr_end.replace(day=1)
    mom_prev_end   = mom_curr_start - relativedelta(days=1)
    mom_prev_start = mom_prev_end.replace(day=1)

    mom = {
        "comparison_type":    "MoM",
        "current_label":      mom_curr_start.strftime("%b %Y"),
        "previous_label":     mom_prev_start.strftime("%b %Y"),
        "current_start":      mom_curr_start,
        "current_end":        mom_curr_end,
        "previous_start":     mom_prev_start,
        "previous_end":       mom_prev_end,
        "current_start_str":  str(mom_curr_start),
        "current_end_str":    str(mom_curr_end),
        "previous_start_str": str(mom_prev_start),
        "previous_end_str":   str(mom_prev_end),
        "description": (
            f"Month-over-Month: current={mom_curr_start} to {mom_curr_end} "
            f"({mom_curr_start.strftime('%b %Y')}), "
            f"previous={mom_prev_start} to {mom_prev_end} "
            f"({mom_prev_start.strftime('%b %Y')})."
        ),
    }

    # ── QoQ (fixed — removed the buggy partial if/elif block) ─
    # The original notebook had an incomplete if current_q==1 / elif current_q==2
    # block that set qoq_curr_start/end for Q1 and Q2 but then the code below
    # unconditionally recalculated qoq_curr_q, overwriting those values.
    # Fix: use only the unified calculation below for all quarters.
    current_month  = today.month
    current_q      = (current_month - 1) // 3 + 1

    qoq_curr_q     = current_q - 1 if current_q > 1 else 4
    qoq_curr_year  = today.year if current_q > 1 else today.year - 1
    qoq_curr_start = date(qoq_curr_year, (qoq_curr_q - 1) * 3 + 1, 1)
    qoq_curr_end   = qoq_curr_start + relativedelta(months=3) - relativedelta(days=1)

    qoq_prev_q     = qoq_curr_q - 1 if qoq_curr_q > 1 else 4
    qoq_prev_year  = qoq_curr_year if qoq_curr_q > 1 else qoq_curr_year - 1
    qoq_prev_start = date(qoq_prev_year, (qoq_prev_q - 1) * 3 + 1, 1)
    qoq_prev_end   = qoq_prev_start + relativedelta(months=3) - relativedelta(days=1)

    qoq = {
        "comparison_type":    "QoQ",
        "current_label":      f"Q{qoq_curr_q} {qoq_curr_year}",
        "previous_label":     f"Q{qoq_prev_q} {qoq_prev_year}",
        "current_start":      qoq_curr_start,
        "current_end":        qoq_curr_end,
        "previous_start":     qoq_prev_start,
        "previous_end":       qoq_prev_end,
        "current_start_str":  str(qoq_curr_start),
        "current_end_str":    str(qoq_curr_end),
        "previous_start_str": str(qoq_prev_start),
        "previous_end_str":   str(qoq_prev_end),
        "description": (
            f"Quarter-over-Quarter: current=Q{qoq_curr_q} {qoq_curr_year} "
            f"({qoq_curr_start} to {qoq_curr_end}), "
            f"previous=Q{qoq_prev_q} {qoq_prev_year} "
            f"({qoq_prev_start} to {qoq_prev_end})."
        ),
    }

    # ── YoY ──────────────────────────────────────────────────
    yoy_curr_start = mom_curr_start
    yoy_curr_end   = mom_curr_end
    yoy_prev_start = yoy_curr_start - relativedelta(years=1)
    yoy_prev_end   = yoy_curr_end   - relativedelta(years=1)

    yoy = {
        "comparison_type":    "YoY",
        "current_label":      yoy_curr_start.strftime("%b %Y"),
        "previous_label":     yoy_prev_start.strftime("%b %Y"),
        "current_start":      yoy_curr_start,
        "current_end":        yoy_curr_end,
        "previous_start":     yoy_prev_start,
        "previous_end":       yoy_prev_end,
        "current_start_str":  str(yoy_curr_start),
        "current_end_str":    str(yoy_curr_end),
        "previous_start_str": str(yoy_prev_start),
        "previous_end_str":   str(yoy_prev_end),
        "description": (
            f"Year-over-Year: current={yoy_curr_start} to {yoy_curr_end} "
            f"({yoy_curr_start.strftime('%b %Y')}), "
            f"previous={yoy_prev_start} to {yoy_prev_end} "
            f"({yoy_prev_start.strftime('%b %Y')})."
        ),
    }

    return {"MoM": mom, "QoQ": qoq, "YoY": yoy}


# ============================================================
# SCHEMA DISCOVERY
# ============================================================

def get_dataset_schema(bq_project: str, dataset_id: str, bq_billing_project: str) -> dict:
    """Auto-discovers all tables and columns in a BigQuery dataset."""
    credentials, _ = google_auth_default()
    client      = bigquery.Client(project=bq_billing_project, credentials=credentials)
    dataset_ref = client.dataset(dataset_id, project=bq_project)
    tables      = list(client.list_tables(dataset_ref))

    schema_info = {}
    for table_item in tables:
        table_ref = client.get_table(table_item.reference)
        schema_info[table_item.table_id] = {
            "description": table_ref.description or "",
            "columns": [
                {
                    "name":        f.name,
                    "type":        f.field_type,
                    "mode":        f.mode,
                    "description": f.description or "",
                }
                for f in table_ref.schema
            ],
        }
    return schema_info


def schema_to_prompt_text(schema: dict, bq_project: str, dataset_id: str) -> str:
    """Formats a schema dict as a compact string for LLM prompt injection."""
    lines = [f"BigQuery Dataset: `{bq_project}.{dataset_id}`", "Available tables:\n"]
    for table_name, info in schema.items():
        full_name = f"`{bq_project}.{dataset_id}.{table_name}`"
        lines.append(f"Table: {full_name}")
        if info["description"]:
            lines.append(f"  Description: {info['description']}")
        lines.append("  Columns:")
        for col in info["columns"]:
            desc = f" -- {col['description']}" if col["description"] else ""
            lines.append(f"    - {col['name']} ({col['type']}, {col['mode']}){desc}")
        lines.append("")
    return "\n".join(lines)


# ============================================================
# SQL BUILDERS
# ============================================================

def social_sql_builder(current_start, current_end, previous_start, previous_end) -> dict:
    """Returns named SQL queries for the Social channel (Meta, LinkedIn)."""
    sql = f"""
  with curr as (
    select
    Campaign_New,
    Tactic,
    Strategy_Type_Social,
    Asset_Type_Social,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
    from `{social_table}`
    where Date between '{current_start}' and '{current_end}'
    and Data_Source_name in ('Brookfield Brand Campaign - Standard','Brookfield - Ad Account - Campaign')
    group by 1,2,3,4
  ),
  prev as (
    select
    Campaign_New,
    Tactic,
    Strategy_Type_Social,
    Asset_Type_Social,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
    from `{social_table}`
    where Date between '{previous_start}' and '{previous_end}'
    and Data_Source_name in ('Brookfield Brand Campaign - Standard','Brookfield - Ad Account - Campaign')
    group by 1,2,3,4
  )
  SELECT
      COALESCE(curr.Campaign_New, prev.Campaign_New) AS Campaign_New,
      COALESCE(curr.Tactic,       prev.Tactic)       AS Tactic,
      COALESCE(curr.Strategy_Type_Social, prev.Strategy_Type_Social) AS Strategy_Type_Social,
      COALESCE(curr.Asset_Type_Social, prev.Asset_Type_Social) AS Asset_Type_Social,
      ifnull(curr.Cost,0)        AS current_cost,
      ifnull(prev.Cost,0)        AS previous_cost,
      ifnull(curr.Clicks,0)      AS current_clicks,
      ifnull(prev.Clicks,0)      AS previous_clicks,
      ifnull(curr.Impressions,0) AS current_impressions,
      ifnull(prev.Impressions,0) AS previous_impressions,
      ifnull(curr.cpc,0)         AS current_cpc,
      ifnull(prev.cpc,0)         AS previous_cpc,
      ifnull(curr.ctr,0)         AS current_ctr,
      ifnull(prev.ctr,0)         AS previous_ctr,
      ifnull(curr.cpm,0)         AS current_cpm,
      ifnull(prev.cpm,0)         AS previous_cpm
  FROM curr
  FULL JOIN prev
      ON  curr.Campaign_New         = prev.Campaign_New
      AND curr.Tactic               = prev.Tactic
      AND curr.Strategy_Type_Social = prev.Strategy_Type_Social
      AND curr.Asset_Type_Social    = prev.Asset_Type_Social
    """
    return {"social_performance": sql}


def search_sql_builder(current_start, current_end, previous_start, previous_end) -> dict:
    """Returns named SQL queries for the Search channel (Google Ads, Bing)."""

    # Query 1 — Aggregated summary by Campaign/Tactic (drives all insight numbers)
    summary_sql = f"""
      with curr as (
        select
        Campaign_New,
        Tactic,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
        from `{search_table}`
        where Date between '{current_start}' and '{current_end}'
        and Data_Source_name in ('2026 - Corporate Brand Campaign - Keyword','Brookfield Brand Campaign - Search keyword')
        group by 1,2
      ),
      prev as (
        select
        Campaign_New,
        Tactic,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
        from `{search_table}`
        where Date between '{previous_start}' and '{previous_end}'
        and Data_Source_name in ('2026 - Corporate Brand Campaign - Keyword','Brookfield Brand Campaign - Search keyword')
        group by 1,2
      )
      select
        coalesce(curr.Campaign_New,prev.Campaign_New) as Campaign_New,
        coalesce(curr.Tactic,prev.Tactic) as Tactic,
        ifnull(curr.Cost,0)        AS current_cost,
        ifnull(prev.Cost,0)        AS previous_cost,
        ifnull(curr.Clicks,0)      AS current_clicks,
        ifnull(prev.Clicks,0)      AS previous_clicks,
        ifnull(curr.Impressions,0) AS current_impressions,
        ifnull(prev.Impressions,0) AS previous_impressions,
        ifnull(curr.cpc,0)         AS current_cpc,
        ifnull(prev.cpc,0)         AS previous_cpc,
        ifnull(curr.ctr,0)         AS current_ctr,
        ifnull(prev.ctr,0)         AS previous_ctr,
        ifnull(curr.cpm,0)         AS current_cpm,
        ifnull(prev.cpm,0)         AS previous_cpm
      from curr
      full join prev
        on  curr.Campaign_New = prev.Campaign_New
        and curr.Tactic       = prev.Tactic
    """

    # Query 2 — Top 10 keywords by Internal Link Clicks (narrative context)
    top_keywords_sql = f"""
      with curr as (
        SELECT
        Tactic,
        Keyword_Search,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
        sum(ifnull(Internal_Link_Clicks,0)) as Internal_Link_Clicks
        FROM `{search_table}`
        WHERE Date BETWEEN '{current_start}' AND '{current_end}'
        GROUP BY 1,2
      ),
      prev as (
        SELECT
        Tactic,
        Keyword_Search,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
        sum(ifnull(Internal_Link_Clicks,0)) as Internal_Link_Clicks
        FROM `{search_table}`
        WHERE Date BETWEEN '{previous_start}' AND '{previous_end}'
        GROUP BY 1,2
      ),
      joined as (
        select
        coalesce(curr.Tactic,prev.Tactic) as Tactic,
        coalesce(curr.Keyword_Search,prev.Keyword_Search) as Keyword_Search,
        ifnull(curr.Cost,0)                     AS current_cost,
        ifnull(prev.Cost,0)                     AS previous_cost,
        ifnull(curr.Clicks,0)                   AS current_clicks,
        ifnull(prev.Clicks,0)                   AS previous_clicks,
        ifnull(curr.Impressions,0)              AS current_impressions,
        ifnull(prev.Impressions,0)              AS previous_impressions,
        ifnull(curr.cpc,0)                      AS current_cpc,
        ifnull(prev.cpc,0)                      AS previous_cpc,
        ifnull(curr.ctr,0)                      AS current_ctr,
        ifnull(prev.ctr,0)                      AS previous_ctr,
        ifnull(curr.cpm,0)                      AS current_cpm,
        ifnull(prev.cpm,0)                      AS previous_cpm,
        ifnull(curr.Internal_Link_Clicks,0)     AS current_internal_link_clicks,
        ifnull(prev.Internal_Link_Clicks,0)     AS previous_internal_link_clicks
        from curr
        full join prev
          on curr.Tactic         = prev.Tactic
          and curr.Keyword_Search = prev.Keyword_Search
      )
      SELECT *
      FROM joined
      where Keyword_Search is not null or Keyword_Search <> 'None'
      ORDER BY current_internal_link_clicks DESC
      LIMIT 10
    """

    # Query 3 — Bottom 10 keywords by Internal Link Clicks
    bottom_keywords_sql = f"""
      with curr as (
        SELECT
        Tactic,
        Keyword_Search,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
        sum(ifnull(Internal_Link_Clicks,0)) as Internal_Link_Clicks
        FROM `{search_table}`
        WHERE Date BETWEEN '{current_start}' AND '{current_end}'
        GROUP BY 1,2
      ),
      prev as (
        SELECT
        Tactic,
        Keyword_Search,
        sum(ifnull(Cost,0)) as Cost,
        sum(ifnull(Clicks,0)) as Clicks,
        sum(ifnull(Impressions,0)) as Impressions,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
        SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
        SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
        sum(ifnull(Internal_Link_Clicks,0)) as Internal_Link_Clicks
        FROM `{search_table}`
        WHERE Date BETWEEN '{previous_start}' AND '{previous_end}'
        GROUP BY 1,2
      ),
      joined as (
        select
        coalesce(curr.Tactic,prev.Tactic) as Tactic,
        coalesce(curr.Keyword_Search,prev.Keyword_Search) as Keyword_Search,
        ifnull(curr.Cost,0)                     AS current_cost,
        ifnull(prev.Cost,0)                     AS previous_cost,
        ifnull(curr.Clicks,0)                   AS current_clicks,
        ifnull(prev.Clicks,0)                   AS previous_clicks,
        ifnull(curr.Impressions,0)              AS current_impressions,
        ifnull(prev.Impressions,0)              AS previous_impressions,
        ifnull(curr.cpc,0)                      AS current_cpc,
        ifnull(prev.cpc,0)                      AS previous_cpc,
        ifnull(curr.ctr,0)                      AS current_ctr,
        ifnull(prev.ctr,0)                      AS previous_ctr,
        ifnull(curr.cpm,0)                      AS current_cpm,
        ifnull(prev.cpm,0)                      AS previous_cpm,
        ifnull(curr.Internal_Link_Clicks,0)     AS current_internal_link_clicks,
        ifnull(prev.Internal_Link_Clicks,0)     AS previous_internal_link_clicks
        from curr
        full join prev
          on curr.Tactic         = prev.Tactic
          and curr.Keyword_Search = prev.Keyword_Search
      )
      SELECT *
      FROM joined
      where Keyword_Search is not null or Keyword_Search <> 'None'
      ORDER BY current_internal_link_clicks ASC
      LIMIT 10
    """

    return {
        "search_performance": summary_sql,
        "top_keywords":       top_keywords_sql,
        "bottom_keywords":    bottom_keywords_sql,
    }


def programmatic_sql_builder(current_start, current_end, previous_start, previous_end) -> dict:
    """Returns named SQL queries for the Programmatic channel (DV360)."""
    sql = f"""
  with curr as (
    select
    Channels_DV360 as Ad_Channel,
    Audience_Type_DV360_ as Audience_type,
    case
        when Line_Item__Display__Video_360 ="1207359_DISNEY SPORTS | Digital | US | All Sports | PG | Video | PG | TWC | Brainlabs | 1P Tar-Group 1 | :15s | 4.1.25-4.30.25" then "Brookfield Line Item"
        when Line_Item__Display__Video_360 ="1207366_DISNEY SPORTS | Digital | US | All Sports | PG | Video | PG | TWC | Brainlabs | 1P Tar-Group 2 | :15s | 4.1.25-4.30.25" then "Brookfield Line Item 1"
        when Line_Item__Display__Video_360 ="DSE-7498953-PG-GL-TWC-PRODUCT-AND-TECHNOLOGY--LL" then "Brookfield Line Item 2"
        when Line_Item__Display__Video_360 ="DSE-7498951-PG-GL-TWC-PRODUCT-AND-TECHNOLOGY--LL" then "Brookfield Line Item 3"
        else "Brookfield Line Item BL"
      end as Line_Item,
    case
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Empaths_DSE_CTV_NonSkip_15s_VAST_Brand_v03" then "Brookfield Creative"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Optimists_DSE_CTV_NonSkip_15s_VAST_Brand_v02" then "Brookfield Creative 1"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Optimists_DSE_CTV_NonSkip_15s_VAST_Brand_v03" then "Brookfield Creative 2"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Empaths_DSE_CTV_NonSkip_15s_VAST_Brand_v01" then "Brookfield Creative 3"
        else "Brookfield Creative BL"
      end as Creative,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    sum(ifnull(Video_Completed_Views__Display__Video_360,0)) as Completed_Views,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
    SAFE_DIVIDE(SUM(Cost),NULLIF(SUM(Video_Completed_Views__Display__Video_360),0)) CPV
    from `{display_table}`
    where Date between '{current_start}' and '{current_end}'
    and Data_Source='doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'
    group by 1,2,3,4
  ),
  prev as (
    select
    Channels_DV360 as Ad_Channel,
    Audience_Type_DV360_ as Audience_type,
    case
        when Line_Item__Display__Video_360 ="1207359_DISNEY SPORTS | Digital | US | All Sports | PG | Video | PG | TWC | Brainlabs | 1P Tar-Group 1 | :15s | 4.1.25-4.30.25" then "Brookfield Line Item"
        when Line_Item__Display__Video_360 ="1207366_DISNEY SPORTS | Digital | US | All Sports | PG | Video | PG | TWC | Brainlabs | 1P Tar-Group 2 | :15s | 4.1.25-4.30.25" then "Brookfield Line Item 1"
        when Line_Item__Display__Video_360 ="DSE-7498953-PG-GL-TWC-PRODUCT-AND-TECHNOLOGY--LL" then "Brookfield Line Item 2"
        when Line_Item__Display__Video_360 ="DSE-7498951-PG-GL-TWC-PRODUCT-AND-TECHNOLOGY--LL" then "Brookfield Line Item 3"
        else "Brookfield Line Item BL"
      end as Line_Item,
    case
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Empaths_DSE_CTV_NonSkip_15s_VAST_Brand_v03" then "Brookfield Creative"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Optimists_DSE_CTV_NonSkip_15s_VAST_Brand_v02" then "Brookfield Creative 1"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Optimists_DSE_CTV_NonSkip_15s_VAST_Brand_v03" then "Brookfield Creative 2"
        when Creative__Display__Video_360 ="2025_TWC_BrandPreference_TOFMOF_Prog_Disney_Video_Consideration_US_Empaths_DSE_CTV_NonSkip_15s_VAST_Brand_v01" then "Brookfield Creative 3"
        else "Brookfield Creative BL"
      end as Creative,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    sum(ifnull(Video_Completed_Views__Display__Video_360,0)) as Completed_Views,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm,
    SAFE_DIVIDE(SUM(Cost),NULLIF(SUM(Video_Completed_Views__Display__Video_360),0)) CPV
    from `{display_table}`
    where Date between '{previous_start}' and '{previous_end}'
    and Data_Source='doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'
    group by 1,2,3,4
  )
  SELECT
      COALESCE(curr.Ad_Channel,    prev.Ad_Channel)    AS Ad_Channel,
      COALESCE(curr.Audience_type, prev.Audience_type) AS Audience_type,
      COALESCE(curr.Line_Item,     prev.Line_Item)     AS Line_Item,
      COALESCE(curr.Creative,      prev.Creative)      AS Creative,
      ifnull(curr.Cost,0)              AS current_cost,
      ifnull(prev.Cost,0)              AS previous_cost,
      ifnull(curr.Clicks,0)            AS current_clicks,
      ifnull(prev.Clicks,0)            AS previous_clicks,
      ifnull(curr.Impressions,0)       AS current_impressions,
      ifnull(prev.Impressions,0)       AS previous_impressions,
      ifnull(curr.Completed_Views,0)   AS current_completed_views,
      ifnull(prev.Completed_Views,0)   AS previous_completed_views,
      ifnull(curr.cpc,0)               AS current_cpc,
      ifnull(prev.cpc,0)               AS previous_cpc,
      ifnull(curr.ctr,0)               AS current_ctr,
      ifnull(prev.ctr,0)               AS previous_ctr,
      ifnull(curr.cpm,0)               AS current_cpm,
      ifnull(prev.cpm,0)               AS previous_cpm,
      ifnull(curr.CPV,0)               AS current_CPV,
      ifnull(prev.CPV,0)               AS previous_CPV
  FROM curr
  FULL JOIN prev
      ON curr.Ad_Channel    = prev.Ad_Channel
      AND curr.Audience_type = prev.Audience_type
      AND curr.Line_Item     = prev.Line_Item
      AND curr.Creative      = prev.Creative
    """
    return {"programmatic_performance": sql}


def executive_sql_builder(current_start, current_end, previous_start, previous_end) -> dict:
    """Returns named SQL queries for the Executive Summary (all channels combined)."""
    sql = f"""
  with curr as (
    select
    Channel,
    Campaign_New,
    Tactic,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
    from `{executive_table}`
    where Date between '{current_start}' and '{current_end}'
    and Channel in ('Search','Social')
    group by 1,2,3
  ),
  prev as (
    select
    Channel,
    Campaign_New,
    Tactic,
    sum(ifnull(Cost,0)) as Cost,
    sum(ifnull(Clicks,0)) as Clicks,
    sum(ifnull(Impressions,0)) as Impressions,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(Clicks),0)) cpc,
    SAFE_DIVIDE(SUM(Clicks), NULLIF(SUM(Impressions),0)) ctr,
    SAFE_DIVIDE(SUM(Cost), NULLIF(SUM(impressions),0))*1000 cpm
    from `{executive_table}`
    where Date between '{previous_start}' and '{previous_end}'
    and Channel in ('Search','Social')
    group by 1,2,3
  )
  SELECT
      COALESCE(curr.Channel,      prev.Channel)      AS Channel,
      COALESCE(curr.Campaign_New, prev.Campaign_New) AS Campaign_New,
      COALESCE(curr.Tactic,       prev.Tactic)       AS Tactic,
      ifnull(curr.Cost,0)        AS current_cost,
      ifnull(prev.Cost,0)        AS previous_cost,
      ifnull(curr.Clicks,0)      AS current_clicks,
      ifnull(prev.Clicks,0)      AS previous_clicks,
      ifnull(curr.Impressions,0) AS current_impressions,
      ifnull(prev.Impressions,0) AS previous_impressions,
      ifnull(curr.cpc,0)         AS current_cpc,
      ifnull(prev.cpc,0)         AS previous_cpc,
      ifnull(curr.ctr,0)         AS current_ctr,
      ifnull(prev.ctr,0)         AS previous_ctr,
      ifnull(curr.cpm,0)         AS current_cpm,
      ifnull(prev.cpm,0)         AS previous_cpm
  FROM curr
  FULL JOIN prev
      ON curr.Channel      = prev.Channel
      AND curr.Campaign_New = prev.Campaign_New
      AND curr.Tactic       = prev.Tactic
    """
    return {"executive_performance": sql}


# ── Channel → SQL builder registry ───────────────────────────
CHANNEL_QUERY_REGISTRY = {
    "Search":        search_sql_builder,
    "Social":        social_sql_builder,
    "programmatic":  programmatic_sql_builder,
    "executive":     executive_sql_builder,
}


# ============================================================
# BQ QUERY RUNNER
# ============================================================

def run_bq_query(sql: str, query_name: str = "Query", max_rows: int = 500) -> tuple:
    """
    Executes SQL on BigQuery.
    Billed to BQ_Billing_Project; reads from BQ_Project tables.

    Returns
    -------
    (text_for_llm: str, full_dataframe: pd.DataFrame)
    """
    client  = _get_bq_client()
    t0      = time.time()
    df      = client.query(sql).result().to_dataframe(create_bqstorage_client=False)
    elapsed = time.time() - t0

    print(f"      [{query_name}] {len(df)} rows in {elapsed:.1f}s")

    if df.empty:
        return "Query returned no results.", df

    display_df = df.head(max_rows)
    text       = display_df.round(2).to_string(index=False)
    if len(df) > max_rows:
        text += f"\n... (showing {max_rows} of {len(df)} rows)"

    return text, df


# ============================================================
# PROMPTS
# ============================================================

BASE_PROMPT = """You are a senior performance marketing analyst writing a weekly insight report.
You will receive query results for a channel covering a specific comparison period.
The metrics marked as current represent the latest period data and the metrics marked with
previous are last period data. Use the current_ and previous_ metric prefix for the same
metrics to compare the numbers.

Output format - try to give concise insights in 3-5 lines or prose paragraphs:
- Show the section name at the start of the insights like Social, Search, Programmatic, Executive_Summary
- Use "↑" for increases and "↓" for decreases
- Always show % change AND absolute values in brackets, e.g.: Cost: ↓35% ($3,520 vs $5,431)
- Nest sub-bullets for explanations, causes, or breakdowns
- Group metrics logically (cost first, then volume metrics, then efficiency metrics)
- End every channel block with a "Suggestions" section as a bulleted list
- Don't include * or m hash or random spaces or long dash in the output. Keep it clean and properly formatted.
- if needed replace * with bullet filled and empty symbol.
- Add a blank line between every top-level section (Brand, NonBrand, Suggestions).
- Add a blank line between the metrics block and the Insights block within each section.
- When you don't have the context for the past period data or if it's missing don't assume that the activity started from the current period only.

INSTRUCTIONS:
- STABILITY THRESHOLDS:
    - If a metric changed < 5%: Describe it as "stable" or "flat".
    - If a metric changed 5-15%: Describe it as "slightly improved/softened".
    - Only use "Surged" or "Dropped" for large shifts (>15%).
- Focus on Traffic Quality: "High impressions but lower clicks" -> "Lower quality traffic".

Rules:
- Never mention SQL, tables, databases, or technical implementation
- Never use filler phrases like "the data shows" or "it can be seen that"
- Calculate % change yourself if not already in the results. But if it's present in the result please use it.
- Be specific when giving the insights, use actual percentage change and numbers. Don't give vague numbers.
- When you aggregate the number always make sure to do correct calculation.
- Always use the numbers you received from the query. Don't imagine/add/hallucinate.
- When you receive multiple rows of data and you have to do aggregation for the overall value for the metric please stick with the data present and don't add anything from your side.
- Double check the number you calculated.
- Be consistent with the data points and don't imagine or add data numbers.
- When giving the insights don't say the activity started or activity is new because you don't have context apart from the date we are giving you the data for"""

CHANNEL_PROMPTS = {
    "executive": """
    Channel context - Executive:
    - Key metrics to cover: Impressions, Clicks, CTR, Cost, CPC, CPM
    - Highlight any Channel-level anomalies if present in the data.
    - Overall performance change
      * Cost: ↓/↑X% ($current vs $previous)
      * Impr.: ↓/↑X% (current vs previous)
      * Clicks: ↓/↑X% (current vs previous)
      * CTR: ↓/↑X% (X% vs X%)
      * CPC: ↓/↑X% ($X vs $X)
    - Try to break some insights for channel level details with 2nd level of granularities like Brand/Non-Brand for search and other values for other channels.
    - See if there is some pattern for channel and campaign_new columns that is worth noting.
    - This is an executive level insights for all the platforms.

    Rule: The detailed channel level insights will be covered in the individual section.
    Give One blank line for formatting between sections, paragraphs to keep it clean.
    """,

    "Search": """Channel context — Search (SEM):
IMPORTANT — Three result sets are provided, use them as follows:
- TACTIC_SUMMARY: Use ONLY this for all cost, clicks, impressions, CTR, CPC figures — numbers are pre-summed, use as-is, never re-sum
- TOP_KEYWORDS: Use for narrative context — which keywords drove the best Internal Link Clicks for both tactics like brand and non brand.
- BOTTOM_KEYWORDS: Use for narrative context — which keywords underperformed on Internal Link Clicks for both tactics like brand and non brand.

- Split insights by Brand vs NonBrand where data allows
- Key metrics to cover for search performance: Impressions, Clicks, CTR, Cost, CPC, Impressions
- when we talk about keywords table include Internal_Link_Clicks as well.
- Highlight any keyword-level anomalies if present in the data
- Note auction dynamics (competitors entering/exiting) if visible
- Next Steps should include: keyword optimisations, budget pacing notes, audience or match-type opportunities

Output structure — follow this exact hierarchy:

* Brand
   * Cost: ↓/↑X% ($current vs $previous)
   * Impr.: ↓/↑X% (current vs previous)
   * Clicks: ↓/↑X% (current vs previous)
   * CTR: ↓/↑X% (X% vs X%)
   * CPC: ↓/↑X% ($X vs $X)

   * Insights
      * [What drove the change in spend/budget]
      * [Impact on impression and click volume]
      * [Any auction dynamics — competitors, keyword conflicts, query matching issues]
         * [Sub-bullet for specific keyword examples if present in data]

* NonBrand
   * Cost: ↓/↑X% ($current vs $previous)
   * Impr.: ↓/↑X% (current vs previous)
   * Clicks: ↓/↑X% (current vs previous)
   * CTR: ↓/↑X% (X% vs X%)
   * CPC: ↓/↑X ($X vs $X)

   * Insights
      * [What drove spend/volume changes]
      * [Which segments or tactics drove incremental performance]
         * [Sub-bullet per segment with metric if data allows]
      * [Top performing or anomalous keywords/queries if present]""",

    "Social": """Channel context — Social (Meta, LinkedIn):
- Dimensions like Tactic, Campaign_New, Strategy_Type_Social, Asset_Type_Social are present which have values
  related to the audience.
- Key metrics to cover: Cost, Impressions, CTR, CPM, Clicks, CPC
- Distinguish between Static and Video creative performance where data allows
- Include a "Creative Insights" sub-section covering:
    - Which creative formats or variants are outperforming
    - Recommendations for creative rotation or new assets""",

    "programmatic": """Channel context — Programmatic / Display:
Data granularity available:
  IO (Insertion Order) level — top-level budget and campaign grouping
  Line Item level — targeting, bid strategy, and audience segments
  Creative level — individual ad units

Ad_types present in the data:
  YouTube or YT — video ads served on YouTube
  CTV (Connected TV) — video ads served on streaming platforms
  Audio — audio ads (no visual creative, no CTR)
  OLV — programmatic video across open web

Key metrics by format:
  All formats:      Cost, Impressions, CPM
  YouTube/CTV/OLV:  Clicks, CTR, CPC, Completed Views, CPV
  Audio:            Completed Views, CPV only — never report CTR or Clicks for audio
  Display (if any): Cost, Impressions, Clicks, CTR, CPM, CPC

Output structure:

Ad_type Level Summary (split by format)

**YouTube**
Cost: ↓/↑X% ($current vs $previous)
Impressions: ↓/↑X% (current vs previous)
Completed Views: ↓/↑X% (current vs previous)
CPV: ↓/↑X% ($X vs $X)
CTR: ↓/↑X% (X% vs X%)

**CTV**
Cost: ↓/↑X% ($current vs $previous)
Impressions: ↓/↑X% (current vs previous)
Completed Views: ↓/↑X% (current vs previous)
CPV: ↓/↑X% ($X vs $X)

**Audio**
Cost: ↓/↑X% ($current vs $previous)
Impressions: ↓/↑X% (current vs previous)
Completed Views: ↓/↑X% (current vs previous)
Note: CTR and CPV not reported for Audio format

**OLV (open web)**
Cost: ↓/↑X% ($current vs $previous)
Impressions: ↓/↑X% (current vs previous)
Completed Views: ↓/↑X% (current vs previous)
CPV: ↓/↑X% ($X vs $X)
CTR: ↓/↑X% (X% vs X%)

**Audience_Type performance**
Analyse the audience_type and show the performance.

**Line Item Performance**
Top 3-5 performing line items by Completed Views or CTR (exclude Audio from CTR ranking)

**Creative Performance**
Top performing creatives per format

**Next Steps**
Budget reallocation recommendations across formats
Line item bid or targeting optimisations
Creative rotation recommendations per format

Rules specific to Programmatic:
- Always identify the IO format first (YouTube/CTV/Audio/Video) before reporting metrics
- NEVER report CTR, CPV, video_Completions or Clicks for Audio IOs
- Only report CPV and Completed Views when Completed_Views data is present and > 0
- Quote IO names and Line Item names exactly as they appear in the data
- Flag any line item with zero completed views but significant spend as priority review""",
}


# ============================================================
# LLM INSIGHT GENERATION (google.genai — no LangChain)
# ============================================================

def _run_insight_prompt(
    channel: str,
    comparison_type: str,
    date_context: str,
    query_results: str,
) -> str:
    """
    Sends one prompt to Gemini via Vertex AI and returns the insight text.
    Replaces the LangChain chain.invoke() call.
    """
    client = _get_genai_client()

    channel_context = CHANNEL_PROMPTS.get(
        channel,
        "No specific channel context defined — apply general performance marketing best practices.",
    )
    system_instruction = BASE_PROMPT + "\n\n" + channel_context

    user_message = (
        f"Channel:         {channel}\n"
        f"Comparison type: {comparison_type}\n"
        f"Period:          {date_context}\n\n"
        f"Query results (all metrics):\n{query_results}\n\n"
        f"Write the full insight block for this channel and period."
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.8,
        ),
    )
    return response.text or ""


# ============================================================
# DESTINATION TABLE
# ============================================================

DEST_TABLE_SCHEMA = [
    bigquery.SchemaField("run_date",          "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("run_timestamp",     "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("channel",           "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("comparison_type",   "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("current_label",     "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("previous_label",    "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("current_start",     "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("current_end",       "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("previous_start",    "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("previous_end",      "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("query_results_raw", "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("insight",           "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("model_name",        "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("bq_source",         "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("generated_sql",     "STRING",    mode="NULLABLE"),
]


def _ensure_dest_table_exists(client: bigquery.Client):
    dataset_ref          = bigquery.Dataset(f"{Dest_Project}.{Dest_Dataset}")
    dataset_ref.location = "US"
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        client.create_dataset(dataset_ref, exists_ok=True)
        print(f"  Created dataset: {Dest_Project}.{Dest_Dataset}")

    table_id = f"{Dest_Project}.{Dest_Dataset}.{Dest_Table}"
    try:
        client.get_table(table_id)
    except Exception:
        client.create_table(bigquery.Table(table_id, schema=DEST_TABLE_SCHEMA))
        print(f"  Created table: {table_id}")


def _append_rows(client: bigquery.Client, rows: list):
    table_id = f"{Dest_Project}.{Dest_Dataset}.{Dest_Table}"
    errors   = client.insert_rows_json(table_id, rows)
    if errors:
        print(f"  BQ insert errors: {errors}")
    else:
        print(f"  {len(rows)} row(s) saved → {table_id}")


# ============================================================
# CORE PIPELINE RUNNER — one channel × one period
# ============================================================

def _run_channel_for_period(
    channel: str,
    date_range: dict,
    bq_client: bigquery.Client,
) -> dict:
    """
    Runs all SQL queries for one channel × one comparison period,
    then generates ONE combined insight block via a single Gemini call.

    Returns one dict matching DEST_TABLE_SCHEMA (plus private _-prefixed keys).
    """
    run_ts    = pd.Timestamp.utcnow()
    comp_type = date_range["comparison_type"]
    query_fn  = CHANNEL_QUERY_REGISTRY[channel]

    queries = query_fn(
        current_start  = date_range["current_start_str"],
        current_end    = date_range["current_end_str"],
        previous_start = date_range["previous_start_str"],
        previous_end   = date_range["previous_end_str"],
    )

    all_metric_texts = []
    all_dfs          = {}
    all_sqls         = {}

    for metric, sql in queries.items():
        print(f"  [{channel.upper()} | {comp_type} | {metric}]")
        try:
            results_text, df = run_bq_query(sql, query_name=metric)
        except Exception as e:
            print(f"  Query failed: {e}")
            results_text = f"[{metric} query failed: {e}]"
            df = pd.DataFrame()

        all_metric_texts.append(f"--- {metric.upper()} ---\n{results_text}")
        all_dfs[metric]  = df
        all_sqls[metric] = sql.strip()

    combined_results = "\n\n".join(all_metric_texts)

    print(f"  Generating insight via Vertex AI [{LLM_Project}]")
    insight = _run_insight_prompt(
        channel         = channel,
        comparison_type = comp_type,
        date_context    = date_range["description"],
        query_results   = combined_results,
    )

    # Light cleanup — remove markdown bold/headers, preserve bullets
    insight = re.sub(r"\*{2,}([^*]+)\*{2,}", r"\1", insight)
    insight = re.sub(r"#{1,6}\s?", "", insight)
    insight = re.sub(r"\n(\* (?:Brand|NonBrand|Next Steps|Suggestions|Creative))", r"\n\n\1", insight)
    insight = insight.strip()

    print(f"  Insight generated ({len(insight)} chars)")

    return {
        "run_date":          str(run_ts.date()),
        "run_timestamp":     run_ts.isoformat(),
        "channel":           channel,
        "comparison_type":   comp_type,
        "current_label":     date_range["current_label"],
        "previous_label":    date_range["previous_label"],
        "current_start":     str(date_range["current_start"]),
        "current_end":       str(date_range["current_end"]),
        "previous_start":    str(date_range["previous_start"]),
        "previous_end":      str(date_range["previous_end"]),
        "query_results_raw": combined_results[:10000],
        "insight":           insight,
        "model_name":        MODEL_NAME,
        "bq_source":         f"{BQ_Project}.{DATASET_ID}",
        "generated_sql":     "\n\n--- NEXT QUERY ---\n\n".join(
            f"-- {m}\n{s}" for m, s in all_sqls.items()
        ),
        # Private keys — stripped before BQ insert
        "_run_ts":      run_ts,
        "_dfs":         all_dfs,
        "_sqls":        all_sqls,
        "_total_rows":  sum(len(d) for d in all_dfs.values()),
    }


# ============================================================
# PUBLIC API — PIPELINE
# ============================================================

def run_insights_pipeline(
    channels: list = None,
    comparison_types: list = None,
) -> list:
    """
    Run the full insights pipeline.

    Parameters
    ----------
    channels : list, optional
        Subset of CHANNEL_QUERY_REGISTRY keys to run.
        Defaults to all registered channels.
    comparison_types : list, optional
        Subset of ["MoM", "QoQ", "YoY"] to run.
        Defaults to all three (respects RUN_MOM / RUN_QOQ / RUN_YOY flags).

    Returns
    -------
    list of result dicts (one per channel × comparison type)
    """
    date_ranges = compute_date_ranges()

    if comparison_types is None:
        comparison_types = [
            ct for ct, flag in [("MoM", RUN_MOM), ("QoQ", RUN_QOQ), ("YoY", RUN_YOY)]
            if flag
        ]
    if channels is None:
        channels = list(CHANNEL_QUERY_REGISTRY.keys())

    bq_client = _get_bq_client()
    _ensure_dest_table_exists(bq_client)

    all_results = []

    for channel in channels:
        print(f"\n{'='*60}")
        print(f"  Channel: {channel.upper()}")
        print(f"{'='*60}")

        channel_bq_rows = []

        for comp_type in comparison_types:
            if comp_type not in date_ranges:
                print(f"  Skipping unknown comparison_type: {comp_type}")
                continue
            date_range = date_ranges[comp_type]
            print(
                f"\n  ── {comp_type}: {date_range['current_label']} "
                f"vs {date_range['previous_label']} ──"
            )

            result = _run_channel_for_period(channel, date_range, bq_client)
            all_results.append(result)

            bq_row = {k: v for k, v in result.items() if not k.startswith("_")}
            channel_bq_rows.append(bq_row)

        if channel_bq_rows:
            print(f"\n  Saving {len(channel_bq_rows)} rows to BQ...")
            _append_rows(bq_client, channel_bq_rows)

    total = len(all_results)
    print(f"\n{'='*60}")
    print(f"Complete — {total} insight block(s) generated")
    print(f"Saved to: {Dest_Project}.{Dest_Dataset}.{Dest_Table}")
    print(f"{'='*60}")

    return all_results


# ============================================================
# PUBLIC API — READER (dashboard display)
# ============================================================

def fetch_insights(
    comparison_type: str = None,
    channel: str = None,
    run_date: str = None,
    latest_only: bool = True,
) -> pd.DataFrame:
    """
    Fetch stored insights from the Automated_insights BigQuery table.
    This is what the dashboard tab calls — no LLM, no pipeline, just a BQ read.

    Parameters
    ----------
    comparison_type : str, optional
        "MoM", "QoQ", or "YoY". None = all.
    channel : str, optional
        "Search", "Social", "programmatic", "executive". None = all.
    run_date : str, optional
        Specific date "YYYY-MM-DD". None + latest_only=True = most recent run.
    latest_only : bool
        If True and run_date is None, returns only the most recent run_date.

    Returns
    -------
    pd.DataFrame with columns:
        run_date, channel, comparison_type, current_label, previous_label,
        current_start, current_end, previous_start, previous_end, insight
    """
    table_id = f"`{Dest_Project}.{Dest_Dataset}.{Dest_Table}`"

    conditions = []
    if latest_only and run_date is None:
        conditions.append(f"run_date = (SELECT MAX(run_date) FROM {table_id})")
    elif run_date:
        conditions.append(f"run_date = '{run_date}'")
    if comparison_type:
        conditions.append(f"comparison_type = '{comparison_type}'")
    if channel:
        conditions.append(f"channel = '{channel}'")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT
            run_date,
            channel,
            comparison_type,
            current_label,
            previous_label,
            current_start,
            current_end,
            previous_start,
            previous_end,
            insight
        FROM {table_id}
        {where_clause}
        ORDER BY channel, comparison_type
    """

    try:
        client = _get_bq_client()
        df = client.query(sql).result().to_dataframe(create_bqstorage_client=False)
        return df
    except Exception as e:
        print(f"fetch_insights error: {e}")
        return pd.DataFrame()


def get_available_run_dates() -> list:
    """Returns a list of all distinct run_dates in the insights table (desc)."""
    table_id = f"`{Dest_Project}.{Dest_Dataset}.{Dest_Table}`"
    sql = f"SELECT DISTINCT run_date FROM {table_id} ORDER BY run_date DESC LIMIT 30"
    try:
        client = _get_bq_client()
        df = client.query(sql).result().to_dataframe(create_bqstorage_client=False)
        return df["run_date"].astype(str).tolist()
    except Exception:
        return []
