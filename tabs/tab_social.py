"""
tab_social.py (v2) — fragment-scoped.
Narrative layout:
  1. Key Metrics     — 5 KPI scorecards (impressions, clicks, CTR, spend, CPC)
  2. Performance Trends — clicks/impressions, spend, CTR line/area charts
  3. Platform Breakdown — impressions stacked bar + spend by platform bar
  4. Data Summary    — platform performance table
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

TAB = "social"

_TREND_TYPES = {"line", "area"}
_DIST_TYPES  = {"bar", "grouped_bar", "stacked_bar"}


@st.fragment
def render(start_date: str, end_date: str) -> None:
    st.subheader("Social Performance")
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
    st.caption("Reach, engagement, and cost efficiency moving over time.")

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

    # ── 3. Platform Breakdown ─────────────────────────────────────────────────
    st.markdown("#### 📊 Platform Breakdown")
    st.caption("How spend and impressions are split across social platforms.")

    for i in range(0, len(dist_charts), 2):
        row = dist_charts[i : i + 2]
        cols = st.columns(len(row))
        for col, cfg in zip(cols, row):
            with col:
                df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
                render_chart(cfg, df)

    st.divider()

    # ── 4. Data Summary table ─────────────────────────────────────────────────
    st.markdown("#### 🗂️ Platform Performance Summary")

    for cfg in get_table_configs_for_tab(TAB):
        df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
        render_table(cfg, df)

    st.divider()

    # ── 5. Deep Analysis ──────────────────────────────────────────────────────
    st.markdown("#### 🔬 Deep Analysis")
    st.caption(
        "Platform efficiency scatter and spend heatmap. "
        "Bubble size = spend. Dashed lines mark the average CPC and CTR across platforms."
    )

    _SQL_SOCIAL_EFFICIENCY = """
    SELECT
      Data_Source_name                                           AS platform,
      ROUND(SAFE_DIVIDE(SUM(Cost),   SUM(Clicks)),        4)   AS cpc,
      ROUND(SAFE_DIVIDE(SUM(Clicks), SUM(Impressions)) * 100, 4) AS ctr,
      ROUND(SUM(Cost), 2)                                       AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Social`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source_name IN (
        'Brookfield Brand Campaign - Standard',
        'Brookfield - Ad Account - Campaign'
      )
    GROUP BY Data_Source_name
    HAVING spend > 0
    """

    _SQL_SOCIAL_HEATMAP = """
    SELECT
      FORMAT_DATE('%A', DATE(Date))                                        AS day_of_week,
      FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))       AS week_iso,
      FORMAT_DATE('%b %d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))          AS week_label,
      ROUND(SUM(Cost), 2)                                                  AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Social`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source_name IN (
        'Brookfield Brand Campaign - Standard',
        'Brookfield - Ad Account - Campaign'
      )
    GROUP BY 1, 2, 3
    ORDER BY week_iso
    """

    col_bubble, col_heat = st.columns(2)

    with col_bubble:
        st.markdown("**Platform Efficiency: CPC vs CTR**")
        st.caption("Low CPC + high CTR is the ideal top-left quadrant.")
        df_soc_e = run_query(sql_template=_SQL_SOCIAL_EFFICIENCY, start_date=start_date, end_date=end_date)
        fig_soc_e = build_bubble(
            df=df_soc_e,
            x_col="cpc", y_col="ctr",
            size_col="spend", label_col="platform",
            title="",
            x_label="CPC ($)", y_label="CTR (%)",
            color_col="platform",
            add_mean_lines=True,
        )
        if fig_soc_e:
            st.plotly_chart(fig_soc_e, width='stretch', config={"displayModeBar": False})
        else:
            st.info("No data available for the selected period.")

    with col_heat:
        st.markdown("**Social Spend by Day of Week × Week**")
        st.caption("Darker = higher spend. Reveals weekly pacing patterns.")
        df_soc_h = run_query(sql_template=_SQL_SOCIAL_HEATMAP, start_date=start_date, end_date=end_date)
        if df_soc_h is not None and not df_soc_h.empty:
            col_order = (
                df_soc_h.drop_duplicates("week_iso")
                .sort_values("week_iso")["week_label"]
                .tolist()
            )
            fig_soc_h = build_heatmap(
                df=df_soc_h,
                row_col="day_of_week", col_col="week_label", value_col="spend",
                title="",
                row_order=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                col_order=col_order,
                value_fmt="${:,.0f}",
            )
            if fig_soc_h:
                st.plotly_chart(fig_soc_h, width='stretch', config={"displayModeBar": False})
            else:
                st.info("Not enough data to render the heatmap.")
        else:
            st.info("No data available for the selected period.")
