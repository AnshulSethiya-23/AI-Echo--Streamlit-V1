import uuid
import os
import base64
import streamlit as st
from streamlit_mic_recorder import mic_recorder
from google.cloud import speech
from google.auth import default as google_auth_default
from google.oauth2 import service_account
from google.auth import compute_engine
from google.api_core.client_options import ClientOptions
from agent import chat, create_session
from charts import ai_chart
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ────────────────────────────────────────────
# Cloud Run: reads base64-encoded service account key from env var.
# Local dev:  falls through to ADC (gcloud auth application-default login).
encoded_credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_FUNNEL_DATA_BASE64")
if encoded_credentials:
    decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
    with open("temp.json", "w") as f:
        f.write(decoded_credentials)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "temp.json"
# else: no base64 key → ADC picks up credentials automatically (local dev)

os.environ["GOOGLE_CLOUD_PROJECT"]      = "generative-insights-poc-bi"
os.environ["GOOGLE_CLOUD_LOCATION"]     = "us-central1"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
 
# ── Logo Configuration ─────────────────────────────────────
# Place logo files in the same folder as app.py in your repo
# Accepts: local filename (e.g. "logo.png") or direct image URL
#
# Repo structure:
#   your-repo/
#   ├── app.py
#   ├── logo.png            ← client logo (white — shown on dark bg)
#   └── brainlabs_logo.png  ← Brainlabs logo

CLIENT_LOGO    = "logo.png"
BRAINLABS_LOGO = "brainlabs_logo.png"


def load_logo(source: str):
    """Returns a base64 data URL for local files, direct URL as-is, or None."""
    if source.startswith("http://") or source.startswith("https://"):
        return source
    elif os.path.exists(source):
        with open(source, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        ext = source.rsplit(".", 1)[-1].lower()
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "svg": "image/svg+xml",
            "gif": "image/gif",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{data}"
    return None


# ── Page config ────────────────────────────────────────────
st.set_page_config(
    page_title="Brookfield Marketing Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brainlabs color scheme ─────────────────────────────────
# Primary:   #FFDD33 (yellow), #80DBFF (blue)
# Neutral:   #ffffff, #FFFCEB (warm white)
# Text:      #000000, #475657 (grey matter)
st.markdown("""
<style>

/* ── Global background (light mode) ── */
.stApp {
    background-color: #FFFCEB;
}

/* ── Sidebar (light mode) ── */
section[data-testid="stSidebar"] {
    background-color: #ffffff;
    border-right: 2px solid #FFDD33;
}

/* ── Sidebar text (light mode) ── */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] div,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] label {
    color: #475657;
}

/* ── Sidebar example question buttons ── */
section[data-testid="stSidebar"] .stButton > button {
    background-color: #ffffff;
    border: 1px solid #FFDD33;
    color: #475657;
    border-radius: 8px;
    font-size: 12px;
    text-align: left;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #FFDD33;
    color: #000000;
    border-color: #FFDD33;
}

/* ── Page title ── */
h1 { color: #000000 !important; }

/* ── Captions and muted text ── */
.stCaption, small { color: #475657 !important; }

/* ── Tool call badges ── */
.tool-badge {
    display: inline-block;
    background: #80DBFF;
    color: #000000;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    margin: 2px;
    font-family: monospace;
}

/* ── Info box (Heard: ...) ── */
div[data-testid="stInfo"] {
    background-color: #FFFCEB;
    border-left: 4px solid #FFDD33;
    color: #475657;
}

/* ── Warning box (Could not transcribe) — readable in all themes ── */
div[data-testid="stWarning"],
div[data-testid="stWarning"] *,
div[data-testid="stWarning"] p,
div[data-testid="stWarning"] span,
div[data-testid="stWarning"] div,
[data-testid="stWarning"] {
    color: #5a4000 !important;
    background-color: #fff3cd !important;
}

/* ── Chat input bar ── */
div[data-testid="stChatInput"] {
    border: 1.5px solid #FFDD33 !important;
    border-radius: 12px !important;
    background: #ffffff !important;
}

/* ── Mic button — idle (yellow) ── */
div[data-testid="stVerticalBlock"] button[title="Start recording"] {
    width: 100% !important;
    height: 42px !important;
    border-radius: 8px !important;
    background: #FFDD33 !important;
    color: #000000 !important;
    font-size: 15px !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(255,221,51,0.4) !important;
    cursor: pointer !important;
    font-weight: 500 !important;
}

/* ── Mic button — recording (blue + pulse) ── */
div[data-testid="stVerticalBlock"] button[title="Stop recording"] {
    width: 100% !important;
    height: 42px !important;
    border-radius: 8px !important;
    background: #80DBFF !important;
    color: #000000 !important;
    font-size: 15px !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(128,219,255,0.4) !important;
    cursor: pointer !important;
    font-weight: 500 !important;
    animation: pulse 1.2s infinite !important;
}
@keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(128,219,255,0.6); }
    70%  { box-shadow: 0 0 0 8px rgba(128,219,255,0); }
    100% { box-shadow: 0 0 0 0 rgba(128,219,255,0); }
}

/* ── Expanders ── */
div[data-testid="stExpander"] {
    border: 1px solid #FFDD33 !important;
    border-radius: 8px !important;
}

/* ════════════════════════════════════════════
   ALWAYS-DARK TEXT — keeps text readable on
   the forced light (#FFFCEB) background
   regardless of System / Light / Dark mode.
   ════════════════════════════════════════════ */

/* Chat message content */
[data-testid="stChatMessageContent"],
[data-testid="stChatMessageContent"] p,
[data-testid="stChatMessageContent"] li,
[data-testid="stChatMessageContent"] ul,
[data-testid="stChatMessageContent"] ol,
[data-testid="stChatMessageContent"] strong,
[data-testid="stChatMessageContent"] em,
[data-testid="stChatMessageContent"] h1,
[data-testid="stChatMessageContent"] h2,
[data-testid="stChatMessageContent"] h3,
[data-testid="stChatMessageContent"] h4,
[data-testid="stChatMessageContent"] td,
[data-testid="stChatMessageContent"] th,
[data-testid="stChatMessageContent"] span {
    color: #1a1a1a !important;
}

/* General markdown blocks in main area */
.main .stMarkdown p,
.main .stMarkdown li,
.main .stMarkdown strong,
.main .stMarkdown em,
.main .stMarkdown h1,
.main .stMarkdown h2,
.main .stMarkdown h3,
.main .stMarkdown h4,
.main .stMarkdown td,
.main .stMarkdown th,
.main .stMarkdown span {
    color: #1a1a1a !important;
}

/* Expander labels and inner content */
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpanderDetails"] p,
[data-testid="stExpanderDetails"] li,
[data-testid="stExpanderDetails"] td,
[data-testid="stExpanderDetails"] th {
    color: #1a1a1a !important;
}

/* Headings always dark */
h1, h2, h3, h4, h5, h6 {
    color: #000000 !important;
}

/* Captions always readable */
.stCaption, small {
    color: #475657 !important;
}

/* Sidebar text always dark (sidebar has white bg) */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] div,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: #475657 !important;
}

/* "Try asking:" bold label */
section[data-testid="stSidebar"] .stMarkdown strong {
    color: #000000 !important;
}

/* Toggle label — cover all Streamlit DOM variants */
section[data-testid="stSidebar"] .stToggle label,
section[data-testid="stSidebar"] .stToggle p,
section[data-testid="stSidebar"] .stToggle span,
section[data-testid="stSidebar"] [data-testid="stToggle"] label,
section[data-testid="stSidebar"] [data-testid="stToggle"] p,
section[data-testid="stSidebar"] [data-testid="stToggle"] span,
section[data-testid="stSidebar"] label[data-testid="stWidgetLabel"],
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] span,
section[data-testid="stSidebar"] [class*="stToggle"] label,
section[data-testid="stSidebar"] [class*="stToggle"] p {
    color: #475657 !important;
}

/* ── SQL code blocks — always readable on light background ── */
/* Force code block background to light and text to dark */
[data-testid="stExpander"] pre,
[data-testid="stExpander"] code,
[data-testid="stExpander"] .stCode,
[data-testid="stExpanderDetails"] pre,
[data-testid="stExpanderDetails"] code,
[data-testid="stExpanderDetails"] .stCode,
[data-testid="stCodeBlock"],
[data-testid="stCodeBlock"] pre,
[data-testid="stCodeBlock"] code,
[data-testid="stCodeBlock"] span,
.stCode pre,
.stCode code {
    background-color: #f4f1d8 !important;
    color: #1a1a1a !important;
}

/* Individual token spans inside syntax-highlighted code */
[data-testid="stCodeBlock"] span,
[data-testid="stExpanderDetails"] pre span {
    color: inherit !important;
}

/* ── Copy button on code blocks — stays visible in all themes ── */
[data-testid="stCodeBlock"] button,
[data-testid="stCodeCopyButton"],
[data-testid="stCodeBlock"] [data-testid="stCodeCopyButton"] {
    background-color: #e8e4c8 !important;
    color: #1a1a1a !important;
    border: 1px solid #ccc8a8 !important;
    opacity: 1 !important;
}
[data-testid="stCodeBlock"] button:hover,
[data-testid="stCodeCopyButton"]:hover {
    background-color: #FFDD33 !important;
    color: #000000 !important;
    border-color: #FFDD33 !important;
}
/* SVG icon inside copy button */
[data-testid="stCodeBlock"] button svg,
[data-testid="stCodeCopyButton"] svg {
    fill: #1a1a1a !important;
    stroke: #1a1a1a !important;
}

</style>
""", unsafe_allow_html=True)


# ── Session init ───────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id    = str(uuid.uuid4())
    st.session_state.session_id = str(uuid.uuid4())
    create_session(st.session_state.user_id, st.session_state.session_id)

if "messages" not in st.session_state:
    st.session_state.messages = []


# ── Speech-to-Text ─────────────────────────────────────────
# compute_engine.Credentials() only works on Cloud Run / GCE.
# Locally we fall back to google.auth.default() (ADC).
def transcribe_audio(audio_bytes: bytes) -> str:
    try:
        try:
            credentials = compute_engine.Credentials()
        except Exception:
            credentials, _ = google_auth_default()
        client = speech.SpeechClient(credentials=credentials)
        audio  = speech.RecognitionAudio(content=audio_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,
            language_code="en-US",
            alternative_language_codes=[
                "hi-IN", "ar-SA", "es-ES", "fr-FR",
                "de-DE", "ja-JP", "ko-KR",
            ],
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)
        if response.results:
            transcript = response.results[0].alternatives[0].transcript
            print(f"Voice transcript: {transcript}")
            return transcript
        return ""
    except Exception as e:
        st.warning(f"Voice input unavailable: {e}")
        return ""


# ── Sidebar ────────────────────────────────────────────────
with st.sidebar:

    # Client logo — white logo shown on dark background so it's always visible
    client_logo = load_logo(CLIENT_LOGO)
    if client_logo:
        st.markdown(
            f"<div style='background:#1a1a1a; padding:12px; "
            f"border-radius:8px; margin-bottom:8px;'>"
            f"<img src='{client_logo}' style='width:100%;'/></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background:#1a1a1a; padding:12px; border-radius:8px; "
            "margin-bottom:8px; color:white; font-size:18px; font-weight:600; "
            "text-align:center;'>Brookfield</div>",
            unsafe_allow_html=True,
        )

    # Built by Brainlabs
    bl_logo = load_logo(BRAINLABS_LOGO)
    if bl_logo:
        st.markdown(
            f"<div style='display:flex; align-items:center; gap:8px; margin-bottom:4px;'>"
            f"<img src='{bl_logo}' style='width:32px; height:32px; object-fit:contain;'/>"
            f"<span style='font-size:11px;'>Built by <b> BI Team <b> from <b> Brainlabs India <b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='font-size:11px;'>Built by <b> BI Team <b> from <b> Brainlabs India <b></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div style='font-size:12px; color:#475657; margin-bottom:8px;'>"
        "Powered by <b>Google ADK</b> + Gemini on Vertex AI</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Example questions
    st.markdown(
        "<div style='font-size:13px; font-weight:600; color:#000; "
        "margin-bottom:6px;'>Try asking:</div>",
        unsafe_allow_html=True,
    )
    examples = [
        "How did Search perform last month vs the month before?",
        "Top 10 keywords by internal link clicks in the last month?",
        "Show social spend trend over the last 3 months",
        "Compare Brand vs NonBrand CTR for the last quarter of 2026",
        "Which social campaigns had highest CPM last month?",
        "Show a chart of monthly impressions by channel",
    ]
    for q in examples:
        if st.button(q, width='stretch', key=f"ex_{q[:25]}"):
            st.session_state.pending_question = q

    st.markdown("---")

    # Controls row
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ New chat", width='stretch'):
            st.session_state.messages   = []
            st.session_state.user_id    = str(uuid.uuid4())
            st.session_state.session_id = str(uuid.uuid4())
            create_session(st.session_state.user_id, st.session_state.session_id)
            st.rerun()
    with col2:
        show_sql = st.toggle("Show SQL", value=False)

    # Mic recorder — right below controls, always visible
    st.markdown("---")
    st.markdown(
        "<div style='font-size:12px; color:#475657; margin-bottom:6px;'>"
        "🎤 Voice input — supports 4 languages (hi-IN, en-US, es-ES, fr-FR).</div>",
        unsafe_allow_html=True,
    )
    audio = mic_recorder(
        start_prompt="🎤 Speak",
        stop_prompt="⏹ Stop recording",
        just_once=True,
        width='stretch',
        key="mic_input",
    )

    st.markdown("---")
    st.markdown(
        "<small style='color:#475657;'> "
        "Google Cloud Speech-to-Text</small>",
        unsafe_allow_html=True,
    )


# ── Page header ────────────────────────────────────────────
_bl_logo = load_logo(BRAINLABS_LOGO)
_logo_html = (
    f"<img src='{_bl_logo}' style='width:56px; height:56px; object-fit:contain; flex-shrink:0;'/>"
    if _bl_logo
    else "<span style='font-size:14px; font-weight:700;'>Brainlabs</span>"
)
st.markdown(
    f"""
    <div style='display:flex; align-items:center; gap:16px; margin-bottom:4px;'>
        {_logo_html}
        <div>
            <h1 style='margin:0; padding:0; font-size:2rem;'>Brookfield Marketing Analytics</h1>
            <p style='margin:0; padding:0; font-size:14px; color:#475657;'>
                Text or voice input · Conversational analytics powered by Google ADK
            </p>
        </div>
    </div>
    <hr style='border:none; border-top:3px solid #FFDD33; margin:8px 0 16px 0;'/>
    """,
    unsafe_allow_html=True,
)


# ── Chat history ───────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user" and msg.get("via_voice"):
            st.caption("🎤 via voice")
        st.markdown(msg["content"], unsafe_allow_html=True)
        if msg["role"] == "assistant":
            if msg.get("tool_calls"):
                badges = "".join(
                    f'<span class="tool-badge">🔧 {t}</span>'
                    for t in msg["tool_calls"]
                )
                st.markdown(badges, unsafe_allow_html=True)
            if show_sql and msg.get("sql"):
                with st.expander("📝 SQL", expanded=False):
                    st.code(msg["sql"], language="sql")
            if msg.get("df") is not None and not msg["df"].empty:
                with st.expander(
                    f"📋 Data ({len(msg['df'])} rows)", expanded=False
                ):
                    st.dataframe(
                        msg["df"], width='stretch', hide_index=True
                    )
            if msg.get("fig") is not None:
                st.plotly_chart(msg["fig"], width='stretch')


# ── Input ──────────────────────────────────────────────────
pending    = st.session_state.pop("pending_question", None)
user_input = st.chat_input("Ask about Search, Social, or Programmatic...")

# Process voice recording
voice_text = ""
if audio and audio.get("bytes"):
    with st.spinner("🎤 Transcribing..."):
        voice_text = transcribe_audio(audio["bytes"])
    if voice_text:
        st.info(f'🎤 Heard: "{voice_text}"')
    else:
        st.warning(
            "Could not transcribe — please try again or type your question."
        )

# Priority: typed > voice > example button
question  = user_input or voice_text or pending
via_voice = bool(voice_text and not user_input)

if question:
    with st.chat_message("user"):
        if via_voice:
            st.caption("🎤 via voice")
        st.markdown(question)

    st.session_state.messages.append({
        "role":       "user",
        "content":    question,
        "via_voice":  via_voice,
        "df":         None,
        "sql":        None,
        "tool_calls": [],
        "fig":        None,
    })

    with st.chat_message("assistant"):
        try:
            with st.spinner("Agent is thinking..."):
                result = chat(
                    user_message=question,
                    user_id=st.session_state.user_id,
                    session_id=st.session_state.session_id,
                )

            st.markdown(result["text"], unsafe_allow_html=True)

            if result["tool_calls"]:
                badges = "".join(
                    f'<span class="tool-badge">🔧 {t}</span>'
                    for t in result["tool_calls"]
                )
                st.markdown(badges, unsafe_allow_html=True)

            if show_sql and result["sql"]:
                with st.expander("📝 SQL", expanded=False):
                    st.code(result["sql"], language="sql")

            if result["df"] is not None and not result["df"].empty:
                with st.expander(
                    f"📋 Data ({len(result['df'])} rows)", expanded=False
                ):
                    st.dataframe(
                        result["df"], width='stretch', hide_index=True
                    )

            fig = None
            if result["df"] is not None and not result["df"].empty:
                try:
                    fig = ai_chart(result["df"], title=question[:60])
                    if fig:
                        st.plotly_chart(fig, width='stretch')
                except Exception as chart_err:
                    import traceback
                    st.markdown(
                        f"<div style='background:#fff3cd; border-left:4px solid #ffc107; "
                        f"padding:10px 14px; border-radius:6px; margin-top:8px;'>"
                        f"<b>⚠️ Chart error:</b><br>"
                        f"<code style='color:#333; font-size:12px;'>{chart_err}</code><br>"
                        f"<details><summary style='cursor:pointer; font-size:12px; color:#666;'>Traceback</summary>"
                        f"<pre style='font-size:11px; color:#333; white-space:pre-wrap;'>"
                        f"{traceback.format_exc()}</pre></details></div>",
                        unsafe_allow_html=True,
                    )
                    fig = None

        except Exception as agent_err:
            import traceback
            error_text = str(agent_err)
            tb_text = traceback.format_exc()
            st.markdown(
                f"<div style='background:#fdecea; border-left:4px solid #e53935; "
                f"padding:10px 14px; border-radius:6px;'>"
                f"<b>❌ Agent error:</b><br>"
                f"<code style='color:#333; font-size:12px;'>{error_text}</code><br>"
                f"<details><summary style='cursor:pointer; font-size:12px; color:#666;'>Traceback</summary>"
                f"<pre style='font-size:11px; color:#333; white-space:pre-wrap;'>"
                f"{tb_text}</pre></details></div>",
                unsafe_allow_html=True,
            )
            result = {"text": f"❌ Error: {error_text}", "df": None, "sql": None, "tool_calls": [], "fig": None}
            fig = None

    st.session_state.messages.append({
        "role":       "assistant",
        "content":    result["text"],
        "df":         result["df"],
        "sql":        result["sql"],
        "tool_calls": result["tool_calls"],
        "fig":        fig,
    })