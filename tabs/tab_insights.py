"""
tabs/tab_insights.py — Automated Insights tab for the Brookfield dashboard.

Reads pre-generated insights from the BigQuery table
`funnel-data.brookfield_dashboard.Automated_insights` via
insights/brookfield_automated_insights.py.

No LLM is called on page load — insights are read from BQ.
The optional "Regenerate" button triggers the full pipeline (queries BQ + Gemini).

Session-state keys are prefixed with `insights_` to avoid conflicts with
other dashboard tabs.
"""

import re
import sys
import os
import streamlit as st

# ── Path setup — allows `from brookfield_automated_insights import ...` ────
_INSIGHTS_DIR = os.path.join(os.path.dirname(__file__), "..", "insights")
if _INSIGHTS_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_INSIGHTS_DIR))

from brookfield_automated_insights import (   # noqa: E402
    fetch_insights,
    get_available_run_dates,
    run_insights_pipeline,
)

# ── Channel display config ──────────────────────────────────────────────────
_CHANNEL_ORDER = ["executive", "Search", "Social", "programmatic"]
_CHANNEL_LABELS = {
    "executive":     "📊 Executive Summary",
    "Search":        "🔍 Search",
    "Social":        "📣 Social",
    "programmatic":  "🖥️ Programmatic",
}
_CHANNEL_COLORS = {
    "executive":    "#80DBFF",  # Brainlabs blue
    "Search":       "#FFDD33",  # Brainlabs yellow
    "Social":       "#d4edda",  # soft green
    "programmatic": "#f3e8ff",  # soft purple
}
_COMPARISON_LABELS = {
    "MoM": "Month over Month",
    "QoQ": "Quarter over Quarter",
    "YoY": "Year over Year",
}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_fetch(comparison_type, channel, run_date, latest_only):
    """Cache BQ reads for 5 minutes to avoid repeated round-trips."""
    return fetch_insights(
        comparison_type=comparison_type,
        channel=channel,
        run_date=run_date,
        latest_only=latest_only,
    )


@st.cache_data(ttl=300, show_spinner=False)
def _cached_run_dates():
    return get_available_run_dates()


def _render_insight_card(row) -> None:
    """Render one insight card for a single channel × period row."""
    channel   = row["channel"]
    comp_type = row["comparison_type"]
    curr_lbl  = row.get("current_label", "Current")
    prev_lbl  = row.get("previous_label", "Previous")
    insight   = row.get("insight", "No insight text available.")
    # Collapse 2+ consecutive blank lines → single newline to avoid huge gaps
    insight   = re.sub(r'\n{2,}', '\n', insight.strip())
    run_date  = row.get("run_date", "")

    header_color = _CHANNEL_COLORS.get(channel, "#eeeeee")
    channel_label = _CHANNEL_LABELS.get(channel, channel)

    st.markdown(
        f"""
        <div style="
            background: #ffffff;
            border: 1px solid #e0e0e0;
            border-top: 4px solid {header_color};
            border-radius: 10px;
            padding: 18px 20px 16px 20px;
            margin-bottom: 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;
                        margin-bottom:10px;">
                <span style="font-size:16px; font-weight:700; color:#1a1a1a;">
                    {channel_label}
                </span>
                <span style="
                    background:{header_color};
                    color:#000;
                    font-size:11px;
                    font-weight:600;
                    padding:3px 10px;
                    border-radius:20px;
                    font-family:monospace;
                ">
                    {_COMPARISON_LABELS.get(comp_type, comp_type)}
                </span>
            </div>
            <div style="font-size:12px; color:#475657; margin-bottom:12px;">
                <b>{curr_lbl}</b> vs <b>{prev_lbl}</b>
                &nbsp;·&nbsp; Generated: {run_date}
            </div>
            <div style="
                font-size:14px;
                color:#1a1a1a;
                line-height:1.65;
                white-space:pre-wrap;
            ">{insight}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment
def render(start_date: str, end_date: str) -> None:
    """Render the Automated Insights tab inside the dashboard."""

    st.subheader("Automated Insights")
    st.caption("AI-generated insights from campaign data")

    st.markdown(
        "<hr style='border:none; border-top:2px solid #FFDD33; margin:8px 0 16px 0;'/>",
        unsafe_allow_html=True,
    )

    # ── Read filter values from sidebar (widgets live in app.py sidebar) ────────
    comp_type_sel = st.session_state.get("insights_comp_type", "MoM")
    channel_sel   = st.session_state.get("insights_channel", "All")
    run_date_sel  = st.session_state.get("insights_run_date", "Latest")

    # Fetch available run dates and push them to the sidebar selectbox options.
    # The sidebar renders before this fragment, so the dates become available on
    # the following rerun (one-rerun delay — "Latest" is always a valid default).
    available_dates = _cached_run_dates()
    if available_dates:
        st.session_state["insights_run_dates_options"] = available_dates

    # ── Resolve filter values ────────────────────────────────────
    comp_type_arg  = None if comp_type_sel  == "All"    else comp_type_sel
    channel_arg    = None if channel_sel    == "All"    else channel_sel
    run_date_arg   = None if run_date_sel   == "Latest" else run_date_sel
    latest_only    = run_date_sel == "Latest"

    # ── Load insights from BQ ────────────────────────────────────
    with st.spinner("Fetching insights from BigQuery..."):
        try:
            df = _cached_fetch(
                comparison_type=comp_type_arg,
                channel=channel_arg,
                run_date=run_date_arg,
                latest_only=latest_only,
            )
        except Exception as e:
            st.error(f"Could not fetch insights: {e}")
            df = None

    # ── Empty state ──────────────────────────────────────────────
    if df is None or df.empty:
        st.markdown(
            """
            <div style="
                background: #fffbea;
                border: 1.5px dashed #FFDD33;
                border-radius: 10px;
                padding: 32px;
                text-align: center;
                color: #475657;
                margin-top: 8px;
            ">
                <div style="font-size:32px; margin-bottom:8px;">💡</div>
                <b>No insights found for the selected filters.</b><br/>
                <span style="font-size:13px;">
                    Insights are generated by running the pipeline. Use the
                    <b>Regenerate Insights</b> button below to generate fresh insights,
                    or adjust your filters above.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:
        # ── Summary banner ───────────────────────────────────────
        unique_channels = df["channel"].nunique()
        run_date_shown  = df["run_date"].astype(str).max()
        st.markdown(
            f"""
            <div style="
                background: #f0faff;
                border-left: 4px solid #80DBFF;
                border-radius: 6px;
                padding: 10px 16px;
                margin-bottom: 16px;
                font-size: 13px;
                color: #1a1a1a;
            ">
                Showing <b>{len(df)}</b> insight block(s) across
                <b>{unique_channels}</b> channel(s) ·
                Latest run: <b>{run_date_shown}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Render insight cards ─────────────────────────────────
        if comp_type_arg:
            # Single comparison type — render channels in order
            ordered_channels = [
                c for c in _CHANNEL_ORDER
                if channel_arg in (None, c) or channel_arg is None
            ]
            for ch in ordered_channels:
                ch_rows = df[df["channel"] == ch]
                for _, row in ch_rows.iterrows():
                    _render_insight_card(row)
        else:
            # Multiple comparison types — group by comparison type, then channel
            for comp in ["MoM", "QoQ", "YoY"]:
                comp_rows = df[df["comparison_type"] == comp]
                if comp_rows.empty:
                    continue
                st.markdown(
                    f"<h4 style='color:#000; margin-top:24px; margin-bottom:4px;'>"
                    f"{_COMPARISON_LABELS.get(comp, comp)}</h4>"
                    f"<hr style='border:none; border-top:1px solid #FFDD33; margin-bottom:14px;'/>",
                    unsafe_allow_html=True,
                )
                ordered = [
                    c for c in _CHANNEL_ORDER if c in comp_rows["channel"].values
                ]
                # Include any channels not in _CHANNEL_ORDER
                ordered += [
                    c for c in comp_rows["channel"].unique() if c not in ordered
                ]
                for ch in ordered:
                    ch_rows = comp_rows[comp_rows["channel"] == ch]
                    for _, row in ch_rows.iterrows():
                        _render_insight_card(row)

    # ── Regenerate section ───────────────────────────────────────
    st.markdown(
        "<hr style='border:none; border-top:1px solid #e0e0e0; margin:24px 0 16px 0;'/>",
        unsafe_allow_html=True,
    )

    with st.expander("Regenerate Insights (advanced)", expanded=False):
        st.markdown(
            "<div style='font-size:13px; color:#475657; margin-bottom:12px;'>"
            "Runs the full pipeline — queries BigQuery and calls Gemini on Vertex AI "
            "to generate fresh insights. This may take several minutes and will "
            "incur LLM costs. Use sparingly."
            "</div>",
            unsafe_allow_html=True,
        )

        regen_col1, regen_col2 = st.columns(2)
        with regen_col1:
            regen_channels = st.multiselect(
                "Channels to regenerate",
                options=_CHANNEL_ORDER,
                default=_CHANNEL_ORDER,
                format_func=lambda c: _CHANNEL_LABELS.get(c, c),
                key="insights_regen_channels",
            )
        with regen_col2:
            regen_comp_types = st.multiselect(
                "Comparison types",
                options=["MoM", "QoQ", "YoY"],
                default=["MoM"],
                key="insights_regen_comp_types",
            )

        if st.button(
            "🔄 Regenerate Now",
            type="primary",
            width='content',
            key="insights_regen_btn",
            disabled=(not regen_channels or not regen_comp_types),
        ):
            progress = st.progress(0, text="Starting pipeline...")
            status   = st.empty()
            try:
                total_jobs = len(regen_channels) * len(regen_comp_types)
                status.info(
                    f"Running {total_jobs} insight job(s) across "
                    f"{len(regen_channels)} channel(s) × "
                    f"{len(regen_comp_types)} comparison type(s)…"
                )
                results = run_insights_pipeline(
                    channels=regen_channels,
                    comparison_types=regen_comp_types,
                )
                progress.progress(100, text="Done")
                status.success(
                    f"✅ {len(results)} insight block(s) generated and saved to BigQuery. "
                    f"Refresh the page to see updated insights."
                )
                # Bust cache so next load picks up fresh data
                _cached_fetch.clear()
                _cached_run_dates.clear()
            except Exception as regen_err:
                import traceback
                progress.empty()
                st.error(
                    f"Pipeline failed: {regen_err}\n\n"
                    f"```\n{traceback.format_exc()}\n```"
                )
