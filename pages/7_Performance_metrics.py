import streamlit as st
import os
import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
import re
from collections import Counter

# ----- AUTHENTICATION SETUP -----
def get_secret(key_name):
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    try:
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

def connect_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    try:
        if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            return gspread.authorize(creds).open("Content Performance Tracker")
    except Exception:
        pass

    if os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    elif os.path.exists("../credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    else:
        st.error("❌ No Google credentials found")
        st.stop()

    return gspread.authorize(creds).open("Content Performance Tracker")

# ----- CONFIG -----
SENTIMENT_TAB = "Sentiment_Results_All"
YOUTUBE_TAB = "YouTube Data"
REDDIT_TAB = "Reddit Posts"
OUTPUT_TAB = "Content_Insights"

# ----- HELPERS -----
def safe_get_df(sheet, tab):
    try:
        return pd.DataFrame(sheet.worksheet(tab).get_all_records())
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()

def clean_numeric(df, col):
    return pd.to_numeric(df[col], errors="coerce").fillna(0) if col in df.columns else 0

def extract_keywords(text_series, top_n=5):
    words = []
    for t in text_series.dropna():
        words += re.findall(r"\b[a-zA-Z]{4,}\b", t.lower())
    return [w for w, _ in Counter(words).most_common(top_n)]

# ----- METRIC LOGIC -----
def calculate_metrics():
    sheet = connect_sheets()
    yt = safe_get_df(sheet, YOUTUBE_TAB)
    rd = safe_get_df(sheet, REDDIT_TAB)
    sent = safe_get_df(sheet, SENTIMENT_TAB)

    metrics = {}

    # ---- YouTube ----
    if not yt.empty:
        yt["Views"] = clean_numeric(yt, "Views")
        yt["Likes"] = clean_numeric(yt, "Likes")
        yt["Comments"] = clean_numeric(yt, "Comments")

        yt["Engagement"] = ((yt["Likes"] + yt["Comments"]) / yt["Views"].replace(0, 1)) * 100
        metrics["yt_avg_engagement"] = round(yt["Engagement"].mean(), 2)

        keywords = extract_keywords(yt["Video Title"])
        metrics["yt_insight"] = f"High-performing videos often use keywords like: {', '.join(keywords)}"
    else:
        metrics["yt_avg_engagement"] = 0
        metrics["yt_insight"] = "No YouTube data available"

    # ---- Reddit ----
    if not rd.empty:
        score_col = "Upvotes" if "Upvotes" in rd.columns else "Score"
        rd[score_col] = clean_numeric(rd, score_col)
        rd["Comments"] = clean_numeric(rd, "Comments")
        rd["Engagement"] = rd[score_col] + rd["Comments"]

        metrics["red_avg_engagement"] = round(rd["Engagement"].mean(), 2)

        pain_words = extract_keywords(rd["Title"])
        metrics["red_insight"] = f"Common discussion themes include: {', '.join(pain_words)}"
    else:
        metrics["red_avg_engagement"] = 0
        metrics["red_insight"] = "No Reddit data available"

    # ---- Sentiment ----
    if not sent.empty:
        sent["Compound Score"] = clean_numeric(sent, "Compound Score")
        metrics["avg_sentiment"] = round(sent["Compound Score"].mean(), 3)
    else:
        metrics["avg_sentiment"] = 0

    return metrics, sheet

def upload_insights(sheet, m):
    data = [
        ["Metric", "Value"],
        ["YouTube Avg Engagement %", m["yt_avg_engagement"]],
        ["YouTube Insight", m["yt_insight"]],
        ["Reddit Avg Engagement", m["red_avg_engagement"]],
        ["Reddit Insight", m["red_insight"]],
        ["Avg Sentiment Score", m["avg_sentiment"]],
        ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ]

    try:
        try:
            ws = sheet.worksheet(OUTPUT_TAB)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=OUTPUT_TAB, rows="50", cols="5")

        ws.update(values=data, range_name="A1")
        st.toast("✅ Content insights updated", icon="🚀")
    except Exception as e:
        st.error(e)

# ----- STREAMLIT UI -----
st.title("📈 Content Performance & Insights")
st.markdown("Insights derived from audience behavior to guide content generation.")

if st.button("🚀 Generate Insights", type="primary"):
    with st.spinner("Analyzing data..."):
        metrics, sheet = calculate_metrics()

    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Sentiment", metrics["avg_sentiment"])
    col2.metric("YouTube Engagement", f"{metrics['yt_avg_engagement']}%")
    col3.metric("Reddit Engagement", metrics["red_avg_engagement"])

    st.divider()
    st.subheader("🧠 Actionable Insights")
    st.info(metrics["yt_insight"])
    st.success(metrics["red_insight"])

    upload_insights(sheet, metrics)
