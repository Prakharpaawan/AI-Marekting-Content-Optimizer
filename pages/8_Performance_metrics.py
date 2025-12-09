import streamlit as st
import os
import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv

# ----- AUTHENTICATION SETUP -----
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    try:
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # A. Try Cloud Secrets
    try:
        if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client.open("Content Performance Tracker")
    except Exception:
        pass

    # B. Try Local File
    if os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    elif os.path.exists("../credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    else:
        st.error("❌ Critical Error: No Google Credentials found!")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----
INPUT_TAB = "Sentiment_Results_All"
OUTPUT_TAB = "Content_Insights"

# ----- HELPERS -----
def safe_get_worksheet(sheet, tab_name):
    try:
        return sheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return None

def calculate_metrics():
    sheet = connect_sheets()
    ws = safe_get_worksheet(sheet, INPUT_TAB)

    if ws is None:
        st.error(f"Tab '{INPUT_TAB}' is missing. Run Sentiment Analysis first.")
        return None, None

    df = pd.DataFrame(ws.get_all_records())
    
    if df.empty:
        st.warning("No data found in Sentiment Results.")
        return None, None

    # Clean & Convert Scores
    df = df.fillna("")
    if "Compound Score" in df.columns:
        score_col = "Compound Score" 
    elif "compound" in df.columns:
        score_col = "compound"
    else:
        st.error("Could not find sentiment score column.")
        return None, None

    df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
    
    # Handle Label Column Name variations
    label_col = "Sentiment Label" if "Sentiment Label" in df.columns else "Sentiment_Label"

    # --- METRICS CALCULATION ---
    metrics = {}
    metrics["total_items"] = len(df)
    
    # Sentiment Distribution
    if label_col in df.columns:
        metrics["positive_pct"] = round((df[label_col].str.lower() == "positive").mean() * 100, 1)
        metrics["negative_pct"] = round((df[label_col].str.lower() == "negative").mean() * 100, 1)
        metrics["neutral_pct"] = round((df[label_col].str.lower() == "neutral").mean() * 100, 1)
    else:
        metrics["positive_pct"] = 0
        metrics["negative_pct"] = 0
        metrics["neutral_pct"] = 0

    metrics["avg_sentiment"] = round(df[score_col].mean(), 3)

    # Top & Bottom Content
    top_row = df.sort_values(by=score_col, ascending=False).iloc[0]
    bottom_row = df.sort_values(by=score_col, ascending=True).iloc[0]
    
    metrics["top_text"] = top_row.get("Text", "")[:150]
    metrics["bottom_text"] = bottom_row.get("Text", "")[:150]

    # Platform Analysis
    if "Source" in df.columns:
        metrics["most_active"] = df["Source"].value_counts().idxmax()
        platform_scores = df.groupby("Source")[score_col].mean()
        metrics["most_positive"] = platform_scores.idxmax()
        metrics["most_negative"] = platform_scores.idxmin()
    else:
        metrics["most_active"] = "N/A"
        metrics["most_positive"] = "N/A"
        metrics["most_negative"] = "N/A"

    # Topic Analysis
    if "Topic" in df.columns:
        metrics["common_topic"] = df["Topic"].value_counts().idxmax()
    else:
        metrics["common_topic"] = "N/A"

    return metrics, sheet

def upload_insights(sheet, metrics):
    if not metrics: return

    out_data = [
        ["Metric", "Value"],
        ["Total Items Analyzed", metrics["total_items"]],
        ["Positive Sentiment %", f"{metrics['positive_pct']}%"],
        ["Negative Sentiment %", f"{metrics['negative_pct']}%"],
        ["Neutral Sentiment %", f"{metrics['neutral_pct']}%"],
        ["Average Sentiment Score", metrics["avg_sentiment"]],
        ["Most Active Platform", metrics["most_active"]],
        ["Most Positive Platform", metrics["most_positive"]],
        ["Most Negative Platform", metrics["most_negative"]],
        ["Most Common Topic", metrics["common_topic"]],
        ["Top Content Snippet", metrics["top_text"]],
        ["Bottom Content Snippet", metrics["bottom_text"]],
        ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ]

    try:
        ws = safe_get_worksheet(sheet, OUTPUT_TAB)
        if ws:
            ws.clear()
        else:
            ws = sheet.add_worksheet(title=OUTPUT_TAB, rows="100", cols="5")
        
        ws.update(values=out_data, range_name="A1")
        st.toast("Insights uploaded to Google Sheets!", icon="🚀")
    except Exception as e:
        st.error(f"Failed to upload insights: {e}")

# ----- STREAMLIT UI -----
st.title("📈 Performance Metrics Dashboard")
st.markdown("Aggregated insights from all data sources.")

if st.button("🚀 Generate Report", type="primary"):
    with st.spinner("Calculating metrics..."):
        metrics, sheet = calculate_metrics()
    
    if metrics:
        # Key Metrics Row
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Items", metrics["total_items"])
        col2.metric("Avg Sentiment", metrics["avg_sentiment"])
        col3.metric("Positivity Rate", f"{metrics['positive_pct']}%")
        col4.metric("Negativity Rate", f"{metrics['negative_pct']}%")

        st.divider()

        # Platform Insights
        st.subheader("Platform Analysis")
        c1, c2, c3 = st.columns(3)
        c1.info(f"**Most Active:** {metrics['most_active']}")
        c2.success(f"**Most Positive:** {metrics['most_positive']}")
        c3.error(f"**Most Negative:** {metrics['most_negative']}")

        st.divider()

        # Content Highlights
        st.subheader("Content Highlights")
        
        st.write("**:trophy: Best Performing Content (Highest Sentiment)**")
        st.success(metrics["top_text"])
        
        st.write("**:warning: Lowest Performing Content (Lowest Sentiment)**")
        st.error(metrics["bottom_text"])

        # Upload
        if sheet:
            upload_insights(sheet, metrics)
