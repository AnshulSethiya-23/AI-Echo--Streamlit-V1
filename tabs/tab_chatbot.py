"""
tabs/tab_chatbot.py — Chatbot tab for the Brookfield dashboard.

Wires the Streamlit fragment UI to chatbot/agent.py (chat + create_session)
and chatbot/charts.py (ai_chart).  No voice input — that is Cloud Run only
and lives in the standalone chatbot/app.py.

Session-state keys are prefixed with `chatbot_` to avoid conflicts with
other dashboard tabs.
"""

import sys
import os
import uuid
import streamlit as st

# ── Path setup — allows `from agent import ...` and `from charts import ...`
_CHATBOT_DIR = os.path.join(os.path.dirname(__file__), "..", "chatbot")
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_CHATBOT_DIR))

from agent import chat, create_session   # noqa: E402
from charts import ai_chart              # noqa: E402


# ── Minimal scoped CSS (tool badges only — global styles live in main app) ──
_TAB_CSS = """
<style>
.chatbot-tab-badge {
    display: inline-block;
    background: #80DBFF;
    color: #000000;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    margin: 2px;
    font-family: monospace;
}
.chatbot-tab-example-btn button {
    background-color: #ffffff !important;
    border: 1px solid #FFDD33 !important;
    color: #475657 !important;
    border-radius: 8px !important;
    font-size: 12px !important;
    text-align: left !important;
    width: 100% !important;
}
.chatbot-tab-example-btn button:hover {
    background-color: #FFDD33 !important;
    color: #000000 !important;
}
/* Prevent long strings / code from overflowing chat bubbles */
[data-testid="stChatMessageContent"] p,
[data-testid="stChatMessageContent"] div,
[data-testid="stChatMessageContent"] span,
[data-testid="stChatMessageContent"] code,
[data-testid="stChatMessageContent"] pre {
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    white-space: pre-wrap !important;
}
</style>
"""


@st.fragment
def render(start_date: str, end_date: str) -> None:
    """Render the chatbot tab inside the dashboard."""

    st.markdown(_TAB_CSS, unsafe_allow_html=True)

    # ── Session-state init ─────────────────────────────────
    if "chatbot_user_id" not in st.session_state:
        st.session_state.chatbot_user_id    = str(uuid.uuid4())
        st.session_state.chatbot_session_id = str(uuid.uuid4())
        create_session(
            st.session_state.chatbot_user_id,
            st.session_state.chatbot_session_id,
        )

    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = []

    # ── Handle new-chat request from sidebar button ─────────
    # The sidebar button triggers a full rerun; we catch the flag here.
    if st.session_state.pop("chatbot_new_chat_requested", False):
        st.session_state.chatbot_messages   = []
        st.session_state.chatbot_user_id    = str(uuid.uuid4())
        st.session_state.chatbot_session_id = str(uuid.uuid4())
        create_session(
            st.session_state.chatbot_user_id,
            st.session_state.chatbot_session_id,
        )

    # ── Read Show SQL toggle value from sidebar ─────────────
    show_sql = st.session_state.get("chatbot_show_sql", False)

    # ── Header ─────────────────────────────────────────────
    st.subheader("Ask Your Data")
    st.caption("Conversational analytics powered by Google ADK + Gemini on Vertex AI")

    st.markdown(
        "<hr style='border:none; border-top:2px solid #FFDD33; margin:8px 0 12px 0;'/>",
        unsafe_allow_html=True,
    )

    # ── Render chat history ────────────────────────────────
    for msg in st.session_state.chatbot_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

            if msg["role"] == "assistant":
                # Tool-call badges
                if msg.get("tool_calls"):
                    badges = "".join(
                        f'<span class="chatbot-tab-badge">🔧 {t}</span>'
                        for t in msg["tool_calls"]
                    )
                    st.markdown(badges, unsafe_allow_html=True)

                # SQL expander
                if show_sql and msg.get("sql"):
                    with st.expander("SQL", expanded=False):
                        st.code(msg["sql"], language="sql")

                # Data table expander
                if msg.get("df") is not None and not msg["df"].empty:
                    with st.expander(
                        f"Data ({len(msg['df'])} rows)", expanded=False
                    ):
                        st.dataframe(
                            msg["df"], width='stretch', hide_index=True
                        )

                # Chart
                if msg.get("fig") is not None:
                    st.plotly_chart(msg["fig"], width='stretch')

    # ── Chat input ─────────────────────────────────────────
    pending    = st.session_state.pop("chatbot_pending", None)
    user_input = st.chat_input(
        "Ask about Search, Social, or Programmatic...",
        key="chatbot_input",
    )

    question = user_input or pending

    if question:
        # Show the user message immediately
        with st.chat_message("user"):
            st.markdown(question)

        st.session_state.chatbot_messages.append({
            "role":       "user",
            "content":    question,
            "df":         None,
            "sql":        None,
            "tool_calls": [],
            "fig":        None,
        })

        # ── Agent call ────────────────────────────────────
        with st.chat_message("assistant"):
            try:
                with st.spinner("Agent is thinking..."):
                    result = chat(
                        user_message=question,
                        user_id=st.session_state.chatbot_user_id,
                        session_id=st.session_state.chatbot_session_id,
                    )

                st.markdown(result["text"], unsafe_allow_html=True)

                # Tool badges
                if result["tool_calls"]:
                    badges = "".join(
                        f'<span class="chatbot-tab-badge">🔧 {t}</span>'
                        for t in result["tool_calls"]
                    )
                    st.markdown(badges, unsafe_allow_html=True)

                # SQL expander
                if show_sql and result["sql"]:
                    with st.expander("SQL", expanded=False):
                        st.code(result["sql"], language="sql")

                # Data table expander
                if result["df"] is not None and not result["df"].empty:
                    with st.expander(
                        f"Data ({len(result['df'])} rows)", expanded=False
                    ):
                        st.dataframe(
                            result["df"], width='stretch', hide_index=True
                        )

                # Chart — attempt AI chart if data exists
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
                            f"<b>⚠️ Chart generation failed:</b> "
                            f"<code style='color:#333; font-size:12px;'>{chart_err}</code>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        fig = None

            except Exception as agent_err:
                import traceback
                tb_text    = traceback.format_exc()
                error_text = str(agent_err)
                st.markdown(
                    f"<div style='background:#fdecea; border-left:4px solid #e53935; "
                    f"padding:10px 14px; border-radius:6px;'>"
                    f"<b>❌ Agent error:</b><br>"
                    f"<code style='color:#333; font-size:12px;'>{error_text}</code><br>"
                    f"<details><summary style='cursor:pointer;font-size:12px;color:#666;'>"
                    f"Traceback</summary>"
                    f"<pre style='font-size:11px;color:#333;white-space:pre-wrap;'>"
                    f"{tb_text}</pre></details></div>",
                    unsafe_allow_html=True,
                )
                result = {
                    "text":       f"❌ Error: {error_text}",
                    "df":         None,
                    "sql":        None,
                    "tool_calls": [],
                }
                fig = None

        # Persist assistant message
        st.session_state.chatbot_messages.append({
            "role":       "assistant",
            "content":    result["text"],
            "df":         result.get("df"),
            "sql":        result.get("sql"),
            "tool_calls": result.get("tool_calls", []),
            "fig":        fig,
        })
        # Re-render so history renders cleanly.
        # scope="fragment" is only valid during a fragment-triggered rerun;
        # fall back to a full rerun when the trigger came from the sidebar.
        try:
            st.rerun(scope="fragment")
        except Exception:
            st.rerun()
