"""
tab_search.py (v2) — fragment-scoped.
Narrative layout:
  1. Key Metrics     — 5 KPI scorecards
  2. Performance Trends — clicks/impressions, spend, CPC, CTR line/area charts
  3. Campaign Breakdown — clicks by campaign, spend by campaign bar charts
  4. Data Summary    — full campaign performance table
"""

import streamlit as st

from modules.config_loader import (
    get_scorecard_ids_for_tab,
    get_viz_charts_for_tab,
    get_table_configs_for_tab,
)
from modules.bq_engine import run_query, run_query_with_delta
import plotly.graph_objects as go
from modules.charts import render_chart, render_scorecard, render_table, build_bubble, build_heatmap, PALETTE, CHART_LAYOUT

TAB = "search"

_TREND_TYPES = {"line", "area"}
_DIST_TYPES  = {"bar", "grouped_bar", "stacked_bar"}


@st.fragment
def render(start_date: str, end_date: str) -> None:
    st.subheader("Search Performance")
    st.caption(f"Reporting period: **{start_date}** to **{end_date}**")

    # ── 1. Key Metrics ────────────────────────────────────────────────────────
    st.markdown("#### 📊 Key Metrics")

    scorecards = get_scorecard_ids_for_tab(TAB)
    if scorecards:
        cols = st.columns(len(scorecards))
        for col, cfg in zip(cols, scorecards):
            with col:
                data = run_query_with_delta(
                    sql_template=cfg["sql"],
                    start_date=start_date,
                    end_date=end_date,
                    metric_col=cfg["metric_col"],
                )
                render_scorecard(cfg, data)

    st.divider()

    # ── 2. Performance Trends ─────────────────────────────────────────────────
    st.markdown("#### 📈 Performance Trends")
    st.caption("Day-by-day movement in clicks, impressions, spend, CPC, and CTR.")

    viz_charts   = get_viz_charts_for_tab(TAB)
    trend_charts = [c for c in viz_charts if c["chart_type"] in _TREND_TYPES]
    dist_charts  = [c for c in viz_charts if c["chart_type"] in _DIST_TYPES]

    for i in range(0, len(trend_charts), 2):
        row = trend_charts[i : i + 2]
        cols = st.columns(len(row))
        for col, cfg in zip(cols, row):
            with col:
                df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
                render_chart(cfg, df)

    st.divider()

    # ── 3. Campaign Breakdown ─────────────────────────────────────────────────
    st.markdown("#### 📊 Campaign Breakdown")
    st.caption("Top campaigns by volume and spend.")

    for i in range(0, len(dist_charts), 2):
        row = dist_charts[i : i + 2]
        cols = st.columns(len(row))
        for col, cfg in zip(cols, row):
            with col:
                df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
                render_chart(cfg, df)

    st.divider()

    # ── 4. Data Summary table ─────────────────────────────────────────────────
    st.markdown("#### 🗂️ Campaign Performance Summary")
    st.caption("All campaigns ranked by spend — sorted highest to lowest.")

    for cfg in get_table_configs_for_tab(TAB):
        df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
        render_table(cfg, df)

    st.divider()

    # ── 5. Deep Analysis ──────────────────────────────────────────────────────
    st.markdown("#### 🔬 Deep Analysis")
    st.caption(
        "Campaign efficiency scatter and spend heatmap. "
        "Bubble size = spend. Dashed lines mark the average CPC and CTR."
    )

    _SQL_SEARCH_EFFICIENCY = """
    SELECT
      Campaign_New                                             AS campaign,
      ROUND(SAFE_DIVIDE(SUM(Cost),   SUM(Clicks)),      4)   AS cpc,
      ROUND(SAFE_DIVIDE(SUM(Clicks), SUM(Impressions)) * 100, 4) AS ctr,
      ROUND(SUM(Cost), 2)                                     AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Search`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source_name IN (
        '2026 - Corporate Brand Campaign - Keyword',
        'Brookfield Brand Campaign - Search keyword'
      )
    GROUP BY Campaign_New
    HAVING spend > 0
    ORDER BY spend DESC
    LIMIT 20
    """

    _SQL_SEARCH_HEATMAP = """
    SELECT
      FORMAT_DATE('%A', DATE(Date))                                        AS day_of_week,
      FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))       AS week_iso,
      FORMAT_DATE('%b %d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))          AS week_label,
      ROUND(SUM(Cost), 2)                                                  AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Search`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source_name IN (
        '2026 - Corporate Brand Campaign - Keyword',
        'Brookfield Brand Campaign - Search keyword'
      )
    GROUP BY 1, 2, 3
    ORDER BY week_iso
    """

    col_bubble, col_heat = st.columns(2)

    with col_bubble:
        st.markdown("**Campaign Efficiency: CPC vs CTR**")
        st.caption("Low CPC + high CTR = bottom-right is the sweet spot.")
        df_se = run_query(sql_template=_SQL_SEARCH_EFFICIENCY, start_date=start_date, end_date=end_date)
        fig_se = build_bubble(
            df=df_se,
            x_col="cpc", y_col="ctr",
            size_col="spend", label_col="campaign",
            title="",
            x_label="CPC ($)", y_label="CTR (%)",
            add_mean_lines=True,
        )
        if fig_se:
            st.plotly_chart(fig_se, width='stretch', config={"displayModeBar": False})
        else:
            st.info("No data available for the selected period.")

    with col_heat:
        st.markdown("**Search Spend by Day of Week × Week**")
        st.caption("Darker = higher spend. Reveals weekly pacing patterns.")
        df_sh = run_query(sql_template=_SQL_SEARCH_HEATMAP, start_date=start_date, end_date=end_date)
        if df_sh is not None and not df_sh.empty:
            col_order = (
                df_sh.drop_duplicates("week_iso")
                .sort_values("week_iso")["week_label"]
                .tolist()
            )
            fig_sh = build_heatmap(
                df=df_sh,
                row_col="day_of_week", col_col="week_label", value_col="spend",
                title="",
                row_order=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                col_order=col_order,
                value_fmt="${:,.0f}",
            )
            if fig_sh:
                st.plotly_chart(fig_sh, width='stretch', config={"displayModeBar": False})
            else:
                st.info("Not enough data to render the heatmap.")
        else:
            st.info("No data available for the selected period.")
