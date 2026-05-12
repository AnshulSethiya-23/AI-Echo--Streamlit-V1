"""
tab_programmatic.py (v2) — fragment-scoped.
Narrative layout:
  1. Key Metrics     — 6 KPI scorecards (impressions, clicks, CPM, CPV, spend, video views)
  2. Performance Trends — impressions, spend, CPM, video views line/area charts
  3. Channel Breakdown — spend, CPM, impressions by DV360 channel bar charts
  4. Data Summary    — channel performance table
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

TAB = "programmatic"

_TREND_TYPES = {"line", "area"}
_DIST_TYPES  = {"bar", "grouped_bar", "stacked_bar"}


@st.fragment
def render(start_date: str, end_date: str) -> None:
    st.subheader("Programmatic Performance")
    st.caption(f"Reporting period: **{start_date}** to **{end_date}**")

    # ── 1. Key Metrics ────────────────────────────────────────────────────────
    st.markdown("#### 📊 Key Metrics")

    scorecards = get_scorecard_ids_for_tab(TAB)
    if scorecards:
        # Split across two rows if there are more than 4 scorecards
        if len(scorecards) <= 4:
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
        else:
            # First row: first 3 scorecards
            row1, row2 = scorecards[:3], scorecards[3:]
            cols = st.columns(3)
            for col, cfg in zip(cols, row1):
                with col:
                    data = run_query_with_delta(
                        sql_template=cfg["sql"],
                        start_date=start_date,
                        end_date=end_date,
                        metric_col=cfg["metric_col"],
                    )
                    render_scorecard(cfg, data)
            # Second row: remaining scorecards
            cols2 = st.columns(len(row2))
            for col, cfg in zip(cols2, row2):
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
    st.caption("Reach, spend, CPM efficiency, and video completion over time.")

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

    # ── 3. Channel Breakdown ──────────────────────────────────────────────────
    st.markdown("#### 📊 DV360 Channel Breakdown")
    st.caption("Spend, efficiency, and scale across DV360 inventory channels.")

    for i in range(0, len(dist_charts), 2):
        row = dist_charts[i : i + 2]
        cols = st.columns(len(row))
        for col, cfg in zip(cols, row):
            with col:
                df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
                render_chart(cfg, df)

    st.divider()

    # ── 4. Data Summary table ─────────────────────────────────────────────────
    st.markdown("#### 🗂️ Channel Performance Summary")
    st.caption("Full breakdown by DV360 channel — impressions, clicks, spend, CPM, video views, CPV.")

    for cfg in get_table_configs_for_tab(TAB):
        df = run_query(sql_template=cfg["sql"], start_date=start_date, end_date=end_date)
        render_table(cfg, df)

    st.divider()

    # ── 5. Deep Analysis ──────────────────────────────────────────────────────
    st.markdown("#### 🔬 Deep Analysis")
    st.caption(
        "Channel efficiency scatter (CPM vs video view rate) and weekly spend heatmap. "
        "Bubble size = spend. Low CPM + high video view rate = top-left is the sweet spot."
    )

    _SQL_PROG_EFFICIENCY = """
    SELECT
      Channels_DV360                                                              AS channel,
      ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Impressions)) * 1000,                 4) AS cpm,
      ROUND(
        SAFE_DIVIDE(
          SUM(Video_Completed_Views__Display__Video_360), SUM(Impressions)
        ) * 100, 4
      )                                                                           AS video_view_rate,
      ROUND(SUM(Cost), 2)                                                         AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Programmatic`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source = 'doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'
    GROUP BY Channels_DV360
    HAVING spend > 0
    ORDER BY spend DESC
    """

    _SQL_PROG_HEATMAP = """
    SELECT
      FORMAT_DATE('%A', DATE(Date))                                        AS day_of_week,
      FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))       AS week_iso,
      FORMAT_DATE('%b %d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))          AS week_label,
      ROUND(SUM(Cost), 2)                                                  AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Programmatic`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
      AND Data_Source = 'doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'
    GROUP BY 1, 2, 3
    ORDER BY week_iso
    """

    col_bubble, col_heat = st.columns(2)

    with col_bubble:
        st.markdown("**Channel Efficiency: CPM vs Video View Rate**")
        st.caption("Low CPM + high video view rate = high-value programmatic channels.")
        df_pe = run_query(sql_template=_SQL_PROG_EFFICIENCY, start_date=start_date, end_date=end_date)
        fig_pe = build_bubble(
            df=df_pe,
            x_col="cpm", y_col="video_view_rate",
            size_col="spend", label_col="channel",
            title="",
            x_label="CPM ($)", y_label="Video View Rate (%)",
            color_col="channel",
            add_mean_lines=True,
        )
        if fig_pe:
            st.plotly_chart(fig_pe, width='stretch', config={"displayModeBar": False})
        else:
            st.info("No data available for the selected period.")

    with col_heat:
        st.markdown("**Programmatic Spend by Day of Week × Week**")
        st.caption("Darker = higher spend. Reveals weekly pacing patterns.")
        df_ph = run_query(sql_template=_SQL_PROG_HEATMAP, start_date=start_date, end_date=end_date)
        if df_ph is not None and not df_ph.empty:
            col_order = (
                df_ph.drop_duplicates("week_iso")
                .sort_values("week_iso")["week_label"]
                .tolist()
            )
            fig_ph = build_heatmap(
                df=df_ph,
                row_col="day_of_week", col_col="week_label", value_col="spend",
                title="",
                row_order=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                col_order=col_order,
                value_fmt="${:,.0f}",
            )
            if fig_ph:
                st.plotly_chart(fig_ph, width='stretch', config={"displayModeBar": False})
            else:
                st.info("Not enough data to render the heatmap.")
        else:
            st.info("No data available for the selected period.")
