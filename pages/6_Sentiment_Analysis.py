import streamlit as st
import os
import json
import re
import math
import pandas as pd
import gspread
import requests
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# ----- NLTK SETUP -----
try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    nltk.download('vader_lexicon')

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
SLACK_WEBHOOK = get_secret("SLACK_WEBHOOK_URL")

# Input tabs
YOUTUBE_TAB = "YouTube Data"
REDDIT_TAB = "Reddit Posts" # Updated to match your actual tab name
REDDIT_COMMENTS_TAB = "Reddit Comments"
ARTICLES_TAB = "Articles"

# Output tabs
ALL_SOURCES_TAB = "All_Content_Sources"
SENTIMENT_RESULTS_TAB = "Sentiment_Results_All"
DASHBOARD_TAB = "Performance_Dashboard"

POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# ----- HELPERS -----
def send_slack(text):
    if not SLACK_WEBHOOK: return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
    except Exception:
        pass

def normalize_whitespace(s):
    if not isinstance(s, str): return ""
    return re.sub(r"\s+", " ", s).strip()

def safe_get_worksheet(sheet, name):
    try:
        return pd.DataFrame(sheet.worksheet(name).get_all_records())
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()

# ----- DATA PROCESSING -----
def build_combined_df(sheet):
    pieces = []
    
    # YouTube Data
    yt = safe_get_worksheet(sheet, YOUTUBE_TAB)
    if not yt.empty:
        for _, r in yt.iterrows():
            text = f"{r.get('Video Title', '')}. {r.get('Description', '')[:300]}"
            pieces.append({
                "Source": "YouTube", "Content Type": "video",
                "Text": normalize_whitespace(text),
                "URL": f"https://www.youtube.com/watch?v={r.get('Video ID', '')}",
                "Topic": r.get("Topic", ""),
                "Date": r.get("Published Date", "")
            })

    # Reddit Posts
    rd = safe_get_worksheet(sheet, REDDIT_TAB)
    if not rd.empty:
        for _, r in rd.iterrows():
            text = f"{r.get('Title', '')}. {r.get('Post Text', '')[:400]}"
            pieces.append({
                "Source": "Reddit", "Content Type": "post",
                "Text": normalize_whitespace(text),
                "URL": r.get("URL", ""),
                "Topic": r.get("Subreddit", ""),
                "Date": r.get("Created Date", "")
            })

    # News Articles
    art = safe_get_worksheet(sheet, ARTICLES_TAB)
    if not art.empty:
        for _, r in art.iterrows():
            text = f"{r.get('Title', '')}. {r.get('Snippet', '')[:300]}"
            pieces.append({
                "Source": "News", "Content Type": "article",
                "Text": normalize_whitespace(text),
                "URL": r.get("Link", ""),
                "Topic": r.get("Topic", ""),
                "Date": r.get("Collected At", "")
            })

    return pd.DataFrame(pieces)

def analyze_sentiment(df):
    sid = SentimentIntensityAnalyzer()
    
    def get_score(text):
        if not text or not isinstance(text, str): return 0.0
        return sid.polarity_scores(text)['compound']

    df['Compound Score'] = df['Text'].apply(get_score)
    
    def get_label(score):
        if score >= POSITIVE_THRESHOLD: return "Positive"
        if score <= NEGATIVE_THRESHOLD: return "Negative"
        return "Neutral"
        
    df['Sentiment Label'] = df['Compound Score'].apply(get_label)
    return df

def upload_results(sheet, df, tab_name):
    try:
        try:
            ws = sheet.worksheet(tab_name)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=tab_name, rows="2000", cols="20")
        
        ws.update(values=[df.columns.tolist()] + df.astype(str).values.tolist(), range_name="A1")
    except Exception as e:
        st.error(f"Failed to upload {tab_name}: {e}")

# ----- STREAMLIT UI -----
st.title("📊 Sentiment Analysis Dashboard")
st.markdown("Analyze sentiment trends across YouTube, Reddit, and News.")

if st.button("🚀 Run Analysis", type="primary"):
    with st.spinner("Connecting to Google Sheets..."):
        sheet = connect_sheets()
        
    with st.spinner("Aggregating data from all sources..."):
        combined_df = build_combined_df(sheet)
        
    if combined_df.empty:
        st.warning("No data found in source tabs (YouTube, Reddit, Articles). Run those modules first.")
    else:
        st.write(f"### 📥 Analyzed {len(combined_df)} content items")
        
        with st.spinner("Running VADER Sentiment Analysis..."):
            results_df = analyze_sentiment(combined_df)
            
        # Display Summary Metrics
        col1, col2, col3 = st.columns(3)
        avg_score = results_df['Compound Score'].mean()
        pos_pct = (results_df['Sentiment Label'] == 'Positive').mean() * 100
        neg_pct = (results_df['Sentiment Label'] == 'Negative').mean() * 100
        
        col1.metric("Avg Sentiment Score", f"{avg_score:.2f}")
        col2.metric("Positive Content", f"{pos_pct:.1f}%")
        col3.metric("Negative Content", f"{neg_pct:.1f}%")
        
        # Display Data Table with Full Columns
        st.write("### Detailed Sentiment Report")
        st.dataframe(
            results_df[['Source', 'Content Type', 'Sentiment Label', 'Compound Score', 'Text']],
            column_config={
                "Text": st.column_config.TextColumn("Content Snippet", width="large"),
                "Compound Score": st.column_config.NumberColumn("Score", format="%.2f"),
            },
            hide_index=True
        )
        
        # Upload Results
        with st.spinner("Uploading results to Google Sheets..."):
            upload_results(sheet, results_df, SENTIMENT_RESULTS_TAB)
            send_slack(f"📊 Sentiment Analysis complete for {len(results_df)} items.")
            
        st.success("✅ Analysis Complete & Uploaded!")
