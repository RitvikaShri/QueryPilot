"""Polished Streamlit interface for QueryPilot."""
from __future__ import annotations

import re

import pandas as pd
import plotly.express as px
import streamlit as st

from agent import DataAgent
from config import DOMAINS
from dataset import DemoDataset


st.set_page_config(
    page_title="QueryPilot | Data Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Visual system ----------
st.markdown(
    """
    <style>
    :root {
        --qp-bg: #10131B;
        --qp-panel: #1B2130;
        --qp-panel-soft: #202838;
        --qp-border: #30394B;
        --qp-text: #F3F5F9;
        --qp-muted: #AAB3C5;
        --qp-accent: #2785D8;
    }
    .stApp { background: var(--qp-bg); }
    [data-testid="stHeader"] { background: rgba(16,19,27,.88); }
    [data-testid="stSidebar"] {
        background: #171C27;
        border-right: 1px solid var(--qp-border);
    }
    [data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem;
    }
    .qp-brand {
        font-size: 2rem; font-weight: 750; letter-spacing: -1.2px;
        color: var(--qp-text); margin: 0 0 .15rem 0;
    }
    .qp-subtitle { color: var(--qp-muted); font-size: .96rem; margin-bottom: 1.25rem; }
    .qp-eyebrow {
        color: #76B9F2; text-transform: uppercase; letter-spacing: .12em;
        font-size: .72rem; font-weight: 700; margin-bottom: .45rem;
    }
    .qp-section-title { font-size: 1rem; font-weight: 650; margin: .4rem 0 .6rem; }
    div[data-testid="stChatMessage"] {
        border: 1px solid rgba(119,137,164,.14);
        border-radius: 14px;
        padding: 1rem 1.1rem;
        background: rgba(27,33,48,.55);
        margin-bottom: .9rem;
    }
    div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        background: rgba(27,33,48,.68);
    }
    .qp-meta { color: var(--qp-muted); font-size: .78rem; margin: .2rem 0 .65rem; }
    .qp-result-heading { font-weight: 650; font-size: .95rem; margin: .55rem 0 .2rem; }
    .qp-result-count { color: var(--qp-muted); font-size: .78rem; margin-bottom: .5rem; }
    div[data-testid="stExpander"] {
        border: 1px solid var(--qp-border);
        border-radius: 10px;
        background: rgba(27,33,48,.45);
    }
    div.stButton > button {
        border: 1px solid var(--qp-border);
        border-radius: 9px;
        background: #202735;
        color: var(--qp-text);
        text-align: left;
        min-height: 2.55rem;
        transition: border-color .15s ease, background .15s ease;
    }
    div.stButton > button:hover {
        border-color: var(--qp-accent);
        background: #263449;
        color: white;
    }
    [data-testid="stChatInput"] {
        border: 1px solid var(--qp-border);
        border-radius: 13px;
        background: #1B2130;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--qp-border);
        border-radius: 10px;
        overflow: hidden;
    }
    .stCaption, small { color: var(--qp-muted) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Formatting and rendering ----------
CURRENCY_COLUMNS = {
    "revenue", "total_revenue", "gross_payroll", "net_payroll",
    "total_deductions", "gross_salary", "net_salary", "overtime_pay",
    "total_overtime_pay", "unit_price", "basic_pay", "hra",
    "special_allowance", "transport_allowance", "bonus",
}


def _format_results(frame: pd.DataFrame) -> pd.DataFrame:
    """Format a display-only copy; the underlying SQL rows remain unchanged."""
    display = frame.copy()
    for column in display.columns:
        key = str(column).lower()
        if key in CURRENCY_COLUMNS or any(
            token in key for token in ("_revenue", "_payroll", "_salary", "_deduction", "_allowance")
        ):
            display[column] = display[column].map(
                lambda value: (
                    f"₹{float(value):,.2f}".rstrip("0").rstrip(".")
                    if pd.notna(value) and _is_numeric(value)
                    else value
                )
            )
        elif pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].map(
                lambda value: f"{value:,.2f}".rstrip("0").rstrip(".")
                if pd.notna(value) and isinstance(value, (int, float))
                else value
            )
    return display


def _is_numeric(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _render_result(result: dict, chart_key: str) -> None:
    domain = result.get("domain")
    if domain:
        st.markdown(
            f'<div class="qp-meta">DOMAIN&nbsp;&nbsp;·&nbsp;&nbsp;{str(domain).upper()}</div>',
            unsafe_allow_html=True,
        )

    sql = result.get("validated_sql")
    if sql:
        with st.expander("View SQL query", expanded=False):
            st.code(sql, language="sql")

    rows = result.get("rows") or []
    if result.get("error"):
        st.error(result["error"])
        return

    if not rows:
        st.info("The query completed successfully, but no matching records were found.")
        return

    frame = pd.DataFrame(rows)

    insights = result.get("insights") or []
    if insights:
        with st.container(border=True):
            st.markdown("**Key insights**")
            for insight in insights:
                st.markdown(f"- {insight}")

    st.markdown('<div class="qp-result-heading">Query results</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="qp-result-count">{len(frame):,} '
        f'{"row" if len(frame) == 1 else "rows"} returned</div>',
        unsafe_allow_html=True,
    )

    chart = result.get("chart")
    if chart:
        fig = _build_chart(frame, chart)
        if fig is not None:
            with st.expander("Explore visualization", expanded=len(frame) > 1):
                st.plotly_chart(
                    fig,
                    width="stretch",
                    key=chart_key,
                    config={"displayModeBar": False, "responsive": True},
                )

    st.dataframe(
        _format_results(frame),
        hide_index=True,
        width="stretch",
        height=min(390, 46 + 36 * min(len(frame), 9)),
    )


def _pretty_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ")).strip().title()


def _build_chart(frame: pd.DataFrame, chart: dict):
    x, y = chart.get("x"), chart.get("y")
    color, chart_type = chart.get("color"), chart.get("type")

    if not x or not y or x not in frame.columns or y not in frame.columns:
        return None
    if color and color not in frame.columns:
        return None

    plot_frame = frame.copy()
    plot_frame[y] = pd.to_numeric(plot_frame[y], errors="coerce")
    plot_frame = plot_frame.dropna(subset=[y])
    if plot_frame.empty:
        return None

    title = chart.get("display_title") or (
        f"{_pretty_label(y)} by {_pretty_label(x)}"
        if not color else
        f"{_pretty_label(y)} by {_pretty_label(x)} and {_pretty_label(color)}"
    )
    labels = {x: _pretty_label(x), y: _pretty_label(y)}
    if color:
        labels[color] = _pretty_label(color)

    common = dict(
        data_frame=plot_frame,
        x=x,
        y=y,
        title=title,
        labels=labels,
        template="plotly_dark",
    )

    if chart_type == "line":
        fig = px.line(**common, markers=True)
    elif chart_type == "grouped_bar":
        fig = px.bar(**common, color=color, barmode="group", text_auto=".2s")
    else:
        fig = px.bar(**common, text_auto=".2s")

    fig.update_layout(
        height=340,
        margin=dict(l=18, r=18, t=58, b=24),
        title=dict(font=dict(size=16), x=0.02, xanchor="left"),
        legend_title_text=_pretty_label(color) if color else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#DCE3EF", size=12),
        xaxis=dict(showgrid=False, automargin=True),
        yaxis=dict(gridcolor="rgba(150,165,190,.16)", zeroline=False, automargin=True),
    )
    fig.update_traces(
        hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
        marker_line_width=0,
    )
    return fig


# ---------- Data and sidebar ----------
dataset = DemoDataset()

with st.sidebar:
    st.markdown('<div class="qp-eyebrow">Workspace</div>', unsafe_allow_html=True)
    st.markdown("### Dataset explorer")
    st.caption("Browse available domains, sample questions and source tables.")

    for domain in DOMAINS.values():
        with st.expander(
            f"{domain.name.title()} analytics",
            expanded=domain.name == "sales",
        ):
            st.caption(domain.description)
            st.caption("TABLES  ·  " + ", ".join(domain.tables))
            for index, question in enumerate(domain.sample_questions):
                if st.button(
                    question,
                    key=f"sample-{domain.name}-{index}",
                    width="stretch",
                ):
                    st.session_state.pending_prompt = question

    st.divider()
    with st.expander(f"Data tables · {len(dataset.table_names)}", expanded=False):
        for table_name in sorted(dataset.table_names):
            with st.expander(table_name, expanded=False):
                preview = pd.DataFrame(dataset.preview(table_name, limit=5))
                st.dataframe(preview, hide_index=True, use_container_width=True)

    if st.button("↻  Reset conversation", use_container_width=True):
        for key in ("messages", "history", "agent", "pending_prompt"):
            st.session_state.pop(key, None)
        st.rerun()


# ---------- Session state ----------
if "agent" not in st.session_state:
    st.session_state.agent = DataAgent(dataset=dataset)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history" not in st.session_state:
    st.session_state.history = []


# ---------- Main workspace ----------
st.markdown('<div class="qp-eyebrow">Conversational analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="qp-brand">QueryPilot</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="qp-subtitle">Ask questions. Explore data. Get insights.</div>',
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    st.markdown("#### Start with a question")
    st.caption("Choose a sample from the sidebar or ask something in your own words.")
    starter_cols = st.columns(3)
    starters = [
        ("Sales", "Which region generated the most revenue?"),
        ("Support", "How many support tickets are there by priority?"),
        ("HR", "Which department has the highest total deductions?"),
    ]
    for col, (label, question) in zip(starter_cols, starters):
        with col:
            if st.button(f"{label}  ·  {question}", use_container_width=True):
                st.session_state.pending_prompt = question
                st.rerun()

for message_index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("result"):
            _render_result(message["result"], chart_key=f"history-chart-{message_index}")

prompt = st.session_state.pop("pending_prompt", None) or st.chat_input(
    "Ask about revenue, orders, support tickets, employees, attendance or payroll…"
)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("QueryPilot is exploring your data…"):
            try:
                result = st.session_state.agent.query(
                    prompt,
                    history=st.session_state.history,
                )
                answer = result.get("answer") or "The query finished, but no summary was generated."
                st.markdown(answer)
                _render_result(result, chart_key=f"live-chart-{len(st.session_state.messages)}")
            except Exception as exc:
                answer = "I couldn't complete that query. Please check the question and try again."
                st.error(answer)
                with st.expander("Technical details"):
                    st.exception(exc)
                result = {"answer": answer}

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "result": result}
    )
    st.session_state.history.extend([("human", prompt), ("ai", answer)])
    st.rerun()
