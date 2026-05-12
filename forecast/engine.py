"""
forecast/engine.py

Abstraction layer for time-series forecasting.

Backend is controlled by the FORECAST_BACKEND environment variable:
  - "prophet"   (default) : runs locally via the prophet package
  - "timesfm"             : calls TimesFM on Vertex AI (deploy first — see below)

TimesFM deployment checklist (Vertex AI):
  1. Enable Vertex AI API in your GCP project
  2. Deploy TimesFM from the Vertex AI Model Garden (or custom container)
  3. Set these env vars in .env / Cloud Run / Docker:
       FORECAST_BACKEND=timesfm
       TIMESFM_ENDPOINT_ID=<your endpoint resource ID>
       VERTEX_PROJECT=<your GCP project ID>
       VERTEX_LOCATION=us-central1          # or your region
  4. grant the service account roles/aiplatform.user

Public API
----------
  generate_forecast(df, horizon) -> tuple[pd.DataFrame, pd.DataFrame]
    df       : DataFrame with columns 'ds' (datetime64) and 'y' (float)
    horizon  : int, number of future days to forecast
    returns  : (df_future, df_insample)
               df_future   — [ds, yhat, yhat_lower, yhat_upper] for future dates
               df_insample — [ds, yhat, yhat_lower, yhat_upper] for historical dates
                             (Prophet's fitted values — lets you compare model vs actuals)
                             May be None for backends that don't support in-sample output.
"""

import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ── Backend selection ──────────────────────────────────────────────────────────
FORECAST_BACKEND = os.getenv("FORECAST_BACKEND", "prophet").lower()


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_forecast(
    df: pd.DataFrame, horizon: int
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """
    Generate a point forecast + 80% CI for the given time series.

    Parameters
    ----------
    df      : DataFrame with columns:
                 'ds' — datetime64, the observation date
                 'y'  — float, the metric value
              Must have at least 14 rows. No gaps required (Prophet fills them).
    horizon : int, 7–90 — number of calendar days to forecast forward from
              the last observed date in df.

    Returns
    -------
    (df_future, df_insample)
      df_future   : DataFrame [ds, yhat, yhat_lower, yhat_upper], length == horizon.
                    Future dates only.
      df_insample : DataFrame [ds, yhat, yhat_lower, yhat_upper] for historical dates
                    — Prophet's fitted values over the training window.
                    Allows visual comparison of model fit vs actuals.
                    None for backends that don't support in-sample output (TimesFM).

    Raises
    ------
    ValueError   if df is empty, missing columns, or horizon is out of range.
    RuntimeError if the selected backend is unavailable or the forecast fails.
    """
    _validate_input(df, horizon)

    if FORECAST_BACKEND == "timesfm":
        return _run_timesfm(df, horizon)
    return _run_prophet(df, horizon)


# ── Validation ─────────────────────────────────────────────────────────────────

def _validate_input(df: pd.DataFrame, horizon: int) -> None:
    if df is None or df.empty:
        raise ValueError("Input DataFrame is empty — cannot generate a forecast.")
    missing = {"ds", "y"} - set(df.columns)
    if missing:
        raise ValueError(f"Input DataFrame is missing required columns: {missing}")
    if not (7 <= horizon <= 90):
        raise ValueError(
            f"Horizon must be between 7 and 90 days (got {horizon})."
        )
    if len(df) < 14:
        raise ValueError(
            f"Insufficient history: need ≥14 daily observations, got {len(df)}. "
            "Widen the date range or choose a different metric."
        )


# ── Prophet (local fallback) ───────────────────────────────────────────────────

def _run_prophet(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    Fits a Facebook/Meta Prophet model and returns the forecast DataFrame.

    Prophet configuration rationale:
      - weekly_seasonality=True  : ad campaigns have strong Mon–Sun patterns
      - daily_seasonality=False  : data is already daily aggregated
      - yearly_seasonality="auto": activates if > 1 year of history available
      - interval_width=0.80      : 80% CI as required
      - changepoint_prior_scale=0.05 : conservative — prevents overfitting to
                                       campaign-driven spend spikes
      - uncertainty_samples=200  : faster than default 1000, still gives reliable CIs
    """
    try:
        from prophet import Prophet
    except ImportError:
        raise RuntimeError(
            "The 'prophet' package is not installed. "
            "Run: pip install prophet"
        )

    # Suppress Stan/CmdStanPy output which pollutes Streamlit logs
    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality="auto",
        interval_width=0.80,
        changepoint_prior_scale=0.05,
        uncertainty_samples=200,
    )

    model.fit(df[["ds", "y"]].copy())

    # include_history=True so we get fitted values for historical dates in one call.
    # We then split at the last observed date to produce both outputs.
    future   = model.make_future_dataframe(periods=horizon, freq="D", include_history=True)
    forecast = model.predict(future)

    _cols      = ["ds", "yhat", "yhat_lower", "yhat_upper"]
    last_hist  = df["ds"].max()

    df_future   = (
        forecast[forecast["ds"] > last_hist][_cols]
        .reset_index(drop=True)
    )
    df_insample = (
        forecast[forecast["ds"] <= last_hist][_cols]
        .reset_index(drop=True)
    )

    return df_future, df_insample


# ── TimesFM on Vertex AI (stub — wire in when endpoint is deployed) ────────────

def _run_timesfm(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    Calls TimesFM on Vertex AI for zero-shot time-series forecasting.

    This implementation is a ready-to-use stub. The input/output contract is
    identical to _run_prophet so the swap from Prophet to TimesFM is transparent
    to tab_forecast.py.

    Required environment variables:
      TIMESFM_ENDPOINT_ID  — Vertex AI endpoint resource ID
      VERTEX_PROJECT       — GCP project ID (falls back to GCP_PROJECT_ID)
      VERTEX_LOCATION      — region, default "us-central1"

    TimesFM Vertex AI endpoint schema (adjust field names to match your deployment):
      Request:  {"instances": [{"context": [y1, y2, ...], "horizon": N, "freq": "D"}]}
      Response: {"predictions": [{"mean": [...], "p10": [...], "p90": [...]}]}
    """
    try:
        from google.cloud import aiplatform
    except ImportError:
        raise RuntimeError(
            "google-cloud-aiplatform is not installed. "
            "Run: pip install google-cloud-aiplatform"
        )

    endpoint_id = os.getenv("TIMESFM_ENDPOINT_ID")
    project     = os.getenv("VERTEX_PROJECT", os.getenv("GCP_PROJECT_ID"))
    location    = os.getenv("VERTEX_LOCATION", "us-central1")

    if not endpoint_id:
        raise RuntimeError(
            "TIMESFM_ENDPOINT_ID is not set. "
            "Deploy TimesFM on Vertex AI and add it to your .env, "
            "or set FORECAST_BACKEND=prophet to use the local Prophet fallback."
        )
    if not project:
        raise RuntimeError(
            "VERTEX_PROJECT (or GCP_PROJECT_ID) is not set in the environment."
        )

    aiplatform.init(project=project, location=location)
    endpoint = aiplatform.Endpoint(endpoint_id)

    y_values = df["y"].tolist()
    instances = [
        {
            "context": y_values,
            "horizon": horizon,
            "freq": "D",
        }
    ]

    logger.info(
        "Calling TimesFM endpoint %s with %d context points, horizon=%d",
        endpoint_id, len(y_values), horizon,
    )

    response = endpoint.predict(instances=instances)
    pred = response.predictions[0]

    last_date    = pd.to_datetime(df["ds"].max())
    future_dates = pd.date_range(
        start=last_date + pd.Timedelta(days=1),
        periods=horizon,
        freq="D",
    )

    # Field names — adjust to match actual TimesFM response schema once deployed.
    # TimesFM is zero-shot and doesn't return in-sample fitted values,
    # so df_insample is None for this backend.
    df_future = pd.DataFrame({
        "ds":          future_dates,
        "yhat":        pred.get("mean",  pred.get("forecast", [0.0] * horizon)),
        "yhat_lower":  pred.get("p10",   pred.get("lower",    [0.0] * horizon)),
        "yhat_upper":  pred.get("p90",   pred.get("upper",    [0.0] * horizon)),
    })
    return df_future, None
