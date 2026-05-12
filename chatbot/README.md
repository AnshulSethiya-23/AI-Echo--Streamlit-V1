# Brookfield Marketing Analytics Chatbot

A conversational AI chatbot for Brookfield paid media analytics — powered by **Google ADK**, **Gemini 2.5 Pro**, and **BigQuery**. Supports text and voice input, auto-generates SQL, and renders interactive Plotly charts.

---

## Repository Structure

```
├── app.py               # Streamlit frontend (GCP-ready, no tunnel)
├── agent.py             # Google ADK agent + BigQuery tools
├── charts.py            # Auto chart generation (Plotly)
├── config.py            # GCP project settings & table definitions
├── logo.png             # Brookfield logo
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container definition for Cloud Run
├── cloudbuild.yaml      # CI/CD pipeline (Cloud Build → Cloud Run)
├── .gitignore
├── .dockerignore
└── Brookfield_Chatbot_Google_ADK_with_Google_Speech_to_Text.ipynb  # Original notebook (Colab + tunnel version)
```

---

## Prerequisites

| Requirement | Detail |
|---|---|
| GCP Project | `generative-insights-poc-bi` (LLM) + `funnel-data` (BigQuery) |
| APIs enabled | Vertex AI, BigQuery, Cloud Speech-to-Text, Cloud Run, Cloud Build, Container Registry |
| Service Account | Needs roles: `BigQuery Data Viewer`, `BigQuery Job User`, `Vertex AI User`, `Cloud Speech Client` |

---

## Local Development

### 1. Clone & install

```bash
git clone https://github.com/YOUR_ORG/brookfield-chatbot.git
cd brookfield-chatbot
pip install -r requirements.txt
```

### 2. Authenticate

```bash
gcloud auth application-default login
gcloud config set project generative-insights-poc-bi
```

### 3. Set environment variables

```bash
export GOOGLE_CLOUD_PROJECT=generative-insights-poc-bi
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=1
```

### 4. Run locally

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## Deploy to GCP Cloud Run

### Option A — Manual deploy (one-time)

```bash
# 1. Build & push image
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/brookfield-chatbot

# 2. Deploy to Cloud Run
gcloud run deploy brookfield-chatbot \
  --image gcr.io/YOUR_PROJECT_ID/brookfield-chatbot \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=1
```

Cloud Run will output a permanent HTTPS URL — no tunnel needed.

### Option B — CI/CD via Cloud Build (recommended)

Connect your GitHub repo to Cloud Build:

1. Go to **Cloud Build → Triggers** in GCP Console
2. Click **Connect Repository** → select your GitHub repo
3. Create a trigger on `push to main` using `cloudbuild.yaml`

Every push to `main` will automatically build and deploy.

---

## Environment Variables (Cloud Run)

| Variable | Value |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Your GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` |
| `GOOGLE_GENAI_USE_VERTEXAI` | `1` |

Set these under **Cloud Run → Service → Edit & Deploy New Revision → Variables**.

---

## Service Account Permissions

The Cloud Run service identity needs these IAM roles:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/speech.client"
```

---

## Notes

- The original **Colab notebook** (`*.ipynb`) includes Cloudflare tunnel setup for quick sharing — it is kept as-is for reference.
- The Python files in this repo are the **GCP-ready version** — no tunnel required since Cloud Run provides a permanent HTTPS URL.
- `google.auth.default()` is used throughout — on Cloud Run this automatically picks up the attached service account credentials.
