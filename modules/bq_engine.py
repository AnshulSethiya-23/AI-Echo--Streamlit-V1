"""
bq_engine.py
BigQuery client wrapper. Same interface as v1, kept identical so the
two versions are drop-in comparable.
"""

import os
import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from typing import Optional


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    sa_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if sa_json:
        import json
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return bigquery.Client(credentials=creds, project=info.get("project_id"))

    project = os.getenv("GCP_PROJECT_ID")
    return bigquery.Client(project=project)


@st.cache_data(ttl=3600, show_spinner="⏳ Fetching data…")
def run_query(
    sql_template: str,
    start_date: str,
    end_date: str,
    project: Optional[str] = None,
    dataset: Optional[str] = None,
) -> pd.DataFrame:
    bq_project = project or os.getenv("GCP_PROJECT_ID", "your-gcp-project")
    bq_dataset = dataset or os.getenv("BQ_DATASET", "your_dataset")

    sql = sql_template.format(
        start_date=start_date,
        end_date=end_date,
        project=bq_project,
        dataset=bq_dataset,
    )

    client = get_bq_client()
    try:
        return client.query(sql).result().to_dataframe(create_bqstorage_client=False)
    except Exception as e:
        st.error(f"BigQuery error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def run_query_with_delta(
    sql_template: str,
    start_date: str,
    end_date: str,
    metric_col: str,
    project: Optional[str] = None,
    dataset: Optional[str] = None,
) -> dict:
    from datetime import datetime, timedelta

    fmt = "%Y-%m-%d"
    start = datetime.strptime(start_date, fmt)
    end = datetime.strptime(end_date, fmt)
    delta = end - start

    prior_end = start - timedelta(days=1)
    prior_start = prior_end - delta

    df_current = run_query(sql_template, start_date, end_date, project, dataset)
    df_previous = run_query(
        sql_template,
        prior_start.strftime(fmt),
        prior_end.strftime(fmt),
        project,
        dataset,
    )

    current_val = float(df_current[metric_col].iloc[0]) if not df_current.empty else 0.0
    previous_val = float(df_previous[metric_col].iloc[0]) if not df_previous.empty else 0.0

    if previous_val and previous_val != 0:
        delta_pct = round(((current_val - previous_val) / previous_val) * 100, 1)
    else:
        delta_pct = 0.0

    return {
        "current": current_val,
        "previous": previous_val,
        "delta_pct": delta_pct,
    }
