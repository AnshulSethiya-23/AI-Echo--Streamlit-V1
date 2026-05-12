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

        // Regex for known Material Icons ligature names (snake_case, no spaces)
        var ICON_TEXT_RE = /^(keyboard_arrow|keyboard_double_arrow|arrow_drop|arrow_forward|arrow_back|arrow_right|arrow_left|arrow_upward|arrow_downward|expand_more|expand_less|chevron_right|chevron_left|more_vert|fullscreen_|unfold_|navigate_|first_page|last_page)/;

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


# Sidebar ---------------------------------------------------------------------
with st.sidebar:
    # BL logo
    st.image(
        "https://raw.githubusercontent.com/brainlabs-design/brand-assets/main/25-Brainlabs-Primary-Color-Logo%20(6).svg",
        width=140,
    )
    st.markdown("---")
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
