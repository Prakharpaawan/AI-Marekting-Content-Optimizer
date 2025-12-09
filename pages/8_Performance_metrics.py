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
# These names must match your Google Sheet Tabs EXACTLY
SENTIMENT_TAB = "Sentiment_Results_All"
YOUTUBE_TAB = "YouTube Data"
REDDIT_TAB = "Reddit Posts"  # Use 'Reddit Posts' to get raw upvotes/comments
OUTPUT_TAB = "Content_Insights" # This is the summary tab you want

# ----- HELPERS -----
def safe_get_df(sheet, tab_name):
    """Safely load a worksheet into a Pandas DataFrame."""
    try:
        ws = sheet.worksheet(tab_name)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()

def clean_numeric(df, col):
    """Safely convert a column to numeric, replacing errors with 0."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors='coerce').fillna(0)
    return 0

# ----- CALCULATION LOGIC -----
def calculate_metrics():
    sheet = connect_sheets()
    
    # 1. Load All Data Sources
    df_sent = safe_get_df(sheet, SENTIMENT_TAB)
    df_yt = safe_get_df(sheet, YOUTUBE_TAB)
    df_red = safe_get_df(sheet, REDDIT_TAB)

    metrics = {}

    # --- YOUTUBE METRICS ---
    if not df_yt.empty:
        df_yt["Views"] = clean_numeric(df_yt, "Views")
        df_yt["Likes"] = clean_numeric(df_yt, "Likes")
        df_yt["Comments"] = clean_numeric(df_yt, "Comments")
        
        # Engagement = (Likes + Comments) / Views * 100
        df_yt["Engagement"] = ((df_yt["Likes"] + df_yt["Comments"]) / df_yt["Views"].replace(0, 1)) * 100
        
        metrics["yt_avg_engagement"] = round(df_yt["Engagement"].mean(), 2)
        
        # Top Video
        top_vid = df_yt.sort_values(by="Views", ascending=False).iloc[0]
        metrics["yt_top_content"] = f"{top_vid.get('Video Title', 'Unknown')} ({top_vid.get('Views')} views)"
    else:
        metrics["yt_avg_engagement"] = 0
        metrics["yt_top_content"] = "No Data"

    # --- REDDIT METRICS (Fixed) ---
    if not df_red.empty:
        # Check if we have 'Upvotes' or 'Score' column (Reddit API varies)
        upvote_col = "Upvotes" if "Upvotes" in df_red.columns else "Score"
        
        df_red[upvote_col] = clean_numeric(df_red, upvote_col)
        df_red["Comments"] = clean_numeric(df_red, "Comments")
        
        # Engagement score = Upvotes + Comments
        df_red["Engagement"] = df_red[upvote_col] + df_red["Comments"]
        
        metrics["red_avg_engagement"] = round(df_red["Engagement"].mean(), 2)
        
        # Top Post
        top_post = df_red.sort_values(by=upvote_col, ascending=False).iloc[0]
        metrics["red_top_content"] = f"{top_post.get('Title', 'Unknown')} ({top_post.get(upvote_col)} upvotes)"
    else:
        metrics["red_avg_engagement"] = 0
        metrics["red_top_content"] = "No Data"

    # --- SENTIMENT METRICS ---
    if not df_sent.empty:
        score_col = "Compound Score" if "Compound Score" in df_sent.columns else "compound"
        label_col = "Sentiment Label" if "Sentiment Label" in df_sent.columns else "Sentiment_Label"
        
        df_sent[score_col] = clean_numeric(df_sent, score_col)
        
        metrics["avg_sentiment"] = round(df_sent[score_col].mean(), 3)
        
        if label_col in df_sent.columns:
            metrics["pos_pct"] = round((df_sent[label_col].str.lower() == "positive").mean() * 100, 1)
            metrics["neg_pct"] = round((df_sent[label_col].str.lower() == "negative").mean() * 100, 1)
            metrics["neu_pct"] = round((df_sent[label_col].str.lower() == "neutral").mean() * 100, 1)
        else:
            metrics["pos_pct"] = 0
            metrics["neg_pct"] = 0
            metrics["neu_pct"] = 0
            
        metrics["total_items"] = len(df_sent)
    else:
        metrics["avg_sentiment"] = 0
        metrics["pos_pct"] = 0
        metrics["neg_pct"] = 0
        metrics["neu_pct"] = 0
        metrics["total_items"] = 0

    return metrics, sheet

def upload_insights(sheet, metrics):
    """Uploads the summary table to the 'Content_Insights' tab."""
    data = [
        ["Metric", "Value"],
        ["YouTube Avg Engagement %", metrics["yt_avg_engagement"]],
        ["Top YouTube Video", metrics["yt_top_content"]],
        ["Reddit Avg Engagement (Score)", metrics["red_avg_engagement"]],
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
            ws = sheet.add_worksheet(title=OUTPUT_TAB, rows="50", cols="5")
        
        ws.update(values=data, range_name="A1")
        st.toast(f"✅ Updated '{OUTPUT_TAB}' tab in Google Sheets!", icon="🚀")
    except Exception as e:
        st.error(f"Upload failed: {e}")

# ----- STREAMLIT UI -----
st.title("📈 Content Performance & Insights")
st.markdown("Aggregated metrics from YouTube, Reddit, and Sentiment Analysis.")

if st.button("🚀 Generate Performance Report", type="primary"):
    with st.spinner("Calculating metrics across all platforms..."):
        metrics, sheet = calculate_metrics()
    
    if metrics:
        # Top Level Metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Avg Sentiment", metrics["avg_sentiment"])
        col2.metric("YouTube Engagement", f"{metrics['yt_avg_engagement']}%")
        col3.metric("Reddit Engagement", metrics["red_avg_engagement"])

        st.divider()

        # Detailed Tables
        st.subheader("🏆 Top Performing Content")
        st.info(f"**YouTube:** {metrics['yt_top_content']}")
        st.success(f"**Reddit:** {metrics['red_top_content']}")

        st.divider()
        st.subheader("📊 Sentiment Breakdown")
        c1, c2, c3 = st.columns(3)
        c1.metric("Positive", f"{metrics['pos_pct']}%")
        c2.metric("Negative", f"{metrics['neg_pct']}%")
        c3.metric("Neutral", f"{metrics['neu_pct']}%")

        # Upload
        if sheet:
            upload_insights(sheet, metrics)
