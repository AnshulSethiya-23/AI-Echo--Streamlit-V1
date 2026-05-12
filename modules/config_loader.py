"""
config_loader.py
Loads charts_config.yaml and groups chart definitions by tab.
"""

import yaml
import streamlit as st
from pathlib import Path
from typing import List

CONFIG_PATH = Path(__file__).parent.parent / "config" / "charts_config.yaml"


@st.cache_resource
def load_charts_config() -> List[dict]:
    """Load and validate charts_config.yaml once per server lifetime.

    Uses cache_resource (not cache_data) because the returned list is shared
    read-only state — no per-user isolation needed and no serialisation cost.
    """
    with open(CONFIG_PATH, "r") as f:
        raw = yaml.safe_load(f)
    charts = raw.get("charts", [])
    _validate(charts)
    return charts


def get_charts_for_tab(tab: str) -> List[dict]:
    return [c for c in load_charts_config() if c.get("tab") == tab]


def get_chart_by_id(chart_id: str) -> dict:
    matches = [c for c in load_charts_config() if c.get("id") == chart_id]
    if not matches:
        raise ValueError(f"No chart found with id='{chart_id}'")
    return matches[0]


def get_scorecard_ids_for_tab(tab: str) -> List[dict]:
    return [c for c in get_charts_for_tab(tab) if c.get("chart_type") == "scorecard"]


def get_viz_charts_for_tab(tab: str) -> List[dict]:
    """Returns plotly-renderable charts — excludes scorecards and tables."""
    excluded = {"scorecard", "table"}
    return [c for c in get_charts_for_tab(tab) if c.get("chart_type") not in excluded]


def get_table_configs_for_tab(tab: str) -> List[dict]:
    """Returns table-type chart configs for a given tab."""
    return [c for c in get_charts_for_tab(tab) if c.get("chart_type") == "table"]


def _validate(charts: List[dict]) -> None:
    required = {"id", "tab", "title", "chart_type", "sql"}
    for chart in charts:
        missing = required - chart.keys()
        if missing:
            raise ValueError(
                f"Chart '{chart.get('id', 'UNKNOWN')}' is missing keys: {missing}"
            )
