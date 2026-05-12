"""
tab_forecast.py (v2) — fragment-scoped.

Forecasting tab: user selects channel, metric, and horizon, clicks
"Generate Forecast", and gets a Prophet (or TimesFM) prediction with an
80% confidence band plotted over the historical training data.

Layout:
  1. Controls        — Channel | Metric | Horizon slider
  2. Generate button — fetches BQ history + runs forecast engine
  3. Summary cards   — last actual · forecast end · peak · trough
  4. Forecast chart  — historical solid + 80% CI band + forecast dashed line
  5. Raw data table  — expandable
  6. Model note      — backend info + TimesFM upgrade path

State strategy:
  Results are stored in st.session_state under a compound key
  fc__{channel}__{metric}__{hist_start}__{hist_end}
  so slider/dropdown changes don't re-trigger expensive BQ + Prophet calls.
  Only the "Generate Forecast" button forces a fresh run by deleting the key.
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Path setup so forecast/ is importable as a sibling of tabs/ ───────────────
_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(_ROOT))

from modules.bq_engine import run_query
from modules.charts import PALETTE, CHART_LAYOUT, _hex_to_rgba
from forecast.engine import generate_forecast, FORECAST_BACKEND


# ── Channel / metric registry ─────────────────────────────────────────────────
# Mirrors the exact source-filter combos used by the existing channel tabs.
# The SQL column alias is always 'y' to match Prophet's input contract.

_CHANNEL_CONFIG: dict = {
    "Search": {
        "table": "Brookfield_1H_Search",
        "filter": """Data_Source_name IN (
            '2026 - Corporate Brand Campaign - Keyword',
            'Brookfield Brand Campaign - Search keyword'
        )""",
        "metrics": {
            "Spend ($)":   "ROUND(SUM(Cost), 2)",
            "Clicks":      "SUM(Clicks)",
            "Impressions": "SUM(Impressions)",
            "CTR (%)":     "ROUND(SAFE_DIVIDE(SUM(Clicks), SUM(Impressions)) * 100, 4)",
            "Avg CPC ($)": "ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Clicks)), 4)",
        },
    },
    "Social": {
        "table": "Brookfield_1H_Social",
        "filter": """Data_Source_name IN (
            'Brookfield Brand Campaign - Standard',
            'Brookfield - Ad Account - Campaign'
        )""",
        "metrics": {
            "Spend ($)":   "ROUND(SUM(Cost), 2)",
            "Clicks":      "SUM(Clicks)",
            "Impressions": "SUM(Impressions)",
            "CTR (%)":     "ROUND(SAFE_DIVIDE(SUM(Clicks), SUM(Impressions)) * 100, 4)",
            "Avg CPC ($)": "ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Clicks)), 4)",
        },
    },
    "Programmatic": {
        "table": "Brookfield_1H_Programmatic",
        "filter": "Data_Source = 'doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'",
        "metrics": {
            "Spend ($)":   "ROUND(SUM(Cost), 2)",
            "Impressions": "SUM(Impressions)",
            "Clicks":      "SUM(Clicks)",
            "Avg CPM ($)": "ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Impressions)) * 1000, 4)",
            "Video Views": "SUM(Video_Completed_Views__Display__Video_360)",
            "Avg CPV ($)": "ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Video_Completed_Views__Display__Video_360)), 4)",
        },
    },
}

# Always train on the last N days regardless of the sidebar date range
_HISTORY_DAYS = 365


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_history_sql(channel: str, metric_label: str) -> str:
    """Return a BQ SQL template with {project}/{dataset}/{start_date}/{end_date} placeholders."""
    cfg   = _CHANNEL_CONFIG[channel]
    table = cfg["table"]
    filt  = cfg["filter"]
    expr  = cfg["metrics"][metric_label]
    return f"""
    SELECT
        DATE(Date) AS ds,
        {expr}     AS y
    FROM `{{project}}.{{dataset}}.{table}`
    WHERE DATE(Date) BETWEEN '{{start_date}}' AND '{{end_date}}'
      AND {filt}
    GROUP BY DATE(Date)
    HAVING y IS NOT NULL AND y > 0
    ORDER BY ds
    """


def _session_key(channel: str, metric: str, hist_start: str, hist_end: str) -> str:
    return f"fc__{channel}__{metric}__{hist_start}__{hist_end}"


# ── Chart builder ──────────────────────────────────────────────────────────────

def _build_forecast_chart(
    df_hist: pd.DataFrame,
    df_fc: pd.DataFrame,
    channel: str,
    metric: str,
    horizon: int,
    df_insample: pd.DataFrame | None = None,
) -> go.Figure:
    """
    Four-layer Plotly figure:
      1. Historical solid line       — PALETTE[0] blue (actuals)
      2. In-sample fitted line       — green dashed (Prophet's fit over history)
      3. 80% CI shaded band          — PALETTE[3] amber, alpha 0.18 (future only)
      4. Forecast dashed line        — PALETTE[3] amber (future)
      + vertical "Today" annotation
    """
    today_str = date.today().isoformat()

    fig = go.Figure()

    # ── Layer 1: Historical actuals ────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df_hist["ds"],
        y=df_hist["y"],
        name="Actual (historical)",
        mode="lines+markers",
        line=dict(color=PALETTE[0], width=2.5),
        marker=dict(size=4, color=PALETTE[0]),
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Actual: %{y:,.2f}<extra></extra>",
    ))

    # ── Layer 2: In-sample fitted values (Prophet's model fit over history) ─
    if df_insample is not None and not df_insample.empty:
        fig.add_trace(go.Scatter(
            x=df_insample["ds"],
            y=df_insample["yhat"],
            name="Model fit (in-sample)",
            mode="lines",
            line=dict(color="#10B981", width=1.5, dash="dot"),
            opacity=0.8,
            hovertemplate=(
                "<b>%{x|%b %d, %Y}</b><br>Model fit: %{y:,.2f}<extra></extra>"
            ),
        ))

    # ── Layer 2a: CI upper boundary (invisible anchor for fill) ───────────
    fig.add_trace(go.Scatter(
        x=df_fc["ds"],
        y=df_fc["yhat_upper"],
        name="80% Upper",
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # ── Layer 2b: CI lower boundary + fill to upper ────────────────────────
    fig.add_trace(go.Scatter(
        x=df_fc["ds"],
        y=df_fc["yhat_lower"],
        name="80% Confidence",
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor=_hex_to_rgba(PALETTE[3], alpha=0.18),
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Lower (80%%): %{y:,.2f}<extra></extra>",
    ))

    # ── Layer 3: Forecast dashed line ─────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df_fc["ds"],
        y=df_fc["yhat"],
        name=f"Forecast (+{horizon}d)",
        mode="lines",
        line=dict(color=PALETTE[3], width=2.5, dash="dash"),
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>Forecast: %{y:,.2f}<extra></extra>",
    ))

    # ── Today marker ──────────────────────────────────────────────────────
    # Use add_shape + add_annotation instead of add_vline to avoid Plotly's
    # annotation bug where sum([str, str]) raises TypeError on date axes.
    _TODAY_COLOR = "#7C3AED"
    fig.add_shape(
        type="line",
        x0=today_str, x1=today_str,
        y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(dash="dot", color=_TODAY_COLOR, width=1.5),
        opacity=0.65,
    )
    fig.add_annotation(
        x=today_str, y=0.97,
        xref="x", yref="paper",
        text="Today",
        showarrow=False,
        font=dict(family="Kanit, sans-serif", size=11, color=_TODAY_COLOR),
        xanchor="left",
        bgcolor="rgba(255,255,255,0.75)",
        borderpad=2,
    )

    # Spread CHART_LAYOUT but exclude keys we're overriding to prevent
    # "multiple values for keyword argument" errors.
    _layout = {k: v for k, v in CHART_LAYOUT.items() if k not in ("legend", "title")}
    fig.update_layout(
        title=f"{channel} — {metric}: {_HISTORY_DAYS}-day history + {horizon}-day forecast",
        **_layout,
    )
    fig.update_layout(legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="right", x=1,
        font=dict(family="Kanit, sans-serif", size=11),
    ))
    fig.update_xaxes(title_text="Date")
    fig.update_yaxes(title_text=metric)

    return fig


# ── Scorecard HTML helper (module-level to avoid redefinition inside fragment) ──

def _card(label: str, value: str, sub: str = "", sub_color: str = "#555") -> str:
    sub_html = (
        f"<div style='font-size:11px;color:{sub_color};margin-top:3px;"
        f"font-family:Kanit,sans-serif;white-space:nowrap;overflow:hidden;"
        f"text-overflow:ellipsis;'>{sub}</div>"
        if sub else ""
    )
    return (
        f"<div style='background:#FFFEF7;border:1.5px solid #000;border-radius:8px;"
        f"padding:12px 14px;box-shadow:2px 2px 0 #000;font-family:Kanit,sans-serif;"
        f"height:88px;overflow:hidden;box-sizing:border-box;'>"
        f"<div style='font-size:10px;color:#555;text-transform:uppercase;"
        f"letter-spacing:0.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{label}</div>"
        f"<div style='font-size:20px;font-weight:600;color:#000;margin-top:4px;"
        f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{value}</div>"
        f"{sub_html}"
        f"</div>"
    )


# ── Main fragment ──────────────────────────────────────────────────────────────

@st.fragment
def render(start_date: str, end_date: str) -> None:
    """
    start_date / end_date come from the global sidebar but are NOT used for
    data fetching here — the forecast tab always trains on the last
    _HISTORY_DAYS days. They are accepted for interface compatibility only.
    """

    st.subheader("🔮 Forecasting")

    # ── How Prophet works ─────────────────────────────────────────────────────
    with st.expander("How does this forecast work?", expanded=False):
        st.markdown(
            """
**Model: Meta Prophet** — an additive decomposition model built for business time series.

It breaks your data into three components:

| Component | What it captures |
|---|---|
| **Trend** | The overall direction of the metric — growing, declining, or flat over the 365-day training window |
| **Weekly seasonality** | Day-of-week patterns — e.g. spend typically lower on weekends |
| **Residual / noise** | Random variation that can't be explained by trend or seasonality |

The model fits these components to 365 days of actual data from BigQuery, then projects them forward for the horizon you set.

**The shaded band** is the **80% confidence interval** — meaning Prophet estimates there is an 80% probability the true value will land inside the band on any given day. A tight band = high precision. A wide band = more uncertainty (usually because the metric is volatile or the training window has sparse data).

**Confidence score** below is derived from the average band width relative to the forecast value — the narrower the band, the higher the score.
            """,
        )

    st.markdown(
        "<hr style='border:none; border-top:2px solid #FFDD33; margin:8px 0 14px 0;'/>",
        unsafe_allow_html=True,
    )

    # ── 1. Controls ───────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3 = st.columns([1, 1, 2])

    with ctrl1:
        channel = st.selectbox(
            "Channel",
            options=list(_CHANNEL_CONFIG.keys()),
            key="fc_channel",
        )

    with ctrl2:
        metric = st.selectbox(
            "Metric",
            options=list(_CHANNEL_CONFIG[channel]["metrics"].keys()),
            key="fc_metric",
        )

    with ctrl3:
        horizon = st.slider(
            "Forecast horizon (days)",
            min_value=7,
            max_value=90,
            value=30,
            step=1,
            key="fc_horizon",
            help="Number of calendar days to predict forward from today.",
        )

    # Fixed history window — independent of sidebar
    today      = date.today()
    hist_end   = today.isoformat()
    hist_start = (today - timedelta(days=_HISTORY_DAYS)).isoformat()

    # ── 2. Generate button ─────────────────────────────────────────────────────
    skey = _session_key(channel, metric, hist_start, hist_end)

    btn_col, info_col = st.columns([1, 5])
    with btn_col:
        run_clicked = st.button(
            "Generate Forecast",
            type="primary",
            key="fc_run_btn",
        )
    with info_col:
        st.caption(
            f"History: **{hist_start}** → **{hist_end}**  ·  "
            f"Horizon: **{horizon} days**  ·  "
            f"Backend: **{FORECAST_BACKEND.upper()}**"
        )

    # Button click: invalidate cached result so a fresh run is forced
    if run_clicked and skey in st.session_state:
        del st.session_state[skey]

    cached = st.session_state.get(skey)

    # ── 3. Run (if button clicked) or render from cache ────────────────────────
    if not run_clicked and cached is None:
        st.info(
            "Configure the channel, metric, and horizon above, "
            "then click **Generate Forecast** to run."
        )
        return

    if cached is None:
        # ── Fetch historical data from BigQuery ────────────────────────────
        sql = _build_history_sql(channel, metric)
        with st.spinner(f"Fetching {channel} · {metric} history from BigQuery…"):
            df_hist = run_query(
                sql_template=sql,
                start_date=hist_start,
                end_date=hist_end,
            )

        if df_hist is None or df_hist.empty:
            st.warning(
                f"No data returned for **{channel} / {metric}** "
                f"between {hist_start} and {hist_end}. "
                "Check that the BigQuery tables contain records for this period."
            )
            return

        # Coerce dtypes for Prophet
        df_hist["ds"] = pd.to_datetime(df_hist["ds"])
        df_hist["y"]  = pd.to_numeric(df_hist["y"], errors="coerce")
        df_hist = df_hist.dropna(subset=["ds", "y"]).sort_values("ds").reset_index(drop=True)

        # ── Run forecast engine ────────────────────────────────────────────
        with st.spinner(
            f"Running {FORECAST_BACKEND.upper()} forecast · {horizon} days…"
        ):
            try:
                df_fc, df_insample = generate_forecast(df_hist, horizon)
            except (ValueError, RuntimeError) as exc:
                st.error(f"**Forecast failed:** {exc}")
                return

        # Persist result under compound key
        st.session_state[skey] = {
            "hist":      df_hist,
            "fc":        df_fc,
            "insample":  df_insample,
            "channel":   channel,
            "metric":    metric,
        }
        cached = st.session_state[skey]

    # ── Unpack ─────────────────────────────────────────────────────────────────
    df_hist     = cached["hist"]
    df_fc       = cached["fc"]
    df_insample = cached.get("insample")

    st.divider()

    # ── 4. Summary scorecards ──────────────────────────────────────────────────
    st.markdown("#### 📊 Forecast Summary")

    last_actual  = float(df_hist["y"].iloc[-1])
    fc_end_val   = float(df_fc["yhat"].iloc[-1])
    fc_peak      = float(df_fc["yhat"].max())
    fc_trough    = float(df_fc["yhat"].min())
    pct_change   = (fc_end_val - last_actual) / last_actual * 100 if last_actual else 0.0
    fc_peak_date = df_fc.loc[df_fc["yhat"].idxmax(), "ds"].strftime("%b %d")
    fc_end_date  = df_fc["ds"].iloc[-1].strftime("%b %d")

    # Confidence score: inverse of mean relative CI width (0–100)
    avg_fc  = df_fc["yhat"].mean()
    avg_ci  = (df_fc["yhat_upper"] - df_fc["yhat_lower"]).mean()
    rel_ci  = avg_ci / avg_fc if avg_fc > 0 else 1.0
    conf_pct = max(0.0, min(100.0, 100.0 * (1.0 - rel_ci / 2.0)))
    conf_label = "High" if conf_pct >= 70 else ("Medium" if conf_pct >= 40 else "Low")
    conf_color = "#10B981" if conf_pct >= 70 else ("#F59E0B" if conf_pct >= 40 else "#EF4444")

    # Use ASCII +/- to avoid Unicode rendering issues on Windows
    dir_sign  = "+" if pct_change >= 0 else "-"
    dir_color = "#10B981" if pct_change >= 0 else "#EF4444"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(_card("Last Actual", f"{last_actual:,.2f}", "Most recent observed"), unsafe_allow_html=True)
    with c2:
        st.markdown(_card(
            f"Forecast · {fc_end_date}",
            f"{fc_end_val:,.2f}",
            sub=f"{dir_sign}{abs(pct_change):.1f}% vs actual",
            sub_color=dir_color,
        ), unsafe_allow_html=True)
    with c3:
        st.markdown(_card(f"Peak · {fc_peak_date}", f"{fc_peak:,.2f}", "Highest in window"), unsafe_allow_html=True)
    with c4:
        st.markdown(_card("Trough", f"{fc_trough:,.2f}", "Lowest in window"), unsafe_allow_html=True)
    with c5:
        st.markdown(_card(
            "Confidence",
            f"{conf_pct:.0f}%",
            sub=f"{conf_label} · band {rel_ci*100:.0f}% of fcst",
            sub_color=conf_color,
        ), unsafe_allow_html=True)

    st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)

    st.divider()

    # ── 5. Chart ───────────────────────────────────────────────────────────────
    st.markdown(f"#### 📈 {channel} — {metric}: Historical + {horizon}-Day Forecast")
    st.caption(
        "Solid line = observed history. Dashed line = forecast. "
        "Shaded band = 80% confidence interval."
    )

    fig = _build_forecast_chart(df_hist, df_fc, channel, metric, horizon, df_insample)
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

    # ── 6. Raw forecast table (collapsed) ─────────────────────────────────────
    with st.expander(f"Raw forecast data ({horizon} rows)", expanded=False):
        display = df_fc.copy()
        display["ds"] = display["ds"].dt.strftime("%Y-%m-%d")
        display.columns = ["Date", "Forecast", "Lower (80%)", "Upper (80%)"]
        st.dataframe(display, width='stretch', hide_index=True)

    st.divider()

    # ── 7. Model note ──────────────────────────────────────────────────────────
    if FORECAST_BACKEND == "prophet":
        st.markdown(
            "<div style='"
            "background:#C2EEFF; border-left:4px solid #2563EB; border-radius:6px; "
            "padding:10px 14px; font-size:12px; font-family:Kanit,sans-serif;'>"
            "<b>Backend: Prophet (local)</b> — seasonal weekly patterns, 80% CI, "
            "365-day training window. "
            "To upgrade to <b>TimesFM on Vertex AI</b>: deploy the endpoint from "
            "Vertex AI Model Garden, then set <code>FORECAST_BACKEND=timesfm</code> "
            "and <code>TIMESFM_ENDPOINT_ID=&lt;your-endpoint-id&gt;</code> in <code>.env</code>."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='"
            "background:#FFE770; border-left:4px solid #F59E0B; border-radius:6px; "
            "padding:10px 14px; font-size:12px; font-family:Kanit,sans-serif;'>"
            "<b>Backend: TimesFM (Vertex AI)</b> — zero-shot foundation model. "
            "80% CI from p10/p90 quantiles."
            "</div>",
            unsafe_allow_html=True,
        )
