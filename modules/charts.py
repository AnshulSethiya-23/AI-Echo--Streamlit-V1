"""
charts.py — Plotly chart builders and Streamlit renderers for Brookfield Dashboard v2.

Supported chart types (chart_type in YAML):
  line, bar, stacked_bar, grouped_bar, area, pie, scorecard, table
"""

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

# ── Brainlabs brand palette ────────────────────────────────────────────────
# Primary: BL Blue (#80DBFF) → BL Yellow (#FFDD33) → supporting colours
# All approved against WCAG on white/cream backgrounds
PALETTE = [
    "#2563EB",  # strong blue  — high-contrast primary series
    "#FFDD33",  # BL Yellow    — primary brand accent
    "#80DBFF",  # BL Blue      — secondary brand accent
    "#F59E0B",  # amber        — warm third series
    "#10B981",  # emerald      — positive/green signals
    "#FFE770",  # Yellow 2     — lighter BL brand yellow
    "#C2EEFF",  # Blue 2       — lighter BL brand blue
    "#EF4444",  # red          — alert / negative signals
    "#8B5CF6",  # violet       — additional series
]

# ── Shared Plotly layout (Kanit font, BL cream background) ─────────────────
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Kanit, sans-serif", size=12, color="#000000"),
    margin=dict(l=40, r=20, t=36, b=28),
    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="right", x=1,
        font=dict(family="Kanit, sans-serif", size=11),
    ),
    xaxis=dict(showgrid=False, linecolor="#000000", linewidth=0.5),
    yaxis=dict(gridcolor="#FFE770", gridwidth=0.5, linecolor="#000000", linewidth=0.5),
    hoverlabel=dict(
        bgcolor="#FFDD33",
        font_size=12,
        font_family="Kanit, sans-serif",
        font_color="#000000",
        bordercolor="#000000",
    ),
)


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Convert a 6-digit hex colour string to an rgba() CSS value."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _fmt_abbrev(value, prefix: str = "") -> str:
    """Abbreviate a large number to K / M / B with 1 decimal place.

    Examples:
        312_345_345  → '$312.3M'  (with prefix='$')
        1_500_000    → '1.5M'
        45_000       → '45.0K'
        999          → '999.0'
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    abs_v = abs(v)
    if abs_v >= 1_000_000_000:
        return f"{prefix}{v / 1_000_000_000:.1f}B"
    elif abs_v >= 1_000_000:
        return f"{prefix}{v / 1_000_000:.1f}M"
    elif abs_v >= 1_000:
        return f"{prefix}{v / 1_000:.1f}K"
    else:
        return f"{prefix}{v:,.1f}"


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC — figure builder (returns Figure or None)
# ══════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def build_figure(chart_config: dict, df: pd.DataFrame) -> go.Figure | None:
    """Return a Plotly Figure for the given chart config + df, or None if empty.

    Cached by Streamlit so the same data + config never rebuilds the figure
    twice in a session. This is the main chart-render speedup — BQ results are
    already cached in bq_engine; now the Plotly work is cached too.
    """
    if df is None or df.empty:
        return None

    chart_type = chart_config.get("chart_type")
    builders = {
        "line":         _build_line,
        "area":         _build_area,
        "bar":          _build_bar,
        "grouped_bar":  _build_bar,       # alias — bar defaults to group mode
        "stacked_bar":  _build_stacked_bar,
        "pie":          _build_pie,
    }
    fn = builders.get(chart_type)
    if fn is None:
        return None
    return fn(chart_config, df)


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC — renderers (render inline + return Figure)
# ══════════════════════════════════════════════════════════════════════════

def render_chart(chart_config: dict, df: pd.DataFrame) -> go.Figure | None:
    """Renders a chart inline. Returns the Figure for callers that need it."""
    fig = build_figure(chart_config, df)
    if fig is None:
        st.info(f"No data for: **{chart_config.get('title')}**")
        return None
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
    return fig


def render_scorecard(chart_config: dict, data: dict) -> None:
    """Renders a single st.metric scorecard."""
    current  = data.get("current", 0)
    delta_pct = data.get("delta_pct", 0)
    fmt      = chart_config.get("format", "number")

    if fmt == "currency":
        display = _fmt_abbrev(current, prefix="$")
    elif fmt == "percent":
        display = f"{current:.2f}%"
    else:
        display = _fmt_abbrev(current)

    delta_str = f"{delta_pct:+.1f}% vs prior period"
    st.metric(label=chart_config.get("title", ""), value=display, delta=delta_str)


def render_table(chart_config: dict, df: pd.DataFrame) -> None:
    """
    Renders a styled summary table.
    Formats number columns and highlights the header with Brainlabs yellow.
    """
    if df is None or df.empty:
        st.info(f"No data for: **{chart_config.get('title')}**")
        return

    title = chart_config.get("title", "")
    if title:
        st.markdown(f"**{title}**")

    # ── Format numeric columns ─────────────────────────────────────────
    display_df = df.copy()
    format_map  = chart_config.get("column_formats", {})

    for col in display_df.columns:
        col_fmt = format_map.get(col, "")
        if col_fmt == "currency" and pd.api.types.is_numeric_dtype(display_df[col]):
            display_df[col] = display_df[col].apply(
                lambda v: f"${v:,.0f}" if pd.notna(v) else "—"
            )
        elif col_fmt == "percent" and pd.api.types.is_numeric_dtype(display_df[col]):
            display_df[col] = display_df[col].apply(
                lambda v: f"{v:.2f}%" if pd.notna(v) else "—"
            )
        elif col_fmt == "number" and pd.api.types.is_numeric_dtype(display_df[col]):
            display_df[col] = display_df[col].apply(
                lambda v: f"{v:,.0f}" if pd.notna(v) else "—"
            )
        elif pd.api.types.is_numeric_dtype(display_df[col]):
            # Auto-format: round to 2 dp
            display_df[col] = display_df[col].apply(
                lambda v: f"{v:,.2f}" if pd.notna(v) else "—"
            )

    # Pretty column headers
    display_df.columns = [
        c.replace("_", " ").title() for c in display_df.columns
    ]

    st.dataframe(display_df, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PRIVATE — figure builders
# ══════════════════════════════════════════════════════════════════════════

def _build_line(cfg: dict, df: pd.DataFrame) -> go.Figure:
    x_col  = cfg.get("x_col", df.columns[0])
    y_cols = cfg.get("y_cols", [df.columns[1]])

    fig = go.Figure()
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[col],
            name=col.replace("_", " ").title(),
            mode="lines+markers",
            line=dict(color=PALETTE[i % len(PALETTE)], width=2.5),
            marker=dict(size=5),
        ))
    fig.update_layout(title=cfg.get("title", ""), **CHART_LAYOUT)
    return fig


def _build_area(cfg: dict, df: pd.DataFrame) -> go.Figure:
    x_col  = cfg.get("x_col", df.columns[0])
    y_cols = cfg.get("y_cols", [df.columns[1]])

    fig = go.Figure()
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[col],
            name=col.replace("_", " ").title(),
            mode="lines",
            fill="tozeroy",
            line=dict(color=PALETTE[i % len(PALETTE)], width=2),
            fillcolor=_hex_to_rgba(PALETTE[i % len(PALETTE)], alpha=0.15),
        ))
    fig.update_layout(title=cfg.get("title", ""), **CHART_LAYOUT)
    return fig


def _build_bar(cfg: dict, df: pd.DataFrame) -> go.Figure:
    x_col  = cfg.get("x_col", df.columns[0])
    y_cols = cfg.get("y_cols", [df.columns[1]])
    prefix = "$" if cfg.get("format") == "currency" else ""

    fig = go.Figure()
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        text_labels = [_fmt_abbrev(v, prefix) for v in df[col]]
        fig.add_trace(go.Bar(
            x=df[x_col],
            y=df[col],
            name=col.replace("_", " ").title(),
            marker_color=PALETTE[i % len(PALETTE)],
            marker_line_color="#000000",
            marker_line_width=0.5,
            text=text_labels,
            texttemplate="%{text}",
            textposition="outside",
            textfont=dict(family="Kanit, sans-serif", size=11, color="#000000"),
        ))
    fig.update_layout(title=cfg.get("title", ""), barmode="group", **CHART_LAYOUT)
    fig.update_yaxes(automargin=True)
    return fig


def _build_stacked_bar(cfg: dict, df: pd.DataFrame) -> go.Figure:
    x_col  = cfg.get("x_col", df.columns[0])
    y_cols = cfg.get("y_cols", list(df.columns[1:]))

    fig = go.Figure()
    for i, col in enumerate(y_cols):
        if col not in df.columns:
            continue
        fig.add_trace(go.Bar(
            x=df[x_col],
            y=df[col],
            name=col.replace("_", " ").title(),
            marker_color=PALETTE[i % len(PALETTE)],
        ))
    fig.update_layout(title=cfg.get("title", ""), barmode="stack", **CHART_LAYOUT)
    return fig


def _build_pie(cfg: dict, df: pd.DataFrame) -> go.Figure:
    label_col = cfg.get("label_col", df.columns[0])
    value_col = cfg.get("value_col", df.columns[1])

    fig = go.Figure(go.Pie(
        labels=df[label_col],
        values=df[value_col],
        hole=0.42,
        marker=dict(colors=PALETTE),
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f}<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        title=cfg.get("title", ""),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Kanit, sans-serif", size=12, color="#000000"),
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=-0.2,
            font=dict(family="Kanit, sans-serif", size=11),
        ),
        hoverlabel=dict(
            bgcolor="#FFDD33",
            font_size=12,
            font_family="Kanit, sans-serif",
            font_color="#000000",
            bordercolor="#000000",
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC — advanced chart builders (called directly from tabs, not YAML)
# ══════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def build_bubble(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    size_col: str,
    label_col: str,
    title: str,
    x_label: str = None,
    y_label: str = None,
    color_col: str = None,
    add_mean_lines: bool = True,
) -> go.Figure | None:
    """Bubble / efficiency scatter.

    Bubble size is normalised from size_col to 12–55 px.
    If color_col is provided, each unique value receives a PALETTE colour.
    Mean reference lines (dashed) split the chart into intuitive quadrants.
    """
    if df is None or df.empty:
        return None

    needed = [x_col, y_col, size_col, label_col]
    if color_col:
        needed.append(color_col)
    df = df.dropna(subset=needed).reset_index(drop=True)
    if df.empty:
        return None

    # Normalise bubble sizes: map size_col → [12, 55] px
    s_min, s_max = df[size_col].min(), df[size_col].max()
    if s_max == s_min:
        sizes = [30.0] * len(df)
    else:
        sizes = (12 + (df[size_col] - s_min) / (s_max - s_min) * 43).tolist()

    fig = go.Figure()

    def _short(v) -> str:
        """Truncate label to 22 chars."""
        return str(v)[:22]

    if color_col:
        for i, grp in enumerate(df[color_col].unique()):
            mask    = df[color_col] == grp
            sub     = df[mask]
            sub_sz  = [sizes[j] for j in sub.index]
            fig.add_trace(go.Scatter(
                x=sub[x_col],
                y=sub[y_col],
                mode="markers+text",
                name=str(grp),
                text=sub[label_col].apply(_short),
                textposition="top center",
                textfont=dict(family="Kanit, sans-serif", size=10, color="#000000"),
                marker=dict(
                    size=sub_sz,
                    color=PALETTE[i % len(PALETTE)],
                    line=dict(color="#000000", width=1),
                    opacity=0.85,
                ),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    f"{x_label or x_col}: %{{x:,.3f}}<br>"
                    f"{y_label or y_col}: %{{y:,.3f}}<extra></extra>"
                ),
            ))
    else:
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="markers+text",
            name=title,
            text=df[label_col].apply(_short),
            textposition="top center",
            textfont=dict(family="Kanit, sans-serif", size=10, color="#000000"),
            marker=dict(
                size=sizes,
                color=PALETTE[0],
                line=dict(color="#000000", width=1),
                opacity=0.85,
            ),
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{x_label or x_col}: %{{x:,.3f}}<br>"
                f"{y_label or y_col}: %{{y:,.3f}}<extra></extra>"
            ),
        ))

    # ── Mean reference lines (quadrant guides) ───────────────────────────
    if add_mean_lines and len(df) > 1:
        mean_x = float(df[x_col].mean())
        mean_y = float(df[y_col].mean())
        fig.add_vline(
            x=mean_x, line_dash="dot", line_color="#8B5CF6",
            line_width=1.2, opacity=0.55,
            annotation_text=f"avg {x_label or x_col}",
            annotation_font=dict(family="Kanit, sans-serif", size=10, color="#8B5CF6"),
            annotation_position="top right",
        )
        fig.add_hline(
            y=mean_y, line_dash="dot", line_color="#8B5CF6",
            line_width=1.2, opacity=0.55,
            annotation_text=f"avg {y_label or y_col}",
            annotation_font=dict(family="Kanit, sans-serif", size=10, color="#8B5CF6"),
            annotation_position="bottom right",
        )

    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Kanit, sans-serif", size=12, color="#000000"),
        margin=dict(l=60, r=20, t=50, b=50),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            font=dict(family="Kanit, sans-serif", size=11),
        ),
        xaxis=dict(
            title=x_label or x_col,
            showgrid=False,
            linecolor="#000000", linewidth=0.5,
        ),
        yaxis=dict(
            title=y_label or y_col,
            gridcolor="#FFE770", gridwidth=0.5,
            linecolor="#000000", linewidth=0.5,
        ),
        hoverlabel=dict(
            bgcolor="#FFDD33",
            font_size=12,
            font_family="Kanit, sans-serif",
            font_color="#000000",
            bordercolor="#000000",
        ),
    )
    return fig


@st.cache_data(show_spinner=False)
def build_heatmap(
    df: pd.DataFrame,
    row_col: str,
    col_col: str,
    value_col: str,
    title: str,
    row_order: list = None,
    col_order: list = None,
    value_fmt: str = "${:,.0f}",
) -> go.Figure | None:
    """Heatmap from a long-format DataFrame.

    Pivots row_col × col_col → value_col with BL yellow colour scale.
    Annotations show formatted values in each cell.
    """
    if df is None or df.empty:
        return None

    pivot = df.pivot_table(
        index=row_col, columns=col_col, values=value_col, aggfunc="sum"
    )
    if pivot.empty:
        return None

    if row_order:
        pivot = pivot.reindex([r for r in row_order if r in pivot.index])
    if col_order:
        pivot = pivot.reindex(columns=[c for c in col_order if c in pivot.columns])

    z    = pivot.values.tolist()
    rows = list(pivot.index)
    cols = list(pivot.columns)

    # Cell text annotations
    text = [
        [value_fmt.format(v) if (v is not None and not pd.isna(v)) else "" for v in row]
        for row in z
    ]

    BL_YELLOW_SCALE = [
        [0.0,  "#FFFEF7"],
        [0.33, "#FFE770"],
        [0.66, "#FFDD33"],
        [1.0,  "#F59E0B"],
    ]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=cols,
        y=rows,
        text=text,
        texttemplate="%{text}",
        textfont=dict(family="Kanit, sans-serif", size=11, color="#000000"),
        colorscale=BL_YELLOW_SCALE,
        showscale=True,
        colorbar=dict(
            thickness=14,
            tickfont=dict(family="Kanit, sans-serif", size=10),
            outlinewidth=0.5,
            outlinecolor="#000000",
        ),
        hovertemplate="%{y} · %{x}<br>Value: %{z:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Kanit, sans-serif", size=12, color="#000000"),
        margin=dict(l=120, r=20, t=50, b=80),
        xaxis=dict(
            side="bottom",
            showgrid=False,
            linecolor="#000000", linewidth=0.5,
            tickangle=-35,
        ),
        yaxis=dict(
            autorange="reversed",
            showgrid=False,
            linecolor="#000000", linewidth=0.5,
        ),
        hoverlabel=dict(
            bgcolor="#FFDD33",
            font_size=12,
            font_family="Kanit, sans-serif",
            font_color="#000000",
            bordercolor="#000000",
        ),
    )
    return fig
