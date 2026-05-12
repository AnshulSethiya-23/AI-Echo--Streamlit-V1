"""
tab_ga4.py — Google Analytics 4 Explorer
Narrative layout:
  1. Connection panel — property selector (Admin API) or manual entry
  2. Preset report cards — Sessions, Users, Bounce Rate, Top Pages, Channels, Devices
  3. Chat interface — ADK-powered GA4 agent (falls back to regex NL if agent unavailable)

Dependencies:
  google-analytics-data>=0.18
  google-analytics-admin>=0.22
  google-adk  (for ADK chat — optional, falls back gracefully)
"""

from __future__ import annotations

import os
import re
import uuid
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ── BL palette (mirrors charts.py) ────────────────────────────────────────────
_PALETTE = ["#2563EB", "#FFDD33", "#80DBFF", "#F59E0B", "#10B981", "#FFE770"]
_FONT = "Kanit, sans-serif"

# ── Check GA4 library availability at import time ─────────────────────────────
try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric,
    )
    _GA4_DATA_OK = True
except ImportError:
    _GA4_DATA_OK = False

try:
    from google.analytics.admin import AnalyticsAdminServiceClient
    _GA4_ADMIN_OK = True
except ImportError:
    _GA4_ADMIN_OK = False

_GA4_AVAILABLE = _GA4_DATA_OK  # Data API is the hard requirement

# ── Try to import the GA4 ADK agent ──────────────────────────────────────────
try:
    from ga4_agent.agent import (
        chat as _ga4_agent_chat,
        create_session as _ga4_create_session,
    )
    _GA4_AGENT_OK = True
except Exception:
    _GA4_AGENT_OK = False


# ── Auth helpers ──────────────────────────────────────────────────────────────

_GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _make_credentials(scopes: list[str]):
    """
    Return credentials with the requested scopes.

    Priority:
      1. GCP_SERVICE_ACCOUNT_JSON env var — service account key (JSON string)
      2. ADC (gcloud auth application-default login) — explicitly scoped so that
         GA4 API calls succeed. ADC without explicit scopes defaults to
         cloud-platform only, which is NOT sufficient for the Analytics API.
    """
    sa_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if sa_json:
        from google.oauth2 import service_account
        import json
        info = json.loads(sa_json)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    # Explicit ADC with the required scopes
    import google.auth
    creds, _ = google.auth.default(scopes=scopes)
    return creds


def _ga4_client():
    """Return a BetaAnalyticsDataClient using ADC or service account."""
    return BetaAnalyticsDataClient(credentials=_make_credentials(_GA4_SCOPES))


def _admin_client():
    """Return an AnalyticsAdminServiceClient."""
    if not _GA4_ADMIN_OK:
        return None
    return AnalyticsAdminServiceClient(credentials=_make_credentials(_GA4_SCOPES))


@st.cache_data(ttl=3600, show_spinner=False)
def _list_properties() -> list[dict]:
    """List all GA4 properties the service account can access."""
    if not _GA4_ADMIN_OK:
        return []
    try:
        admin = _admin_client()
        if admin is None:
            return []
        accounts = admin.list_account_summaries()
        props = []
        for acc in accounts:
            for prop in acc.property_summaries:
                props.append({
                    "account": acc.display_name,
                    "property": prop.display_name,
                    "property_id": prop.property.replace("properties/", ""),
                })
        return props
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def _run_ga4_report(
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    metrics: list[str],
    limit: int = 20,
) -> pd.DataFrame:
    """Run a GA4 Data API report and return a DataFrame."""
    if not _GA4_AVAILABLE:
        return pd.DataFrame()
    try:
        client = _ga4_client()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=limit,
        )
        response = client.run_report(request)
        rows = []
        for row in response.rows:
            r = {response.dimension_headers[i].name: row.dimension_values[i].value
                 for i in range(len(response.dimension_headers))}
            for i, mv in enumerate(row.metric_values):
                r[response.metric_headers[i].name] = mv.value
            rows.append(r)
        df = pd.DataFrame(rows)
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        return df
    except Exception as e:
        st.error(f"GA4 query error: {e}")
        return pd.DataFrame()


# ── Preset report definitions ─────────────────────────────────────────────────

_PRESETS = [
    {
        "title": "Sessions & Users",
        "icon": "👥",
        "desc": "Day-by-day sessions and active users",
        "dimensions": ["date"],
        "metrics": ["sessions", "activeUsers"],
        "chart": "line",
        "x": "date",
        "ys": ["sessions", "activeUsers"],
    },
    {
        "title": "Channel Breakdown",
        "icon": "📊",
        "desc": "Sessions by default channel group",
        "dimensions": ["sessionDefaultChannelGroup"],
        "metrics": ["sessions", "engagementRate"],
        "chart": "bar",
        "x": "sessionDefaultChannelGroup",
        "ys": ["sessions"],
    },
    {
        "title": "Top Landing Pages",
        "icon": "📄",
        "desc": "Top 15 pages by sessions",
        "dimensions": ["landingPagePlusQueryString"],
        "metrics": ["sessions", "bounceRate", "averageSessionDuration"],
        "chart": "table",
        "x": "landingPagePlusQueryString",
        "ys": ["sessions"],
        "limit": 15,
    },
    {
        "title": "Device Category",
        "icon": "📱",
        "desc": "Sessions split by device type",
        "dimensions": ["deviceCategory"],
        "metrics": ["sessions", "activeUsers", "engagementRate"],
        "chart": "bar",
        "x": "deviceCategory",
        "ys": ["sessions"],
    },
    {
        "title": "Country Performance",
        "icon": "🌍",
        "desc": "Top 20 countries by sessions",
        "dimensions": ["country"],
        "metrics": ["sessions", "activeUsers", "bounceRate"],
        "chart": "bar",
        "x": "country",
        "ys": ["sessions"],
        "limit": 20,
    },
    {
        "title": "Engagement Overview",
        "icon": "⏱️",
        "desc": "Engagement rate and avg session duration by date",
        "dimensions": ["date"],
        "metrics": ["engagementRate", "averageSessionDuration", "bounceRate"],
        "chart": "line",
        "x": "date",
        "ys": ["engagementRate", "averageSessionDuration"],
    },
]


# ── Fallback NL → GA4 query parser (used when ADK agent not available) ────────

_NL_PATTERNS = [
    (r"(top|best).*page",   {"dimensions": ["pageTitle"], "metrics": ["screenPageViews", "sessions"], "limit": 15}),
    (r"channel",            {"dimensions": ["sessionDefaultChannelGroup"], "metrics": ["sessions", "activeUsers"], "limit": 10}),
    (r"device",             {"dimensions": ["deviceCategory"], "metrics": ["sessions", "activeUsers"], "limit": 5}),
    (r"country|region",     {"dimensions": ["country"], "metrics": ["sessions", "activeUsers"], "limit": 20}),
    (r"source|medium",      {"dimensions": ["sessionSource", "sessionMedium"], "metrics": ["sessions", "activeUsers"], "limit": 15}),
    (r"campaign",           {"dimensions": ["sessionCampaignName"], "metrics": ["sessions", "activeUsers"], "limit": 15}),
    (r"conver",             {"dimensions": ["date"], "metrics": ["conversions", "sessions"], "limit": 90}),
    (r"bounce",             {"dimensions": ["date"], "metrics": ["bounceRate", "sessions"], "limit": 90}),
    (r"session|user|visit", {"dimensions": ["date"], "metrics": ["sessions", "activeUsers"], "limit": 90}),
    (r"engagement",         {"dimensions": ["date"], "metrics": ["engagementRate", "averageSessionDuration"], "limit": 90}),
    (r"revenue|ecomm",      {"dimensions": ["date"], "metrics": ["totalRevenue", "transactions"], "limit": 90}),
    (r"event",              {"dimensions": ["eventName"], "metrics": ["eventCount", "sessions"], "limit": 20}),
    (r"landing",            {"dimensions": ["landingPagePlusQueryString"], "metrics": ["sessions", "bounceRate"], "limit": 15}),
]

def _parse_nl_query(question: str) -> dict:
    q = question.lower()
    for pattern, cfg in _NL_PATTERNS:
        if re.search(pattern, q):
            return cfg
    return {"dimensions": ["date"], "metrics": ["sessions", "activeUsers"], "limit": 60}


def _bl_chart(df: pd.DataFrame, chart_type: str, x: str, ys: list[str], title: str) -> go.Figure | None:
    if df.empty or x not in df.columns:
        return None

    if chart_type == "line":
        fig = go.Figure()
        for i, y in enumerate(ys):
            if y not in df.columns:
                continue
            fig.add_trace(go.Scatter(
                x=df[x], y=df[y],
                name=y.replace("_", " ").title(),
                mode="lines+markers",
                line=dict(color=_PALETTE[i % len(_PALETTE)], width=2.5),
                marker=dict(size=5),
            ))
    else:
        fig = go.Figure()
        for i, y in enumerate(ys):
            if y not in df.columns:
                continue
            fig.add_trace(go.Bar(
                x=df[x], y=df[y],
                name=y.replace("_", " ").title(),
                marker_color=_PALETTE[i % len(_PALETTE)],
                marker_line_color="#000", marker_line_width=0.5,
            ))

    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONT, size=12, color="#000"),
        margin=dict(l=40, r=20, t=40, b=28),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=False, linecolor="#000", linewidth=0.5),
        yaxis=dict(gridcolor="#FFE770", gridwidth=0.5, linecolor="#000", linewidth=0.5),
        hoverlabel=dict(bgcolor="#FFDD33", font_size=12, font_family=_FONT, font_color="#000", bordercolor="#000"),
        hovermode="x unified" if chart_type == "line" else "closest",
    )
    return fig


def _auto_chart_from_df(df: pd.DataFrame, title: str) -> go.Figure | None:
    """Infer a suitable chart from whatever columns the ADK agent returned."""
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    # Detect time-series
    if "date" in cols:
        num_cols = [c for c in cols if c != "date" and pd.api.types.is_numeric_dtype(df[c])]
        return _bl_chart(df, "line", "date", num_cols[:2], title)
    # Otherwise bar chart — first col as x, numeric cols as y
    x_col = cols[0]
    num_cols = [c for c in cols[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if num_cols:
        return _bl_chart(df, "bar", x_col, num_cols[:1], title)
    return None


# ── Main render ───────────────────────────────────────────────────────────────

@st.fragment
def render(start_date: str, end_date: str) -> None:
    st.subheader("**Note:** -----------This tab is a work in progress.----------")
    st.subheader("Google Analytics 4 Explorer.")
    st.caption(
        f"Reporting period: **{start_date}** → **{end_date}**  ·  "
        "Connect a GA4 property to explore data and chat with your analytics."
    )

    # ── Work-in-progress notice ───────────────────────────────────────────────
    st.info(
        "**Note:** This tab is a work in progress. "
        "Once we have GA4 property access configured, the tab will be fully active.",
        icon="🚧",
    )

    # ── Library availability check ────────────────────────────────────────────
    if not _GA4_AVAILABLE:
        st.error("**Google Analytics libraries not installed in this environment.**")
        st.markdown(
            """
            Run the following command in your project's virtual environment, then restart Streamlit:

            ```
            .\\bot\\Scripts\\pip install google-analytics-data google-analytics-admin google-adk
            ```

            Or if you're using a global Python install:

            ```
            pip install google-analytics-data google-analytics-admin google-adk
            ```
            """
        )
        st.info(
            "After installing, restart the Streamlit server (`Ctrl+C` then `streamlit run app.py`) "
            "and this tab will activate automatically."
        )
        return

    # ── Connection panel ──────────────────────────────────────────────────────
    with st.container():
        st.markdown("#### 🔗 Connect a GA4 Property")

        props = _list_properties()

        col_sel, col_manual = st.columns([2, 1])
        with col_sel:
            if props:
                options = {f"{p['account']} / {p['property']} ({p['property_id']})": p["property_id"]
                           for p in props}
                chosen = st.selectbox(
                    "Select a GA4 property",
                    ["— pick a property —"] + list(options.keys()),
                    key="ga4_property_selector",
                )
                property_id = options.get(chosen, "")
            else:
                st.caption("No properties auto-discovered. Enter a property ID manually.")
                property_id = ""

        with col_manual:
            manual_id = st.text_input(
                "Or enter Property ID manually",
                value=st.session_state.get("ga4_property_id", ""),
                placeholder="e.g. 123456789",
                key="ga4_manual_id",
            )
            if manual_id.strip():
                property_id = manual_id.strip()

        if property_id:
            st.session_state["ga4_property_id"] = property_id

            # Agent status badge
            agent_badge = (
                '<span style="background:#d4edda;color:#155724;padding:2px 10px;'
                'border-radius:999px;font-size:11px;font-family:Kanit,sans-serif;'
                'font-weight:600;border:1px solid #155724;">🤖 AI Agent active</span>'
                if _GA4_AGENT_OK else
                '<span style="background:#fff3cd;color:#856404;padding:2px 10px;'
                'border-radius:999px;font-size:11px;font-family:Kanit,sans-serif;'
                'font-weight:600;border:1px solid #856404;">⚡ Pattern mode</span>'
            )
            st.markdown(
                f"Connected to property **{property_id}** &nbsp; {agent_badge}",
                unsafe_allow_html=True,
            )
        else:
            st.info("👆 Select or enter a GA4 Property ID above to start exploring data.")
            _render_placeholder()
            return

    st.divider()

    # ── Preset Report Cards ───────────────────────────────────────────────────
    st.markdown("#### 📋 Quick Reports")
    st.caption("Click any card to run a preset report for your selected date range.")

    if "ga4_active_preset" not in st.session_state:
        st.session_state["ga4_active_preset"] = None

    cols1 = st.columns(3)
    for i, preset in enumerate(_PRESETS[:3]):
        with cols1[i]:
            active = st.session_state["ga4_active_preset"] == preset["title"]
            btn_style = (
                "background:#FFDD33;border:1.5px solid #000;" if active
                else "background:#FFFFFF;border:1.5px solid #000;"
            )
            st.markdown(
                f"<div style='{btn_style}border-radius:8px;padding:10px 12px;"
                f"font-family:Kanit,sans-serif;box-shadow:2px 2px 0 0 #000;margin-bottom:4px;'>"
                f"<div style='font-size:18px;'>{preset['icon']}</div>"
                f"<div style='font-weight:600;font-size:13px;'>{preset['title']}</div>"
                f"<div style='font-size:11px;opacity:0.7;'>{preset['desc']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Run", key=f"preset_{i}", width='stretch'):
                st.session_state["ga4_active_preset"] = preset["title"]
                st.rerun()

    cols2 = st.columns(3)
    for i, preset in enumerate(_PRESETS[3:]):
        with cols2[i]:
            active = st.session_state["ga4_active_preset"] == preset["title"]
            btn_style = (
                "background:#FFDD33;border:1.5px solid #000;" if active
                else "background:#FFFFFF;border:1.5px solid #000;"
            )
            st.markdown(
                f"<div style='{btn_style}border-radius:8px;padding:10px 12px;"
                f"font-family:Kanit,sans-serif;box-shadow:2px 2px 0 0 #000;margin-bottom:4px;'>"
                f"<div style='font-size:18px;'>{preset['icon']}</div>"
                f"<div style='font-weight:600;font-size:13px;'>{preset['title']}</div>"
                f"<div style='font-size:11px;opacity:0.7;'>{preset['desc']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Run", key=f"preset_{i+3}", width='stretch'):
                st.session_state["ga4_active_preset"] = preset["title"]
                st.rerun()

    # ── Render active preset ──────────────────────────────────────────────────
    active_preset_name = st.session_state.get("ga4_active_preset")
    if active_preset_name:
        active = next((p for p in _PRESETS if p["title"] == active_preset_name), None)
        if active:
            st.divider()
            st.markdown(f"##### {active['icon']} {active['title']}")
            df = _run_ga4_report(
                property_id=property_id,
                start_date=start_date,
                end_date=end_date,
                dimensions=active["dimensions"],
                metrics=active["metrics"],
                limit=active.get("limit", 20),
            )
            if df.empty:
                st.info("No data returned. Check your property ID and date range.")
            elif active["chart"] == "table":
                st.dataframe(df, width='stretch', hide_index=True)
            else:
                fig = _bl_chart(df, active["chart"], active["x"], active["ys"], active["title"])
                if fig:
                    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
                st.dataframe(df, width='stretch', hide_index=True)

    st.divider()

    # ── Chat interface ────────────────────────────────────────────────────────
    st.markdown("#### 💬 Chat with GA4")

    if _GA4_AGENT_OK:
        st.caption(
            "Powered by the GA4 AI Agent. Ask questions in plain English — the agent "
            "will query the GA4 API and explain the results. "
            "Examples: *'Show me top channels this month'*, "
            "*'How has bounce rate trended?'*, *'Which countries drive the most sessions?'*"
        )
    else:
        st.caption(
            "Pattern mode active (install `google-adk` for full AI). "
            "Ask questions like: *'Sessions by channel'*, *'Top pages'*, *'Bounce rate trend'*."
        )

    # ── Session state init ────────────────────────────────────────────────────
    if "ga4_chat_history" not in st.session_state:
        st.session_state["ga4_chat_history"] = []

    # Unique session IDs for the ADK agent
    if "ga4_agent_user_id" not in st.session_state:
        st.session_state["ga4_agent_user_id"] = f"ga4_user_{uuid.uuid4().hex[:8]}"
    if "ga4_agent_session_id" not in st.session_state:
        st.session_state["ga4_agent_session_id"] = f"ga4_session_{uuid.uuid4().hex[:8]}"
        if _GA4_AGENT_OK:
            try:
                _ga4_create_session(
                    st.session_state["ga4_agent_user_id"],
                    st.session_state["ga4_agent_session_id"],
                )
            except Exception:
                pass

    # ── Chat display ──────────────────────────────────────────────────────────
    for msg in st.session_state["ga4_chat_history"]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                st.markdown(msg["content"], unsafe_allow_html=True)
                if msg.get("df") is not None and not msg["df"].empty:
                    if msg.get("chart") and msg.get("fig") is not None:
                        st.plotly_chart(
                            msg["fig"],
                            width='stretch',
                            config={"displayModeBar": False},
                        )
                    st.dataframe(msg["df"], width='stretch', hide_index=True)

    # ── Chat input ────────────────────────────────────────────────────────────
    question = st.chat_input("Ask a question about your GA4 data…", key="ga4_chat_input")
    if question:
        st.session_state["ga4_chat_history"].append({"role": "user", "content": question})

        # ── ADK Agent path ────────────────────────────────────────────────────
        if _GA4_AGENT_OK:
            with st.spinner("GA4 agent thinking…"):
                try:
                    result = _ga4_agent_chat(
                        user_message=question,
                        user_id=st.session_state["ga4_agent_user_id"],
                        session_id=st.session_state["ga4_agent_session_id"],
                        property_id=property_id,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    reply    = result["text"]
                    last_df  = result["df"]
                    want_chart = result["chart"]
                    fig = _auto_chart_from_df(last_df, question.title()) if (want_chart and last_df is not None) else None

                except Exception as e:
                    reply    = f"Agent error: {e}. Falling back to pattern mode."
                    last_df  = None
                    want_chart = False
                    fig      = None

        # ── Fallback regex pattern path ───────────────────────────────────────
        else:
            with st.spinner("Querying GA4…"):
                cfg = _parse_nl_query(question)
                last_df = _run_ga4_report(
                    property_id=property_id,
                    start_date=start_date,
                    end_date=end_date,
                    dimensions=cfg["dimensions"],
                    metrics=cfg["metrics"],
                    limit=cfg.get("limit", 30),
                )

            chart_type = "line" if cfg["dimensions"] == ["date"] else "bar"
            x_col  = cfg["dimensions"][0]
            y_cols = cfg["metrics"][:2]
            want_chart = True

            if last_df.empty:
                reply      = "No data found for that query. Try a different question or adjust your date range."
                want_chart = False
                fig        = None
            else:
                rows    = len(last_df)
                top_val = last_df[y_cols[0]].iloc[0] if y_cols[0] in last_df.columns else "—"
                reply = (
                    f"Found **{rows}** rows. "
                    f"Top result: **{last_df[x_col].iloc[0]}** "
                    f"with **{y_cols[0]}** = **{top_val:,.0f}**."
                    if pd.api.types.is_numeric_dtype(last_df.get(y_cols[0], pd.Series(dtype=float)))
                    else f"Found **{rows}** rows."
                )
                fig = _bl_chart(last_df, chart_type, x_col, y_cols, question.title())

        st.session_state["ga4_chat_history"].append({
            "role":  "assistant",
            "content": reply,
            "df":    last_df,
            "fig":   fig,
            "chart": want_chart,
        })
        st.rerun()

    if st.session_state["ga4_chat_history"]:
        col_clear, _ = st.columns([1, 5])
        with col_clear:
            if st.button("🗑️ Clear chat", key="ga4_clear_chat"):
                st.session_state["ga4_chat_history"] = []
                # Reset ADK session so next conversation starts fresh
                if _GA4_AGENT_OK:
                    new_sid = f"ga4_session_{uuid.uuid4().hex[:8]}"
                    st.session_state["ga4_agent_session_id"] = new_sid
                    try:
                        _ga4_create_session(
                            st.session_state["ga4_agent_user_id"],
                            new_sid,
                        )
                    except Exception:
                        pass
                st.rerun()


def _render_placeholder():
    """Shown before a property is connected."""
    st.markdown(
        """
        <div style="background:#FFE770;border:1.5px solid #000;border-radius:8px;
          padding:24px 28px;font-family:Kanit,sans-serif;box-shadow:3px 3px 0 0 #000;
          margin-top:12px;">
          <div style="font-size:32px;margin-bottom:8px;">📊</div>
          <div style="font-weight:600;font-size:16px;margin-bottom:6px;">GA4 Explorer</div>
          <div style="font-size:13px;opacity:0.75;line-height:1.6;">
            Once connected, you can:<br>
            · Run preset reports (sessions, channels, pages, devices, countries)<br>
            · Chat with the AI agent — ask anything about your GA4 data in plain English<br>
            · All results respect the date range selected in the sidebar
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
