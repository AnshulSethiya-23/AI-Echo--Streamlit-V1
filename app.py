"""
app.py — Brookfield Dashboard v2 (Streamlit, fragment-scoped)

Run:    streamlit run app.py

What's different vs v1:
  * Each tab is decorated with @st.fragment so interactions inside one tab
    don't rerun the others (date input still triggers a full rerun by design).
  * .streamlit/config.toml carries the theme so app.py stays clean.
  * Executive Summary pie chart is click-to-filter via streamlit-plotly-events.
  * st.metric cards are styled via streamlit-extras for a tighter look.
"""

import os
import base64
from dotenv import load_dotenv
load_dotenv()  # loads GCP_PROJECT_ID and BQ_DATASET from .env

# ── Credentials bootstrap ─────────────────────────────────────────────────────
# Mirrors the standalone chatbot pattern. On Cloud Run, reads a base64-encoded
# SA key and writes it to a temp file so all google_auth_default() calls across
# the process (chatbot agent, insights) automatically use the same credentials.
# Locally, falls through to ADC (gcloud auth application-default login).
encoded_credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_FUNNEL_DATA_BASE64")
if encoded_credentials:
    decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
    with open("/tmp/sa_key.json", "w") as f:
        f.write(decoded_credentials)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/sa_key.json"
# else: no base64 key → ADC picks up credentials automatically (local dev)

os.environ["GOOGLE_CLOUD_PROJECT"]      = "generative-insights-poc-bi"
os.environ["GOOGLE_CLOUD_LOCATION"]     = "us-central1"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"

import streamlit as st
import streamlit.components.v1 as components
from datetime import date, timedelta

try:
    from streamlit_extras.metric_cards import style_metric_cards
except ImportError:
    style_metric_cards = None

from tabs import (
    tab_exec_summary,
    tab_search,
    tab_social,
    tab_programmatic,
    tab_insights,
    tab_chatbot,
    tab_ga4,
    tab_forecast,
)


# Page config -----------------------------------------------------------------
st.set_page_config(
    page_title="Brookfield Dashboard v2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brainlabs brand CSS ───────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* ── Kanit font ── */
        @import url('https://fonts.googleapis.com/css2?family=Kanit:ital,wght@0,300;0,400;0,500;0,600;0,700;1,600;1,700&display=swap');

        /* ── Material Icons: nuclear hide ───────────────────────────────────
           Covers span, i, and the toggle-icon container regardless of version */
        span.material-icons,
        span.material-icons-round,
        span.material-icons-outlined,
        span.material-icons-sharp,
        i.material-icons,
        i.material-icons-round,
        [data-testid="stExpanderToggleIcon"],
        [data-testid="stExpanderToggleIcon"] * {
            display: none !important;
        }

        /* ── Sidebar collapse buttons — hide both variants ───────────────────*/
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapseButton"],
        section[data-testid="stSidebarCollapsedControl"],
        button[data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }

        /* Apply Kanit globally */
        html, body, [class*="st-"], .stMarkdown, .stMetric,
        .stTabs, button, label, p, h1, h2, h3, h4, h5, h6 {
            font-family: 'Kanit', sans-serif !important;
        }

        #MainMenu { visibility: hidden; }
        footer    { visibility: hidden; }

        /* ── Main area — cream background ── */
        .stApp { background-color: #FFFEF7; }
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 1rem !important;
            background-color: #FFFEF7;
        }

        /* ── Tabs — BL yellow active indicator ── */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            border-bottom: 2px solid #FFDD33;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0;
            font-family: 'Kanit', sans-serif !important;
            font-weight: 600;
            font-size: 14px;
            color: #000000;
            background-color: #FFE770;
            padding: 8px 18px;
        }
        .stTabs [aria-selected="true"] {
            background-color: #FFDD33 !important;
            color: #000000 !important;
            border-bottom: 3px solid #000000 !important;
        }

        /* ── Sidebar — BL Yellow 2 background, black text ── */
        [data-testid="stSidebar"] {
            background-color: #FFE770;
            border-right: 2px solid #000000;
        }
        [data-testid="stSidebar"] * {
            color: #000000 !important;
            font-family: 'Kanit', sans-serif !important;
        }
        [data-testid="stSidebar"] .stDateInput label {
            color: #000000 !important;
            font-weight: 600;
        }

        /* ── Sidebar buttons — pill-shaped, black border, BL yellow hover ── */
        [data-testid="stSidebar"] .stButton > button {
            background-color: #FFFFFF !important;
            color: #000000 !important;
            border: 1.5px solid #000000 !important;
            border-radius: 999px !important;
            font-family: 'Kanit', sans-serif !important;
            font-weight: 500 !important;
            font-size: 13px !important;
            padding: 6px 14px !important;
            transition: background-color 0.15s ease, border-color 0.15s ease;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background-color: #FFDD33 !important;
            border-color: #000000 !important;
        }

        /* ── st.metric cards — BL yellow left-accent, cream background ── */
        [data-testid="stMetric"] {
            background-color: #FFFFFF;
            border-left: 4px solid #FFDD33;
            border-radius: 8px;
            padding: 12px 16px !important;
            box-shadow: 2px 2px 0 0 #000000;
            font-family: 'Kanit', sans-serif !important;
        }
        [data-testid="stMetricLabel"] {
            font-weight: 600 !important;
            font-size: 13px !important;
            color: #000000 !important;
        }
        [data-testid="stMetricValue"] {
            font-weight: 700 !important;
            color: #000000 !important;
        }
        [data-testid="stMetricDelta"] { font-size: 12px !important; }

        /* ── Dividers ── */
        hr { border-color: #000000 !important; opacity: 0.15; }

        /* ── Reduce vertical whitespace between consecutive charts only ── */
        /* Scoped to plotly chart wrappers — NOT to all vertical blocks,        */
        /* which would crush dropdown menus and cause text overlap.             */
        [data-testid="stPlotlyChart"] { margin-bottom: 0px !important; }

        /* ── Ensure Streamlit dropdown menus always render on top ── */
        [data-baseweb="popover"],
        [data-baseweb="menu"],
        ul[role="listbox"] {
            z-index: 9999 !important;
        }

        /* ── Dataframe table — BL yellow header ── */
        .stDataFrame thead tr th {
            background-color: #FFDD33 !important;
            color: #000000 !important;
            font-family: 'Kanit', sans-serif !important;
            font-weight: 600 !important;
        }

        /* ── Subheaders & captions ── */
        .stMarkdown h3 { font-family: 'Kanit', sans-serif !important; font-weight: 600; }
        .stCaption   { color: #000000 !important; opacity: 0.6; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── JS patch via same-origin iframe ──────────────────────────────────────────
# st.markdown <script> tags are stripped by React's renderer.
# components.html() runs inside a same-origin iframe, so window.parent.document
# IS accessible. MutationObserver re-runs after every Streamlit re-render.
components.html(
    """
    <script>
    (function() {
        var p = window.parent.document;

        var ICON_SEL = [
            'span.material-icons',
            'span.material-icons-round',
            'span.material-icons-outlined',
            'span.material-icons-sharp',
            'i.material-icons',
            'i.material-icons-round',
            '[data-testid="stExpanderToggleIcon"]',
        ].join(',');

        var HIDE_SEL = [
            '[data-testid="stSidebarCollapseButton"]',
            '[data-testid="stSidebarCollapsedControl"]',
            '[data-testid="collapsedControl"]',
        ].join(',');

        // Regex for known Material Icons ligature names (snake_case, no spaces).
        // Includes chat-avatar icons: "face" (user) and "smart_toy" / "art_" (assistant).
        var ICON_TEXT_RE = /^(keyboard_arrow|keyboard_double_arrow|arrow_drop|arrow_forward|arrow_back|arrow_right|arrow_left|arrow_upward|arrow_downward|expand_more|expand_less|chevron_right|chevron_left|more_vert|fullscreen_|unfold_|navigate_|first_page|last_page|face|smart_toy|art_|person|account_circle|psychology|sentiment_)/ ;

        function scanTextNodes() {
            var walker = p.createTreeWalker(
                p.documentElement,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            var node;
            while ((node = walker.nextNode())) {
                var txt = node.nodeValue.trim();
                // Must match icon pattern and contain no spaces (avoid real content)
                if (txt && !txt.includes(' ') && ICON_TEXT_RE.test(txt)) {
                    var parent = node.parentElement;
                    if (parent) {
                        parent.style.setProperty('display', 'none', 'important');
                    }
                }
            }
        }

        function patch() {
            p.querySelectorAll(ICON_SEL).forEach(function(el) {
                el.style.setProperty('display', 'none', 'important');
            });
            p.querySelectorAll(HIDE_SEL).forEach(function(el) {
                el.style.setProperty('display', 'none', 'important');
            });
            scanTextNodes();
        }

        patch();
        new MutationObserver(patch).observe(p.documentElement,
            { childList: true, subtree: true });
    })();
    </script>
    """,
    height=0,
    scrolling=False,
)


# ── JS: tab-aware sidebar sections ───────────────────────────────────────────
# Three sections are toggled based on the active tab index:
#   Date filter   (filter-start / filter-end)   → visible on tabs 0-3, 6, 7
#   Insights      (insights-start / insights-end) → visible only on tab 4
#   Chatbot       (chatbot-start / chatbot-end)   → visible only on tab 5
components.html(
    """
    <script>
    (function() {
        var p = window.parent.document;

        function toggleSection(startAttr, endAttr, show) {
            var startEl = p.querySelector('[data-bl="' + startAttr + '"]');
            var endEl   = p.querySelector('[data-bl="' + endAttr   + '"]');
            if (!startEl || !endEl) return;

            var sidebarContent = p.querySelector('[data-testid="stSidebarContent"]');
            if (!sidebarContent) return;
            var topBlock = sidebarContent.querySelector('[data-testid="stVerticalBlock"]');
            if (!topBlock) return;

            var children   = Array.from(topBlock.children);
            var startChild = children.find(function(c) { return c.contains(startEl); });
            var endChild   = children.find(function(c) { return c.contains(endEl);   });
            if (!startChild || !endChild) return;

            var s = children.indexOf(startChild);
            var e = children.indexOf(endChild);
            if (s < 0 || e < 0) return;

            children.slice(s, e + 1).forEach(function(child) {
                child.style.setProperty('display', show ? '' : 'none', 'important');
            });
        }

        function updateSidebar() {
            var tabs = p.querySelectorAll('[data-baseweb="tab"]');
            var activeIdx = -1;
            tabs.forEach(function(t, i) {
                if (t.getAttribute('aria-selected') === 'true') activeIdx = i;
            });
            if (activeIdx === -1) activeIdx = 0; // default: Executive Summary

            toggleSection('filter-start',   'filter-end',   activeIdx !== 4 && activeIdx !== 5);
            toggleSection('insights-start', 'insights-end', activeIdx === 4);
            toggleSection('chatbot-start',  'chatbot-end',  activeIdx === 5);
        }

        updateSidebar();
        new MutationObserver(updateSidebar).observe(
            p.documentElement, { childList: true, subtree: true }
        );
    })();
    </script>
    """,
    height=0,
    scrolling=False,
)


# Sidebar ---------------------------------------------------------------------
with st.sidebar:
    # BL logo
    st.image(
        "https://raw.githubusercontent.com/brainlabs-design/brand-assets/main/25-Brainlabs-Primary-Color-Logo%20(6).svg",
        width=140,
    )
    st.markdown("---")
    # ── Sentinel: JS uses this to find the start of the date-filter block ──
    st.markdown('<span data-bl="filter-start" style="display:none"></span>', unsafe_allow_html=True)
    st.markdown("### Filters")

    today = date.today()

    # Init filter state (read by date_input via value=, written by quick-range buttons)
    if "start_date" not in st.session_state:
        st.session_state.start_date = today - timedelta(days=29)
    if "end_date" not in st.session_state:
        st.session_state.end_date = today

    # Quick range buttons FIRST so a click updates state before the widgets render below
    st.markdown("**Quick ranges**")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Last 7d", width='stretch'):
            st.session_state.start_date = today - timedelta(days=6)
            st.session_state.end_date = today
            st.rerun()
        if st.button("Last 30d", width='stretch'):
            st.session_state.start_date = today - timedelta(days=29)
            st.session_state.end_date = today
            st.rerun()
    with c2:
        if st.button("Last 90d", width='stretch'):
            st.session_state.start_date = today - timedelta(days=89)
            st.session_state.end_date = today
            st.rerun()
        if st.button("This month", width='stretch'):
            st.session_state.start_date = today.replace(day=1)
            st.session_state.end_date = today
            st.rerun()

    st.divider()

    # Bind widgets to value=, no key= so we can keep writing to state from buttons
    start_date = st.date_input(
        "Start date",
        value=st.session_state.start_date,
        max_value=today,
    )
    end_date = st.date_input(
        "End date",
        value=st.session_state.end_date,
        max_value=today,
    )
    st.session_state.start_date = start_date
    st.session_state.end_date = end_date

    if start_date > end_date:
        st.error("Start date must be before end date.")
        st.stop()

    st.divider()
    st.markdown(
        "<div style='font-family:Kanit,sans-serif;font-size:12px;color:#000000;opacity:0.6;'>Powered by <strong>brainlabs</strong> × Brookfield</div>",
        unsafe_allow_html=True,
    )


start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

# Compute and display prior period in sidebar
_delta_days = (end_date - start_date).days
_prior_end = start_date - timedelta(days=1)
_prior_start = _prior_end - timedelta(days=_delta_days)

with st.sidebar:
    st.markdown(
        f"""
        <div style='font-family:Kanit,sans-serif;font-size:12px;margin-top:-6px;'>
          <div style='font-weight:600;'>📅 Reporting period</div>
          <div style='color:#000;opacity:0.85;'>{start_str} → {end_str}</div>
          <div style='font-weight:600;margin-top:6px;'>📅 Prior period</div>
          <div style='color:#000;opacity:0.65;'>{_prior_start.strftime('%Y-%m-%d')} → {_prior_end.strftime('%Y-%m-%d')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # ── Sentinel: JS uses this to find the end of the date-filter block ──
    st.markdown('<span data-bl="filter-end" style="display:none"></span>', unsafe_allow_html=True)


# ── Insights filters sidebar section ─────────────────────────────────────────
_INSIGHT_CHANNEL_ORDER = ["executive", "Search", "Social", "programmatic"]
_INSIGHT_CHANNEL_LABELS = {
    "executive":    "📊 Executive Summary",
    "Search":       "🔍 Search",
    "Social":       "📣 Social",
    "programmatic": "🖥️ Programmatic",
}

with st.sidebar:
    st.markdown('<span data-bl="insights-start" style="display:none"></span>', unsafe_allow_html=True)
    st.markdown("### 💡 Insights Filters")

    st.selectbox(
        "Comparison type",
        options=["All", "MoM", "QoQ", "YoY"],
        index=1,
        key="insights_comp_type",
        help="Filter insights by period comparison.",
    )
    st.selectbox(
        "Channel",
        options=["All"] + _INSIGHT_CHANNEL_ORDER,
        format_func=lambda c: _INSIGHT_CHANNEL_LABELS.get(c, c) if c != "All" else "All Channels",
        key="insights_channel",
        help="Filter by a specific channel.",
    )

    # Run-date options are populated by the tab fragment after its BQ call.
    # On first load only "Latest" is available; options expand on the next rerun.
    _run_date_opts = ["Latest"] + st.session_state.get("insights_run_dates_options", [])
    # Guard: if a previously stored value is no longer in the new option list, reset.
    if st.session_state.get("insights_run_date", "Latest") not in _run_date_opts:
        st.session_state["insights_run_date"] = "Latest"
    st.selectbox(
        "Report date",
        options=_run_date_opts,
        key="insights_run_date",
        help="Select a specific insight generation date, or Latest.",
    )

    st.markdown('<span data-bl="insights-end" style="display:none"></span>', unsafe_allow_html=True)


# ── Chatbot suggestions sidebar section ───────────────────────────────────────
_CHATBOT_SIDEBAR_EXAMPLES = [
    "How did Search perform last month vs the month before?",
    "Show social spend trend over the last 3 months",
    "Compare Brand vs NonBrand CTR for the last quarter",
    "Which programmatic campaigns had the highest CPM last month?",
    "Top 10 keywords by internal link clicks in the last month?",
    "Show a chart of monthly impressions by channel",
]

with st.sidebar:
    st.markdown('<span data-bl="chatbot-start" style="display:none"></span>', unsafe_allow_html=True)
    st.markdown("### 🤖 Try Asking")
    st.markdown(
        "<div style='font-size:12px; color:#000; opacity:0.65; margin-bottom:8px;'>"
        "Click a question to send it to the chatbot.</div>",
        unsafe_allow_html=True,
    )
    for i, q in enumerate(_CHATBOT_SIDEBAR_EXAMPLES):
        if st.button(q, key=f"sidebar_chatbot_ex_{i}", width="stretch"):
            st.session_state.chatbot_pending = q

    st.divider()

    # Controls that used to live in the tab header
    _sb_c1, _sb_c2 = st.columns(2)
    with _sb_c1:
        st.toggle("Show SQL", value=False, key="chatbot_show_sql")
    with _sb_c2:
        if st.button("🗑️ New chat", width="stretch", key="sidebar_chatbot_new_chat"):
            st.session_state.chatbot_new_chat_requested = True

    st.markdown('<span data-bl="chatbot-end" style="display:none"></span>', unsafe_allow_html=True)


# Header ----------------------------------------------------------------------
st.title("Brookfield Performance Dashboard")
st.caption(f"Showing data from **{start_str}** to **{end_str}**  ·  v2")


# Tabs ------------------------------------------------------------------------
tabs = st.tabs([
    "📋 Executive Summary",
    "🔍 Search",
    "📱 Social",
    "📡 Programmatic",
    "💡 Insights",
    "🤖 Chatbot",
    "📊 Google Analytics",
    "🔮 Forecasting",
])

with tabs[0]:
    tab_exec_summary.render(start_str, end_str)
with tabs[1]:
    tab_search.render(start_str, end_str)
with tabs[2]:
    tab_social.render(start_str, end_str)
with tabs[3]:
    tab_programmatic.render(start_str, end_str)
with tabs[4]:
    tab_insights.render(start_str, end_str)
with tabs[5]:
    tab_chatbot.render(start_str, end_str)
with tabs[6]:
    tab_ga4.render(start_str, end_str)
with tabs[7]:
    tab_forecast.render(start_str, end_str)


# Style metric cards globally (no-op if streamlit-extras isn't installed) -----
if style_metric_cards is not None:
    style_metric_cards(
        background_color="#FFFFFF",
        border_left_color="#FFDD33",
        border_color="#000000",
        border_radius_px=8,
        box_shadow=False,
    )
