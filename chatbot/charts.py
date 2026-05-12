import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_DARK  = "#1a1a1a"
_GRID  = "#e0e0e0"
_BG    = "#ffffff"
_PLOTBG = "#f9f9f9"

def _apply_light_theme(fig: go.Figure) -> go.Figure:
    """Force all text and background elements to a readable light theme."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=_BG,
        plot_bgcolor=_PLOTBG,
        font=dict(color=_DARK, family="Arial, sans-serif"),
        title_font=dict(color=_DARK, size=16),
        legend=dict(
            font=dict(color=_DARK),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor=_GRID,
            borderwidth=1,
        ),
    )
    fig.update_xaxes(
        tickfont=dict(color=_DARK),
        title_font=dict(color=_DARK),
        gridcolor=_GRID,
        linecolor=_GRID,
        zerolinecolor=_GRID,
    )
    fig.update_yaxes(
        tickfont=dict(color=_DARK),
        title_font=dict(color=_DARK),
        gridcolor=_GRID,
        linecolor=_GRID,
        zerolinecolor=_GRID,
    )
    # Fix colorbar text if present (heatmaps etc.)
    for trace in fig.data:
        if hasattr(trace, "colorbar") and trace.colorbar:
            trace.colorbar.tickfont = dict(color=_DARK)
            trace.colorbar.title = dict(
                font=dict(color=_DARK),
                text=getattr(trace.colorbar.title, "text", ""),
            )
    return fig


def ai_chart(df: pd.DataFrame, title: str = "") -> go.Figure | None:
    """
    Asks Gemini to decide the best chart type AND write the Plotly code.
    Executes the generated code and returns the figure.
    Falls back to a simple bar chart if anything fails.
    """
    if df is None or df.empty:
        return None

    try:
        from google import genai
        from config import MODEL_NAME

        # Same client as ADK — picks up env vars automatically
        client = genai.Client()

        sample    = df.head(5).to_csv(index=False)
        col_types = df.dtypes.to_string()
        num_rows  = len(df)

        prompt = f"""You are a data visualization expert writing Python code using Plotly.

User question: "{title}"

DataFrame info:
- {num_rows} rows
- Column types:
{col_types}

First 5 rows:
{sample}

Instructions:
1. Decide the best chart type based on the user question and data:
   - "pie", "share", "proportion", "breakdown", "distribution" → px.pie with hole=0.3
   - "trend", "over time", "monthly", "weekly" → go.Scatter line chart
   - "compare", "vs", "current vs previous" → grouped bar chart
   - "top", "ranking", "highest", "lowest" → horizontal bar chart
   - default → vertical bar chart

2. Write complete Python code to create that chart using Plotly.

Rules:
- `df` is already defined — do NOT redefine it
- `px`, `go`, `pd`, `make_subplots` are already imported — do NOT import anything
- Assign the final figure to variable named `fig`
- Use template="plotly_white"
- Add a clear title to the chart
- Output ONLY the Python code — no explanation, no markdown fences"""

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )

        code = response.text.strip()

        # Strip markdown fences if model adds them anyway
        code = re.sub(r"^```(?:python)?\n?", "", code)
        code = re.sub(r"\n?```$", "", code)
        code = code.strip()

        print(f"[ai_chart] Generated code:\n{code}\n")

        # Execute generated code with all plotly vars available
        local_vars = {
            "df":            df,
            "pd":            pd,
            "px":            px,
            "go":            go,
            "make_subplots": make_subplots,
        }
        exec(code, {}, local_vars)  # noqa: S102

        fig = local_vars.get("fig")
        if fig is not None:
            fig = _apply_light_theme(fig)
            print("[ai_chart] Chart created successfully")
            return fig
        else:
            print("[ai_chart] No `fig` variable found in generated code")

    except Exception as e:
        print(f"[ai_chart] Failed: {e}")

    # Fallback — simple bar chart
    return _fallback_chart(df, title)


def _fallback_chart(df: pd.DataFrame, title: str) -> go.Figure | None:
    """Simple rule-based fallback when AI generation fails."""
    num_cols = df.select_dtypes(include="number").columns.tolist()
    str_cols = df.select_dtypes(include="object").columns.tolist()
    curr_cols = [c for c in num_cols if c.startswith("current_")]
    prev_cols = [c for c in num_cols if c.startswith("previous_")]

    # Long-format period comparison: UNION ALL result with a 'period' column
    period_col = next(
        (c for c in str_cols if c.lower() == "period"), None
    )
    if period_col and num_cols:
        return _period_comparison_bar(df, period_col, num_cols, title)

    date_cols = []
    for c in df.columns:
        if "date" in c.lower():
            date_cols.append(c)
        elif c in str_cols:
            try:
                pd.to_datetime(df[c].dropna().head(5))
                date_cols.append(c)
            except Exception:
                pass

    if curr_cols and prev_cols:
        return _comparison_bar(df, curr_cols, prev_cols, str_cols, title)
    if date_cols and num_cols:
        return _time_series(df, date_cols[0], num_cols, title)
    if str_cols and num_cols:
        return _ranking_bar(df, str_cols[0], num_cols[0], title)
    return None


def _period_comparison_bar(df, period_col, num_cols, title):
    """
    Handles long-format UNION ALL results with a 'period' column.
    Ensures 'Previous Month' always renders left of 'Last Month'.
    """
    # Canonical period order: previous first, current second
    period_order = ["Previous Month", "Last Month"]
    present = df[period_col].unique().tolist()
    order = [p for p in period_order if p in present] + \
            [p for p in present if p not in period_order]

    df = df.copy()
    df[period_col] = pd.Categorical(df[period_col], categories=order, ordered=True)
    df = df.sort_values(period_col)

    colors = {"Previous Month": "#aec7e8", "Last Month": "#1f77b4"}

    n_metrics = min(len(num_cols), 4)
    n_cols = min(2, n_metrics)
    n_rows = (n_metrics + 1) // 2

    fig = make_subplots(
        rows=n_rows, cols=n_cols,
        subplot_titles=[c.replace("_", " ").title() for c in num_cols[:n_metrics]],
    )
    for i, metric in enumerate(num_cols[:n_metrics]):
        row, col = i // n_cols + 1, i % n_cols + 1
        for period in order:
            subset = df[df[period_col] == period]
            fig.add_trace(
                go.Bar(
                    name=period,
                    x=[period],
                    y=subset[metric].values,
                    marker_color=colors.get(period, "#888"),
                    showlegend=(i == 0),
                ),
                row=row, col=col,
            )
    fig.update_layout(
        title_text=title or "Period Comparison",
        barmode="group",
        height=350 * n_rows,
    )
    return _apply_light_theme(fig)


def _comparison_bar(df, curr_cols, prev_cols, str_cols, title):
    label_col = str_cols[0] if str_cols else None
    pairs = []
    for cc in curr_cols:
        metric = cc.replace("current_", "")
        pc = f"previous_{metric}"
        if pc in prev_cols:
            pairs.append((metric, cc, pc))
    if not pairs:
        return None
    n_cols = min(2, len(pairs))
    n_rows = (len(pairs) + 1) // 2
    fig = make_subplots(rows=n_rows, cols=n_cols,
                        subplot_titles=[p[0].replace("_", " ").title() for p in pairs])
    for i, (metric, cc, pc) in enumerate(pairs):
        row, col = i // n_cols + 1, i % n_cols + 1
        x = df[label_col].astype(str) if label_col else [f"Row {j}" for j in range(len(df))]
        fig.add_trace(go.Bar(name="Current",  x=x, y=df[cc], marker_color="#1f77b4", showlegend=(i == 0)), row=row, col=col)
        fig.add_trace(go.Bar(name="Previous", x=x, y=df[pc], marker_color="#aec7e8", showlegend=(i == 0)), row=row, col=col)
    fig.update_layout(title_text=title or "Period Comparison", barmode="group",
                      height=350 * n_rows)
    return _apply_light_theme(fig)


def _time_series(df, date_col, num_cols, title):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values(date_col)
    fig = go.Figure()
    for col in num_cols[:5]:
        fig.add_trace(go.Scatter(x=df[date_col], y=df[col],
                                 mode="lines+markers",
                                 name=col.replace("_", " ").title()))
    fig.update_layout(title_text=title or "Trend Over Time",
                      xaxis_title="Date", height=400)
    return _apply_light_theme(fig)


def _ranking_bar(df, label_col, value_col, title):
    try:
        df = df.nlargest(15, value_col)
    except Exception:
        df = df.head(15)
    fig = px.bar(df.sort_values(value_col), x=value_col, y=label_col,
                 orientation="h", title=title or f"Top {label_col} by {value_col}",
                 color_discrete_sequence=["#1f77b4"])
    fig.update_layout(height=max(300, len(df) * 28), yaxis_title="")
    return _apply_light_theme(fig)