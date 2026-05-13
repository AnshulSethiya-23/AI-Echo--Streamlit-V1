# Brookfield Dashboard v2 — Developer Guide

A practical reference for understanding the codebase, adding charts, and debugging issues. Written for someone reviewing the code for the first time or returning after time away.

---

## 1. Project Layout

```
brookfield-dashboard-streamlit-v2/
│
├── app.py                        ← Entry point. Run with: streamlit run app.py
│
├── config/
│   └── charts_config.yaml        ← SQL + chart type definitions for all standard charts
│
├── modules/
│   ├── bq_engine.py              ← BigQuery client + run_query() / run_query_with_delta()
│   ├── config_loader.py          ← Reads charts_config.yaml, groups charts by tab
│   └── charts.py                 ← All Plotly figure builders + Streamlit renderers
│
├── tabs/
│   ├── tab_exec_summary.py       ← Executive Summary tab
│   ├── tab_search.py             ← Search tab
│   ├── tab_social.py             ← Social tab
│   ├── tab_programmatic.py       ← Programmatic tab
│   ├── tab_insights.py           ← Insights tab
│   ├── tab_chatbot.py            ← AI chatbot tab
│   ├── tab_ga4.py                ← Google Analytics 4 tab
│   └── tab_forecast.py           ← Forecasting tab (Prophet / TimesFM)
│
├── forecast/
│   ├── __init__.py
│   └── engine.py                 ← Forecast engine: Prophet now, TimesFM when deployed
│
├── chatbot/
│   ├── agent.py                  ← Google ADK agent (chat + create_session)
│   └── charts.py                 ← AI-generated chart helper (ai_chart)
│
├── insights/                     ← Placeholder for future insights logic
├── ga4_agent/                    ← Placeholder for GA4 ADK agent
├── google_ads_agent/             ← Placeholder for Google Ads ADK agent
│
├── Dockerfile                    ← Container definition for Cloud Run
├── cloudbuild.yaml               ← GCP Cloud Build CI/CD pipeline
├── requirements.txt              ← Python dependencies
└── .env                          ← Local secrets (never commit this)
                                     GCP_PROJECT_ID, BQ_DATASET, etc.
```

---

## 2. How the Dashboard Works (Data Flow)

Understanding this flow saves a lot of time when debugging or adding new features.

```
User changes date range in sidebar
        │
        ▼
app.py re-runs → passes start_str / end_str to each tab
        │
        ▼
Each tab is a @st.fragment — only the active tab re-renders
        │
        ▼
Tab calls run_query(sql_template, start_date, end_date)
        │
        ├── bq_engine.py fills in {project}, {dataset}, {start_date}, {end_date}
        ├── Result is cached for 1 hour via @st.cache_data(ttl=3600)
        └── Returns a pandas DataFrame
        │
        ▼
Tab calls render_scorecard() / render_chart() / render_table()
        │
        └── charts.py builds a Plotly Figure and calls st.plotly_chart()
```

**Two ways charts get their SQL:**

| Route | Used by | Where the SQL lives |
|-------|---------|---------------------|
| YAML config | Scorecards, standard trend/bar charts, tables | `config/charts_config.yaml` |
| Inline SQL | Complex/bespoke charts (bubble, heatmap, deep analysis) | Directly in the tab file |

The YAML route is cleaner for anything you might want to reuse or swap. The inline route is faster for one-off charts that are specific to a single tab.

---

## 3. Adding a New Chart or Graph

### Route A — Standard chart via YAML (recommended for most charts)

Use this for: scorecards, line/area trends, bar charts, tables.

**Step 1 — Add an entry to `config/charts_config.yaml`**

Every chart entry needs these fields:

```yaml
- id: search_new_metric          # unique ID, lowercase with underscores
  tab: search                    # which tab it belongs to (see tab names below)
  title: "My New Metric"         # shown as chart title
  chart_type: line               # see chart types below
  metric_col: my_metric          # only needed for scorecard type
  format: currency               # optional: currency | percent | number
  sql: |
    SELECT
      DATE(Date)        AS date,
      SUM(MyColumn)     AS my_metric
    FROM `{project}.{dataset}.Brookfield_1H_Search`
    WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY date
    ORDER BY date
```

**Tab name values** (must match exactly):

| Tab | `tab` value in YAML |
|-----|---------------------|
| Executive Summary | `exec_summary` |
| Search | `search` |
| Social | `social` |
| Programmatic | `programmatic` |

**Chart type values:**

| `chart_type` | What renders |
|---|---|
| `scorecard` | `st.metric` KPI card with period-over-period delta |
| `line` | Plotly line chart (lines + markers) |
| `area` | Plotly area chart (fill to zero) |
| `bar` | Plotly grouped bar chart |
| `grouped_bar` | Same as bar |
| `stacked_bar` | Plotly stacked bar chart |
| `pie` | Plotly donut chart |
| `table` | `st.dataframe` summary table |

**Step 2 — Control where it appears in the tab**

The tab files automatically pull charts from the YAML by type. In each tab file:

```python
viz_charts   = get_viz_charts_for_tab(TAB)
trend_charts = [c for c in viz_charts if c["chart_type"] in {"line", "area"}]
dist_charts  = [c for c in viz_charts if c["chart_type"] in {"bar", "grouped_bar", "stacked_bar"}]
```

- Trend charts (`line`, `area`) render in section **2. Performance Trends** — two per row
- Distribution charts (`bar`, `stacked_bar`) render in section **3. Channel/Campaign Breakdown** — two per row
- Scorecards render in section **1. Key Metrics** — left to right in YAML order
- Tables render in section **4. Data Summary** — stacked vertically

**So to control order:** arrange entries in `charts_config.yaml` in the order you want them to appear. Scorecards and tables render in YAML order. Trend and distribution charts each render left-to-right, two per row, in YAML order.

That's it. No code change needed — just save the YAML and restart Streamlit.

---

### Route B — Inline / bespoke chart (for one-off complex charts)

Use this for: bubble/scatter charts, heatmaps, or anything needing custom SQL that doesn't fit the standard column format.

**Step 1 — Write the SQL directly in the tab file**

Open the relevant tab file (e.g. `tabs/tab_search.py`) and add a SQL string:

```python
_SQL_MY_CHART = """
SELECT
  Campaign_New                                   AS campaign,
  ROUND(SAFE_DIVIDE(SUM(Cost), SUM(Clicks)), 4)  AS cpc,
  ROUND(SUM(Cost), 2)                            AS spend
FROM `{project}.{dataset}.Brookfield_1H_Search`
WHERE DATE(Date) BETWEEN '{start_date}' AND '{end_date}'
GROUP BY campaign
ORDER BY spend DESC
LIMIT 20
"""
```

**Step 2 — Run the query and render**

Inside the `render()` function, call `run_query()` and pass the result to a chart builder:

```python
df = run_query(sql_template=_SQL_MY_CHART, start_date=start_date, end_date=end_date)

# Option A — use an existing chart builder from charts.py
fig = build_bubble(
    df=df,
    x_col="cpc", y_col="ctr",
    size_col="spend", label_col="campaign",
    title="Campaign Efficiency",
    x_label="CPC ($)", y_label="CTR (%)",
    add_mean_lines=True,
)
if fig:
    st.plotly_chart(fig, use_container_width=True)

# Option B — build a custom Plotly figure inline
import plotly.graph_objects as go
fig = go.Figure()
fig.add_trace(go.Bar(x=df["campaign"], y=df["spend"]))
st.plotly_chart(fig, use_container_width=True)
```

**Step 3 — Control where it appears**

The tab files are plain Python. Place the `st.plotly_chart()` call wherever you want it in the `render()` function. The sections in each tab file are numbered with comments — add your chart to the relevant section, or create a new `st.divider()` + `st.markdown("#### ...")` block.

---

### Route C — Adding a chart builder to `charts.py` (for reuse across tabs)

If you're building a chart type that multiple tabs will share, add a new `build_*` function to `modules/charts.py`:

```python
@st.cache_data(show_spinner=False)
def build_my_chart(df: pd.DataFrame, ...) -> go.Figure | None:
    if df is None or df.empty:
        return None
    fig = go.Figure()
    # ... build the figure ...
    fig.update_layout(**CHART_LAYOUT)
    return fig
```

Then import and call it from any tab file:

```python
from modules.charts import build_my_chart
```

Use `@st.cache_data` on the builder so the same data never rebuilds the figure twice in a session.

---

## 4. Adding a New Tab

1. Create `tabs/tab_mynewtab.py` using this skeleton:

```python
import streamlit as st
from modules.bq_engine import run_query
from modules.charts import render_chart  # or whatever you need

@st.fragment
def render(start_date: str, end_date: str) -> None:
    st.subheader("My New Tab")
    st.caption(f"Reporting period: **{start_date}** to **{end_date}**")

    # your sections here
```

2. In `app.py`, import the tab and add it to the `st.tabs()` list:

```python
from tabs import tab_mynewtab   # add to the import block

tabs = st.tabs([
    # ... existing tabs ...
    "🆕 My New Tab",             # add here — order in list = order in UI
])

with tabs[8]:                   # index must match position in the list
    tab_mynewtab.render(start_str, end_str)
```

The tab label emoji and text are arbitrary — just pick something clear.

---

## 5. Controlling Chart Order and Layout

| What you want | What to change |
|---|---|
| Reorder scorecards (KPI cards) | Reorder the `scorecard` entries for that tab in `charts_config.yaml` |
| Reorder trend line/area charts | Reorder the `line`/`area` entries for that tab in `charts_config.yaml` |
| Reorder bar charts | Reorder the `bar`/`stacked_bar` entries for that tab in `charts_config.yaml` |
| Put two charts side-by-side | They automatically go two-per-row. No config needed — just have an even number of them |
| Put a chart alone on a full row | Wrap it in `st.columns([1])` — one column takes full width |
| Add a new section heading | Add `st.markdown("#### 🔥 My Section")` + `st.divider()` in the tab file |
| Move the Deep Analysis section | It's the last section in each tab file — just cut/paste the block higher in `render()` |

---

## 6. The BigQuery Tables

All four source tables are in `{project}.{dataset}` (set via `GCP_PROJECT_ID` and `BQ_DATASET` in `.env`).

| Table | Used by | Key columns |
|---|---|---|
| `Brookfield_1H_Executive_Summary_` | exec_summary | Date, Channel, Cost, Clicks, Impressions |
| `Brookfield_1H_Search` | search | Date, Data_Source_name, Campaign_New, Cost, Clicks, Impressions |
| `Brookfield_1H_Social` | social | Date, Data_Source_name, Cost, Clicks, Impressions |
| `Brookfield_1H_Programmatic` | programmatic | Date, Data_Source, Channels_DV360, Cost, Impressions, Video_Completed_Views__Display__Video_360 |

**Important quirks:**
- `Date` is a `DATETIME` column — always wrap it: `DATE(Date)` before comparing or grouping
- Use `SAFE_DIVIDE(a, b)` instead of `a / b` — avoids divide-by-zero errors
- Spend is in the `Cost` column, not `Spend`
- Filter programmatic data by `Data_Source = 'doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86'`
- Filter search data by `Data_Source_name IN ('2026 - Corporate Brand Campaign - Keyword', 'Brookfield Brand Campaign - Search keyword')`
- Filter social data by `Data_Source_name IN ('Brookfield Brand Campaign - Standard', 'Brookfield - Ad Account - Campaign')`

---

## 7. Sidebar Architecture

The sidebar has three mutually exclusive sections, each controlled by a client-side JS `MutationObserver`. Only one section is visible at a time, determined by the active tab.

| Section | Visible on | Sentinel attrs |
|---|---|---|
| Date filters | All tabs except Insights (4) and Chatbot (5) | `filter-start` / `filter-end` |
| Insights filters | Insights tab (index 4) | `insights-start` / `insights-end` |
| Chatbot controls | Chatbot tab (index 5) | `chatbot-start` / `chatbot-end` |

**How it works:**
The JS in the second `components.html()` block in `app.py` reads `aria-selected` on `[data-baseweb="tab"]` elements to determine the active tab index. It then calls `toggleSection(startAttr, endAttr, show)` which finds all sidebar DOM children between the two sentinel `<span data-bl="...">` elements and sets `display: none` or `display: ''` on them.

**Adding a new sidebar section for a new tab:**

1. In `app.py`, add a `with st.sidebar:` block containing:
   - An opening sentinel: `st.markdown('<span data-bl="mysection-start" style="display:none"></span>', unsafe_allow_html=True)`
   - Your sidebar widgets
   - A closing sentinel: `st.markdown('<span data-bl="mysection-end" style="display:none"></span>', unsafe_allow_html=True)`

2. In the `updateSidebar()` JS function, add a `toggleSection` call for the new tab index:
   ```javascript
   toggleSection('mysection-start', 'mysection-end', activeIdx === 6);
   ```

3. For any widgets moved from a tab into the sidebar: keep the same `key=` so the tab can read the value via `st.session_state.get("my_key", default)` without declaring a second widget.

**Gotcha — `BaseWeb` popover:** Do not add `position: relative` to `[data-baseweb="popover"]` — it breaks dropdown positioning inside the sidebar.

---

## 8. Debugging Guide

### 8.1 BigQuery / data errors

**Symptom:** `st.error("BigQuery error: ...")` shown on the page, or a chart shows "No data available."

**Where to look:** `modules/bq_engine.py` → `run_query()`. The error is caught and surfaced via `st.error()`, so you'll see it on the page.

**Steps:**
1. Copy the failing SQL from `charts_config.yaml` or the tab file
2. Paste it into the BigQuery console in GCP — replace `{project}`, `{dataset}`, `{start_date}`, `{end_date}` manually
3. Check: does the table name exist? Is the date range valid? Is `DATE(Date)` needed?
4. Check `.env` — `GCP_PROJECT_ID` and `BQ_DATASET` must be set correctly
5. Check authentication — local: ADC (`gcloud auth application-default login`). Cloud Run: set `GOOGLE_APPLICATION_CREDENTIALS_FUNNEL_DATA_BASE64` in your env (base64-encoded SA key JSON). The `app.py` bootstrap writes it to `/tmp/sa_key.json` at startup, which all GCP clients pick up automatically.

**NAType / null metric values:** BigQuery can return `pd.NA` for null columns. `run_query_with_delta()` handles this via `_safe_float()` in `bq_engine.py`. If you add a new BQ call and see `TypeError: float() argument must be a string or a real number, not 'NAType'`, import and use `_safe_float(val)` when reading numeric values from the DataFrame.

**Cache note:** `run_query` caches results for 1 hour. If you've fixed data and want a fresh result, restart Streamlit (`Ctrl+C` → `streamlit run app.py`) or wait for the cache to expire.

---

### 8.2 Chart not appearing / wrong chart

**Symptom:** Section header shows but chart is blank, or the wrong chart type renders.

**Where to look:** Depends on which route the chart uses.

**YAML chart:**
1. Open `config/charts_config.yaml`
2. Check: is `tab` value exactly right? (`exec_summary` not `exec-summary`)
3. Check: is `chart_type` a valid value? (see Section 3 above)
4. Check: does the SQL column alias match `metric_col`? (scorecard only)
5. In the tab file, add a temporary `st.write(df)` right after `run_query()` to see what the DataFrame looks like

**Inline chart:**
1. Find the chart in the tab file (search for the SQL string)
2. Add `st.write(df)` after `run_query()` to inspect the DataFrame
3. Verify column names in the DataFrame match what you pass to `build_bubble()`, `build_heatmap()`, etc.
4. Check that `build_*` functions return a `go.Figure` and not `None` — they return `None` when `df` is empty or `None`

---

### 8.3 Scorecard delta showing wrong value

**Symptom:** `st.metric` shows a delta of 0% or an incorrect percentage.

**Where to look:** `modules/bq_engine.py` → `run_query_with_delta()`.

The function automatically computes the prior period as the same length of time immediately before `start_date`. So if you're viewing Jan 1–Jan 31, the prior period is Dec 1–Dec 31. The delta is `(current - prior) / prior * 100`.

**Common cause:** The metric column name in the SQL doesn't match `metric_col` in the YAML config. Check both.

**KPI number display:** Large numbers (e.g. `312,345,678`) are automatically shortened to `312.3M` via `_fmt_abbrev()` in `modules/charts.py`. This applies to both scorecard values and bar chart labels. The helper uses a `prefix` arg for currency formatting (`$312.3M`). If you add a new scorecard and the number looks truncated, check that `render_scorecard()` is calling `_fmt_abbrev()` and that your `format` field in the YAML is set correctly (`currency`, `percent`, or `number`).

---

### 8.4 Heatmap columns in wrong order

**Symptom:** Week columns on the heatmap are not chronological, or there are too many columns.

**Root cause and fix:** The heatmap SQL must group by week (not individual dates) and use an ISO sort key. The correct pattern — already applied in all four heatmap SQLs — is:

```sql
SELECT
  FORMAT_DATE('%A', DATE(Date))                                   AS day_of_week,
  FORMAT_DATE('%Y-%m-%d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))  AS week_iso,
  FORMAT_DATE('%b %d', DATE_TRUNC(DATE(Date), WEEK(MONDAY)))     AS week_label,
  ROUND(SUM(Cost), 2)                                             AS spend
FROM ...
GROUP BY 1, 2, 3
ORDER BY week_iso
```

And the `col_order` must be extracted like this:

```python
col_order = (
    df.drop_duplicates("week_iso")
    .sort_values("week_iso")["week_label"]
    .tolist()
)
```

If you see this bug on a new chart, apply the same pattern.

---

### 8.5 Chatbot not working

**Symptom:** "Agent error" shown in the chatbot tab, or the spinner runs indefinitely.

**Where to look:** `chatbot/agent.py` → `chat()` and `create_session()`. `tab_chatbot.py` wraps these calls in a `try/except` and shows the full traceback in a collapsible block on the page.

**Common causes:**
- `GOOGLE_CLOUD_PROJECT` or ADK credentials not set in `.env`
- ADK session expired — click "🗑️ New chat" in the sidebar to reset
- The `chat()` function returned a malformed result dict (missing `text`, `df`, or `sql` keys)

**Chatbot controls location:** The "Show SQL" toggle and "New Chat" button live in the sidebar (Chatbot section), not in the tab itself. The tab reads `show_sql` from `st.session_state.get("chatbot_show_sql", False)`. New Chat sets a `chatbot_new_chat_requested` flag in session state; the tab fragment checks and clears this flag on its next run.

**Material icon text visible in chat bubbles** (e.g. "face", "art_"): These are Material Icons ligature names leaking through when the icon font isn't applied. The JS patch in `app.py` suppresses them via a regex in `scanTextNodes()`. If a new icon name appears, add it to the `ICON_TEXT_RE` pattern in that function.

---

### 8.6 Forecast tab errors

**Symptom:** "Forecast failed: ..." error shown after clicking Generate Forecast.

**Where to look:** `forecast/engine.py` → `generate_forecast()`. Errors from Prophet or TimesFM surface via `st.error()` in `tab_forecast.py`.

**Common causes:**

| Error message | Cause | Fix |
|---|---|---|
| `Insufficient history: need ≥14 daily observations` | The date range returned fewer than 14 rows | Check that the BQ tables have data for the last 365 days. The `HAVING y > 0` clause drops zero rows |
| `prophet is not installed` | Prophet not installed in this environment | `pip install prophet` |
| `TIMESFM_ENDPOINT_ID is not set` | `FORECAST_BACKEND=timesfm` but env var missing | Add endpoint ID to `.env` or switch back to `FORECAST_BACKEND=prophet` |
| `ValueError: Input contains NaN` | The metric has null values after `HAVING y > 0` | Add `AND MyColumn IS NOT NULL` to the SQL |

**Switching backends:** Change `FORECAST_BACKEND` in `.env`. `prophet` = local (default). `timesfm` = Vertex AI endpoint. Restart Streamlit after changing.

---

### 8.7 Tab loads slowly

**Symptom:** The page takes more than a few seconds to load after a date change.

**How caching works:**
- `run_query()` caches BQ results for **1 hour** — first load is slow, subsequent loads within the hour are instant
- `build_figure()`, `build_bubble()`, `build_heatmap()` cache the Plotly Figure objects — chart rendering is only slow the first time per session
- `@st.fragment` means only the **active tab** re-renders when the date changes, not all tabs

**If it's still slow:**
- Check that `@st.cache_data` is on your `run_query()` call (it is, by default in `bq_engine.py`)
- Check that you're not calling `run_query()` more times than needed — each unique (sql, start_date, end_date) combination is a separate BQ round-trip
- Consider adding a BigQuery BI Engine reservation in GCP for sub-second cached queries
- For first-load parallelism: all BQ queries within a tab currently fire sequentially. Using `concurrent.futures.ThreadPoolExecutor` to fire them in parallel (fetch all, then render) would reduce first-load time from ~sum-of-all-queries to ~slowest-single-query. `@st.cache_data` is thread-safe so there are no race conditions.

---

### 8.8 Streamlit rerun / scope errors

**Symptom:** `StreamlitAPIException: scope="fragment" can only be specified from @st.fragment-decorated functions during fragment reruns.`

**Cause:** `st.rerun(scope="fragment")` is only valid when the rerun was triggered *from inside* the fragment (e.g. the user typed in the chat input). When the trigger comes from *outside* the fragment — such as a sidebar button click — Streamlit is doing a full-page rerun and `scope="fragment"` is invalid.

**Fix:** Wrap the rerun call in a try/except:

```python
try:
    st.rerun(scope="fragment")
except Exception:
    st.rerun()
```

This is already applied in `tab_chatbot.py`. Apply the same pattern anywhere else you see `st.rerun(scope="fragment")` that might be triggered by a sidebar interaction.

**General rule:** `scope="fragment"` is safe when the only triggers are widgets *inside* the fragment. As soon as sidebar buttons or other outside-fragment interactions can cause a rerun, use the try/except.

---

## 9. Environment Variables Reference

Set these in `.env` at the project root:

```bash
# Required
GCP_PROJECT_ID=your-gcp-project-id
BQ_DATASET=your_dataset_name

# Production auth — base64-encode your SA key JSON:
#   base64 -i sa_key.json | tr -d '\n'
GOOGLE_APPLICATION_CREDENTIALS_FUNNEL_DATA_BASE64=<base64-string>

# Forecasting — switch to TimesFM when deployed
FORECAST_BACKEND=prophet            # or: timesfm
TIMESFM_ENDPOINT_ID=                # Vertex AI endpoint resource ID
VERTEX_PROJECT=                     # GCP project (defaults to GCP_PROJECT_ID)
VERTEX_LOCATION=us-central1         # Vertex AI region
```

---

## 10. Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Authenticate with GCP (for local BigQuery access)
gcloud auth application-default login

# Set environment variables
cp .env.example .env     # edit with your project ID and dataset

# Run
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## 11. Quick Reference — Adding the Most Common Things

**New KPI scorecard on the Search tab:**
→ Add a `scorecard` entry in `charts_config.yaml` with `tab: search`. That's it.

**New line chart on the Social tab:**
→ Add a `line` entry in `charts_config.yaml` with `tab: social`. It appears in section 2, left-to-right by YAML order.

**New bar chart on the Programmatic tab:**
→ Add a `bar` entry in `charts_config.yaml` with `tab: programmatic`. It appears in section 3.

**New complex scatter chart on any tab:**
→ Write the SQL inline in the tab file. Use `build_bubble()` from `charts.py`. Place the `st.plotly_chart()` call where you want it in `render()`.

**New tab entirely:**
→ Create `tabs/tab_newtab.py`, add import + tab label + `with tabs[N]:` block in `app.py`.

**Change which BigQuery table a chart queries:**
→ Edit the `FROM` clause in the chart's `sql` in `charts_config.yaml`. No Python changes needed.

**Debug a blank chart:**
→ Add `st.write(df)` right after `run_query()` in the tab file. Check the DataFrame columns match what the chart builder expects.
