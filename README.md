# Brookfield Performance Dashboard v2

A Streamlit dashboard for monitoring Brookfield's paid media performance across Search, Social, and Programmatic channels. Built by [Brainlabs](https://www.brainlabsdigital.com).

---

## What it does

| Tab | Description |
|-----|-------------|
| 📋 Executive Summary | Cross-channel KPIs, dual-axis trend chart, channel distribution, campaign table, efficiency bubble chart, spend heatmap |
| 🔍 Search | Paid Search metrics — spend, clicks, impressions, CPC, CTR — with campaign breakdown and deep analysis |
| 📱 Social | Paid Social metrics with the same layout as Search |
| 📡 Programmatic | DV360 programmatic metrics including video completed views and CPV |
| 💡 Insights | AI-generated performance insights (MoM / QoQ / YoY) powered by Gemini on Vertex AI |
| 🤖 Chatbot | Natural-language interface to query BigQuery — ask questions, get charts |
| 📊 Google Analytics | GA4 web analytics *(work in progress — activates once property access is confirmed)* |
| 🔮 Forecasting | 30–90 day channel forecasts using Meta Prophet (or TimesFM on Vertex AI) |

All data is read from **Google BigQuery**. No data is stored locally.

---

## Prerequisites

- Python 3.11+
- A Google Cloud project with BigQuery enabled
- BigQuery tables: `Brookfield_1H_Executive_Summary_`, `Brookfield_1H_Search`, `Brookfield_1H_Social`, `Brookfield_1H_Programmatic`
- A service account (or Application Default Credentials) with `bigquery.dataViewer` and `bigquery.jobUser` roles

---

## Running locally

**1. Clone the repo**

```bash
git clone <your-repo-url>
cd brookfield-dashboard-streamlit-v2
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

> Prophet requires a C++ compiler. On macOS: `xcode-select --install`. On Linux: `apt-get install build-essential python3-dev`.

**3. Set environment variables**

```bash
cp .env.example .env
```

Edit `.env`:

```bash
GCP_PROJECT_ID=your-gcp-project-id
BQ_DATASET=your_dataset_name

# Leave blank to use Application Default Credentials locally
GCP_SERVICE_ACCOUNT_JSON=

# Forecasting — prophet is the default (no extra setup needed)
FORECAST_BACKEND=prophet
```

**4. Authenticate with GCP**

```bash
gcloud auth application-default login
```

**5. Run**

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

---

## Deploying to Cloud Run

The project includes a `cloudbuild.yaml` for automated deployment via GCP Cloud Build.

**One-time setup**

1. Enable APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager
2. Create an Artifact Registry repository named `brookfield` in your target region
3. Store secrets in Secret Manager:
   - `BQ_DATASET` — your BigQuery dataset name
   - `BROOKFIELD_SA_KEY` — the full JSON of a service account key with BQ access
4. Grant Cloud Build the `Cloud Run Admin` and `Secret Manager Accessor` roles

**Deploy**

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=europe-west2,_REPO=brookfield,_SERVICE=brookfield-dashboard-v2
```

Or connect the repo to Cloud Build for automatic deploys on push to `main`.

**Manual deploy (Docker)**

```bash
# Build
docker build -t brookfield-dashboard .

# Run locally
docker run -p 8080:8080 \
  -e GCP_PROJECT_ID=your-project \
  -e BQ_DATASET=your_dataset \
  brookfield-dashboard
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GCP_PROJECT_ID` | Yes | GCP project ID — used for BigQuery queries |
| `BQ_DATASET` | Yes | BigQuery dataset name |
| `GCP_SERVICE_ACCOUNT_JSON` | No | Service account key JSON string. Falls back to ADC if not set |
| `FORECAST_BACKEND` | No | `prophet` (default) or `timesfm` |
| `TIMESFM_ENDPOINT_ID` | If `timesfm` | Vertex AI endpoint ID for TimesFM |
| `VERTEX_PROJECT` | No | GCP project for Vertex AI (defaults to `GCP_PROJECT_ID`) |
| `VERTEX_LOCATION` | No | Vertex AI region (default: `us-central1`) |

---

## Project structure

```
├── app.py                      ← Streamlit entry point
├── config/
│   └── charts_config.yaml      ← Chart registry: SQL + chart type per tab
├── modules/
│   ├── bq_engine.py            ← BigQuery client and query helpers
│   ├── config_loader.py        ← YAML loader and chart accessors
│   └── charts.py               ← Plotly builders and Streamlit renderers
├── tabs/                       ← One file per dashboard tab
├── chatbot/                    ← Google ADK chatbot agent
├── insights/                   ← Automated insights pipeline (Gemini)
├── forecast/                   ← Prophet / TimesFM forecast engine
├── Dockerfile
├── cloudbuild.yaml             ← GCP Cloud Build CI/CD
├── requirements.txt
└── DEVELOPER_GUIDE.md          ← Detailed guide: adding charts, debugging, BQ table reference
```

---

## Tech stack

- **Frontend:** Streamlit 1.45
- **Charts:** Plotly
- **Data:** Google BigQuery
- **AI / Chatbot:** Google ADK + Gemini on Vertex AI
- **Forecasting:** Meta Prophet (local) / TimesFM on Vertex AI
- **Deployment:** Docker + GCP Cloud Run

---

## Developer docs

For a full reference — adding charts, debugging common errors, BigQuery table schemas, and how the data flow works — see **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)**.

---

*Built by Brainlabs × Brookfield*
