import streamlit as st
import os
import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv

# ---------------- AUTHENTICATION ----------------

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
        st.error("❌ Google credentials not found")
        st.stop()

    return gspread.authorize(creds).open("Content Performance Tracker")

# ---------------- CONFIG ----------------

SENTIMENT_TAB = "Sentiment_Results_All"
YOUTUBE_TAB = "YouTube Data"
REDDIT_TAB = "Reddit Posts"
OUTPUT_TAB = "Content_Insights"

# ---------------- HELPERS ----------------

@st.cache_data(show_spinner=False)
def safe_get_df(sheet, tab_name):
    """Safely load a worksheet into DataFrame"""
    try:
        ws = sheet.worksheet(tab_name)
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()

def clean_numeric(df, col):
    """Convert column to numeric safely"""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series([0] * len(df))

# ---------------- METRIC CALCULATION ----------------

def calculate_metrics():
    sheet = connect_sheets()

    df_sent = safe_get_df(sheet, SENTIMENT_TAB)
    df_yt = safe_get_df(sheet, YOUTUBE_TAB)
    df_red = safe_get_df(sheet, REDDIT_TAB)

    metrics = {}

    # ---------- YOUTUBE ----------
    if not df_yt.empty:
        df_yt["Views"] = clean_numeric(df_yt, "Views")
        df_yt["Likes"] = clean_numeric(df_yt, "Likes")
        df_yt["Comments"] = clean_numeric(df_yt, "Comments")

        df_yt = df_yt[df_yt["Views"] > 0]

        df_yt["Engagement"] = (
            (df_yt["Likes"] + df_yt["Comments"]) / df_yt["Views"]
        ) * 100

        metrics["yt_avg_engagement"] = round(df_yt["Engagement"].mean(), 2)

        if not df_yt.empty:
            top = df_yt.sort_values("Views", ascending=False).iloc[0]
            metrics["yt_top_content"] = f"{top.get('Video Title', 'Unknown')} ({int(top['Views'])} views)"
        else:
            metrics["yt_top_content"] = "No Valid Data"
    else:
        metrics["yt_avg_engagement"] = 0
        metrics["yt_top_content"] = "No Data"

    # ---------- REDDIT ----------
    if not df_red.empty:
        upvote_col = "Upvotes" if "Upvotes" in df_red.columns else "Score"
        df_red[upvote_col] = clean_numeric(df_red, upvote_col)
        df_red["Comments"] = clean_numeric(df_red, "Comments")

        df_red = df_red[(df_red[upvote_col] > 0)]

        df_red["Engagement"] = df_red[upvote_col] + df_red["Comments"]

        metrics["red_avg_engagement"] = round(df_red["Engagement"].mean(), 2)

        if not df_red.empty:
            top = df_red.sort_values(upvote_col, ascending=False).iloc[0]
            metrics["red_top_content"] = f"{top.get('Title', 'Unknown')} ({int(top[upvote_col])} upvotes)"
        else:
            metrics["red_top_content"] = "No Valid Data"
    else:
        metrics["red_avg_engagement"] = 0
        metrics["red_top_content"] = "No Data"

    # ---------- SENTIMENT ----------
    if not df_sent.empty:
        score_col = "Compound Score" if "Compound Score" in df_sent.columns else None
        label_col = "Sentiment Label" if "Sentiment Label" in df_sent.columns else None

        if score_col:
            df_sent[score_col] = clean_numeric(df_sent, score_col)
            metrics["avg_sentiment"] = round(df_sent[score_col].mean(), 3)
        else:
            metrics["avg_sentiment"] = 0

        if label_col:
            metrics["pos_pct"] = round((df_sent[label_col].str.lower() == "positive").mean() * 100, 1)
            metrics["neg_pct"] = round((df_sent[label_col].str.lower() == "negative").mean() * 100, 1)
            metrics["neu_pct"] = round((df_sent[label_col].str.lower() == "neutral").mean() * 100, 1)
        else:
            metrics["pos_pct"] = metrics["neg_pct"] = metrics["neu_pct"] = 0

        metrics["total_items"] = len(df_sent)
    else:
        metrics.update({
            "avg_sentiment": 0,
            "pos_pct": 0,
            "neg_pct": 0,
            "neu_pct": 0,
            "total_items": 0
        })

    return metrics, sheet

# ---------------- UPLOAD ----------------

def upload_insights(sheet, metrics):
    data = [
        ["Metric", "Value"],
        ["YouTube Avg Engagement %", metrics["yt_avg_engagement"]],
        ["Top YouTube Video", metrics["yt_top_content"]],
        ["Reddit Avg Engagement", metrics["red_avg_engagement"]],
        ["Top Reddit Post", metrics["red_top_content"]],
        ["Avg Sentiment Score", metrics["avg_sentiment"]],
        ["Positive Sentiment %", f"{metrics['pos_pct']}%"],
        ["Negative Sentiment %", f"{metrics['neg_pct']}%"],
        ["Neutral Sentiment %", f"{metrics['neu_pct']}%"],
        ["Total Items Analyzed", metrics["total_items"]],
        ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ]

    try:
        try:
            ws = sheet.worksheet(OUTPUT_TAB)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(OUTPUT_TAB, rows="50", cols="5")

        ws.update(values=data, range_name="A1")
        st.toast("✅ Content Insights updated!", icon="🚀")
    except Exception as e:
        st.error(f"Upload failed: {e}")

# ---------------- STREAMLIT UI ----------------

st.title("📈 Content Performance & Insights")
st.markdown("Aggregated metrics from YouTube, Reddit, and Sentiment Analysis.")

if st.button("🚀 Generate Performance Report", type="primary"):
    with st.spinner("Calculating metrics..."):
        metrics, sheet = calculate_metrics()

    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Sentiment", metrics["avg_sentiment"])
    col2.metric("YouTube Engagement", f"{metrics['yt_avg_engagement']}%")
    col3.metric("Reddit Engagement", metrics["red_avg_engagement"])

    st.divider()

    st.subheader("🏆 Top Performing Content")
    st.info(f"**YouTube:** {metrics['yt_top_content']}")
    st.success(f"**Reddit:** {metrics['red_top_content']}")

    st.divider()

    st.subheader("📊 Sentiment Breakdown")
    c1, c2, c3 = st.columns(3)
    c1.metric("Positive", f"{metrics['pos_pct']}%")
    c2.metric("Negative", f"{metrics['neg_pct']}%")
    c3.metric("Neutral", f"{metrics['neu_pct']}%")

    if sheet:
        upload_insights(sheet, metrics)
