# ── GCP Projects ──────────────────────────────────────────
BQ_PROJECT         = "funnel-data"
BQ_BILLING_PROJECT = "generative-insights-poc-bi"
LLM_PROJECT        = "generative-insights-poc-bi"
VERTEX_LOCATION    = "us-central1"
DATASET_ID         = "brookfield_dashboard"
MODEL_NAME         = "gemini-2.5-pro"

# ── Table descriptions — injected into agent instructions ─
TABLE_DESCRIPTIONS = {
    "Brookfield_1H_Social": {
        "description": "Social media performance (Meta, LinkedIn).",
        "key_columns": ["Date", "Campaign_New", "Tactic", "Strategy_Type_Social",
                        "Asset_Type_Social", "Data_Source_name",
                        "Cost", "Clicks", "Impressions"],
        "filter_note": "Always filter: Data_Source_name IN ('Brookfield Brand Campaign - Standard', 'Brookfield - Ad Account - Campaign')",
    },
    "Brookfield_1H_Search": {
        "description": "Paid search (Google Ads, Bing). Brand vs NonBrand via Tactic column.",
        "key_columns": ["Date", "Campaign_New", "Tactic", "Keyword_Search",
                        "Data_Source_name", "Cost", "Clicks",
                        "Impressions", "Internal_Link_Clicks"],
        "filter_note": "Always filter: Data_Source_name IN ('2026 - Corporate Brand Campaign - Keyword', 'Brookfield Brand Campaign - Search keyword')",
    },
    "Brookfield_1H_Programmatic": {
        "description": "Programmatic/display advertising.",
        "key_columns": ["Date", "Channels_DV360", "Audience_Type_DV360","Line_Item__Display__Video_360","Creative__Display__Video_360",
                        "Cost", "Clicks", "Impressions","Video_Completed_Views__Display__Video_360"],
        "filter_note": "Always filter: Data_Source='doubleclick_bidmanager_api:e6b3648e-2446-48ae-9031-9316e1113d86' ",
    },
    "Brookfield_1H_Executive_Summary_": {
        "description": "Cross-channel summary (Search + Social combined).",
        "key_columns": ["Date", "Channel", "Campaign_New", "Tactic",
                        "Cost", "Clicks", "Impressions"],
        "filter_note": "",
    },
}
