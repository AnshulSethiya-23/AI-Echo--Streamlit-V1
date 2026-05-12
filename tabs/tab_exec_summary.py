"""
tab_exec_summary.py (v2) — fragment-scoped.
Narrative layout:
  1. Key Metrics     — KPI scorecards with prior-period delta
  2. Trend Graph     — interactive dual-axis chart (metric selectors left & right)
  3. Channel Split   — spend pie + clicks bar
  4. Campaign Table  — all channels, all campaigns with metrics
  5. Channel Summary — rolled-up channel table
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

from modules.config_loader import (
    get_scorecard_ids_for_tab,
    get_viz_charts_for_tab,
    get_table_configs_for_tab,
    get_charts_for_tab,
)
from modules.bq_engine import run_query, run_query_with_delta
from modules.charts import build_figure, render_scorecard, render_chart, render_table, PALETTE, CHART_LAYOUT, build_bubble, build_heatmap

TAB = "exec_summary"

_TREND_TYPES = {"line", "area"}
_DIST_TYPES  = {"bar", "grouped_bar", "stacked_bar", "pie"}

# Metric definitions for the dual-axis selector
_METRICS = {
    "Spend ($)":       {"col": "spend",       "fmt": "${:,.0f}",   "suffix": ""},
    "Clicks":          {"col": "clicks",       "fmt": "{:,.0f}",    "suffix": ""},
    "Impressions":     {"col": "impressions",  "fmt": "{:,.0f}",    "suffix": ""},
    "CTR (%)":         {"col": "ctr",          "fmt": "{:.2f}%",    "suffix": "%"},
    "CPC ($)":         {"col": "cpc",          "fmt": "${:.2f}",    "suffix": ""},
    "CPM ($)":         {"col": "cpm",          "fmt": "${:.2f}",    "suffix": ""},
}
_METRIC_NAMES = list(_METRICS.keys())


def _prior_period(start_date: str, end_date: str) -> tuple[str, str]:
    fmt = "%Y-%m-%d"
    s = datetime.strptime(start_date, fmt)
    e = datetime.strptime(end_date, fmt)
    delta = e - s
    prior_end = s - timedelta(days=1)
    prior_start = prior_end - delta
    return prior_start.strftime(fmt), prior_end.strftime(fmt)


def _build_dual_axis_chart(df, left_metric: str, right_metric: str) -> go.Figure:
    """Builds a dual-axis Plotly chart from the multi-metric trend dataframe."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    lm = _METRICS[left_metric]
    rm = _METRICS[right_metric]

    lc = lm["col"]
    rc = rm["col"]

    if lc in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[lc],
                name=left_metric,
                mode="lines+markers",
                line=dict(color=PALETTE[0], width=2.5),
                marker=dict(size=5, color=PALETTE[0]),
                hovertemplate=f"<b>{left_metric}</b>: %{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=False,
        )

    if rc in df.columns and rc != lc:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[rc],
                name=right_metric,
                mode="lines+markers",
                line=dict(color=PALETTE[1], width=2.5, dash="dot"),
                marker=dict(size=5, color=PALETTE[1]),
                hovertemplate=f"<b>{right_metric}</b>: %{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=True,
        )
    elif rc == lc:
        pass  # same metric — only one trace shown, no warning needed

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Kanit, sans-serif", size=12, color="#000000"),
        margin=dict(l=50, r=50, t=20, b=30),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5,
            font=dict(family="Kanit, sans-serif", size=12),
        ),
        hoverlabel=dict(
            bgcolor="#FFDD33", font_size=12,
            font_family="Kanit, sans-serif", font_color="#000000",
            bordercolor="#000000",
        ),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, linecolor="#000000", linewidth=0.5)
    fig.update_yaxes(
        title_text=f"← {left_metric}",
        secondary_y=False,
        gridcolor="#FFE770",
        gridwidth=0.5,
        linecolor="#000000",
        linewidth=0.5,
        title_font=dict(color=PALETTE[0], family="Kanit, sans-serif", size=11),
        tickfont=dict(color=PALETTE[0]),
    )
    fig.update_yaxes(
        title_text=f"{right_metric} →",
        secondary_y=True,
        showgrid=False,
        title_font=dict(color=PALETTE[1], family="Kanit, sans-serif", size=11),
        tickfont=dict(color=PALETTE[1]),
    )
    return fig


@st.fragment
def render(start_date: str, end_date: str) -> None:
    prior_start, prior_end = _prior_period(start_date, end_date)

    st.subheader("Executive Summary")
    st.caption(
        f"Reporting period: **{start_date}** → **{end_date}**"
        f"&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"Prior period: {prior_start} → {prior_end}"
    )

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

    # ── 2. Interactive Dual-Axis Trend Chart ──────────────────────────────────
    st.markdown("#### 📈 Trend Graph")
    st.caption("Select a metric on each side to compare any two KPIs on a dual axis.")

    # Fetch multi-metric trend data (single query, all metrics)
    all_charts = get_charts_for_tab(TAB)
    multi_cfg = next((c for c in all_charts if c["id"] == "exec_multi_metric_trend"), None)

    if multi_cfg:
        df_trend = run_query(
            sql_template=multi_cfg["sql"],
            start_date=start_date,
            end_date=end_date,
        )

        if not df_trend.empty:
            # Init session state
            if "exec_left_metric" not in st.session_state:
                st.session_state["exec_left_metric"] = "Impressions"
            if "exec_right_metric" not in st.session_state:
                st.session_state["exec_right_metric"] = "Spend ($)"

            # Three-column layout: left selector | chart | right selector
            sel_left, chart_col, sel_right = st.columns([1, 5, 1])

            with sel_left:
                st.markdown(
                    "<div style='font-family:Kanit,sans-serif;font-weight:600;"
                    "font-size:13px;padding-bottom:6px;border-bottom:2px solid #FFDD33;"
                    "margin-bottom:10px;'>Metric 1</div>",
                    unsafe_allow_html=True,
                )
                for m in _METRIC_NAMES:
                    active = st.session_state["exec_left_metric"] == m
                    btn_style = (
                        "background:#FFDD33;border:1.5px solid #000;border-radius:999px;"
                        "padding:4px 10px;font-family:Kanit,sans-serif;font-size:12px;"
                        "font-weight:600;cursor:pointer;width:100%;text-align:left;margin-bottom:4px;"
                        if active else
                        "background:#fff;border:1.5px solid #000;border-radius:999px;"
                        "padding:4px 10px;font-family:Kanit,sans-serif;font-size:12px;"
                        "cursor:pointer;width:100%;text-align:left;margin-bottom:4px;"
                    )
                    if st.button(m, key=f"lm_{m}", width='stretch'):
                        st.session_state["exec_left_metric"] = m
                        st.rerun()

            with sel_right:
                st.markdown(
                    "<div style='font-family:Kanit,sans-serif;font-weight:600;"
                    "font-size:13px;padding-bottom:6px;border-bottom:2px solid #2563EB;"
                    "margin-bottom:10px;'>Metric 2</div>",
                    unsafe_allow_html=True,
                )
                for m in _METRIC_NAMES:
                    active = st.session_state["exec_right_metric"] == m
                    if st.button(m, key=f"rm_{m}", width='stretch'):
                        st.session_state["exec_right_metric"] = m
                        st.rerun()

            with chart_col:
                lm_name = st.session_state["exec_left_metric"]
                rm_name = st.session_state["exec_right_metric"]

                # ── Metric label banner above the chart ──
                st.markdown(
                    f"""
                    <div style="
                        display:flex;justify-content:space-between;align-items:center;
                        background:#FFFEF7;border:1.5px solid #000;border-radius:8px;
                        padding:8px 18px;margin-bottom:8px;font-family:Kanit,sans-serif;
                        box-shadow:2px 2px 0 0 #000;">
                      <div>
                        <span style="display:inline-block;width:12px;height:12px;
                          border-radius:50%;background:#2563EB;margin-right:6px;vertical-align:middle;"></span>
                        <span style="font-weight:600;font-size:13px;">Metric 1:</span>
                        <span style="font-size:13px;margin-left:4px;">{lm_name}</span>
                      </div>
                      <div style="font-size:11px;color:#000;opacity:0.4;">dual-axis trend</div>
                      <div>
                        <span style="font-weight:600;font-size:13px;">Metric 2:</span>
                        <span style="font-size:13px;margin-left:4px;">{rm_name}</span>
                        <span style="display:inline-block;width:12px;height:12px;
                          border-radius:50%;background:#FFDD33;border:1px solid #000;
                          margin-left:6px;vertical-align:middle;"></span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                fig = _build_dual_axis_chart(df_trend, lm_name, rm_name)
                st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
        else:
            st.info("No trend data available for the selected period.")

    st.divider()

    # ── 3. Channel Distribution ───────────────────────────────────────────────
    st.markdown("#### 🥧 Channel Distribution")

    viz_charts  = get_viz_charts_for_tab(TAB)
    pie_configs = [c for c in viz_charts if c["chart_type"] == "pie"]
    dist_charts = [c for c in viz_charts if c["chart_type"] in _DIST_TYPES and c["chart_type"] != "pie"]
    trend_charts = [c for c in viz_charts if c["chart_type"] in _TREND_TYPES]

    # Pie left, bar right
    if pie_configs or dist_charts:
        left_col, right_col = st.columns(2)
        with left_col:
            if pie_configs:
                pie_df = run_query(sql_template=pie_configs[0]["sql"], start_date=start_date, end_date=end_date)
                fig = build_figure(pie_configs[0], pie_df)
                if fig:
                    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
        with right_col:
            if dist_charts:
                bar_df = run_query(sql_template=dist_charts[0]["sql"], start_date=start_date, end_date=end_date)
                render_chart(dist_charts[0], bar_df)

    st.divider()

    # ── 4. Campaign Performance Table (cross-channel) ─────────────────────────
    st.markdown("#### 🗂️ Campaign Performance — All Channels")
    st.caption("All campaigns ranked by spend. Includes Search and Social.")

    campaign_cfg = next(
        (c for c in get_table_configs_for_tab(TAB) if c["id"] == "exec_campaign_table"),
        None,
    )
    if campaign_cfg:
        df_camp = run_query(sql_template=campaign_cfg["sql"], start_date=start_date, end_date=end_date)
        render_table(campaign_cfg, df_camp)

    st.divider()

    # ── 5. Channel Performance Summary ───────────────────────────────────────
    st.markdown("#### 📋 Channel Performance Summary")

    channel_cfg = next(
        (c for c in get_table_configs_for_tab(TAB) if c["id"] == "exec_channel_table"),
        None,
    )
    if channel_cfg:
        df_ch = run_query(sql_template=channel_cfg["sql"], start_date=start_date, end_date=end_date)
        render_table(channel_cfg, df_ch)

    st.divider()

    # ── 6. Deep Analysis ──────────────────────────────────────────────────────
    st.markdown("#### 🔬 Deep Analysis")
    st.caption(
        "Advanced views: channel efficiency scatter and spend distribution by day of week. "
        "Bubble size = spend; dashed lines mark the cross-channel average."
    )

    deep_left, deep_right = st.columns(2)

    # ── 6a. Channel efficiency bubble (CTR vs CPC, sized by spend) ────────────
    _SQL_CHANNEL_EFFICIENCY = """
    SELECT
      Channel AS channel,
      ROUND(SAFE_DIVIDE(SUM(Clicks), SUM(Impressions)) * 100, 4) AS ctr,
      ROUND(SAFE_DIVIDE(SUM(Cost),   SUM(Clicks)),      4) AS cpc,
      ROUND(SUM(Cost), 2)                                  AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Executive_Summary_`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY Channel
    HAVING spend > 0
    ORDER BY spend DESC
    """
    with deep_left:
        st.markdown("**Channel Efficiency: CTR vs CPC**")
        st.caption("High CTR + low CPC = top-right quadrant is the sweet spot.")
        df_eff = run_query(sql_template=_SQL_CHANNEL_EFFICIENCY, start_date=start_date, end_date=end_date)
        fig_eff = build_bubble(
            df=df_eff,
            x_col="ctr", y_col="cpc",
            size_col="spend", label_col="channel",
            title="",
            x_label="CTR (%)", y_label="CPC ($)",
            color_col="channel",
            add_mean_lines=True,
        )
        if fig_eff:
            st.plotly_chart(fig_eff, width='stretch', config={"displayModeBar": False})
        else:
            st.info("No data available for the selected period.")

    # ── 6b. Spend by day × week heatmap ──────────────────────────────────────
    _SQL_WEEKDAY_HEATMAP = """
    SELECT
      FORMAT_DATE('%A', DATE(Date))                                        AS day_of_week,
      FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))       AS week_iso,
      FORMAT_DATE('%b %d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))          AS week_label,
      ROUND(SUM(Cost), 2)                                                  AS spend
    FROM `{project}.{dataset}.Brookfield_1H_Executive_Summary_`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY 1, 2, 3
    ORDER BY week_iso
    """
    with deep_right:
        st.markdown("**Spend by Day of Week × Week**")
        st.caption("Darker = higher spend. Reveals weekly pacing patterns.")
        df_hw = run_query(sql_template=_SQL_WEEKDAY_HEATMAP, start_date=start_date, end_date=end_date)
        if df_hw is not None and not df_hw.empty:
            col_order = (
                df_hw.drop_duplicates("week_iso")
                .sort_values("week_iso")["week_label"]
                .tolist()
            )
            fig_hw = build_heatmap(
                df=df_hw,
                row_col="day_of_week", col_col="week_label", value_col="spend",
                title="",
                row_order=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                col_order=col_order,
                value_fmt="${:,.0f}",
            )
            if fig_hw:
                st.plotly_chart(fig_hw, width='stretch', config={"displayModeBar": False})
            else:
                st.info("Not enough data to render the heatmap.")
        else:
            st.info("No data available for the selected period.")
