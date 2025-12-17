import streamlit as st
import os
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# ----- AUTHENTICATION SETUP -----

# This function is used to get secret values like API keys.
# It first checks Streamlit Cloud secrets.
# If not found, it tries to load the value from a local .env file.
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    try:
        from dotenv import load_dotenv
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

# This function connects the app to Google Sheets.
# It works both when deployed on Streamlit Cloud and when run locally.
def connect_sheets():
    """Connect to Google Sheets (Works on Cloud & Local)"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # First try to read Google credentials from Streamlit secrets
    if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
        try:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            
            # Fix formatting issue in private key if needed
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client.open("Content Performance Tracker")
        except Exception as e:
            st.error(f"Secret Error: {e}")
            st.stop()

    # If secrets are not found, try using local credentials.json file
    local_creds = None
    if os.path.exists("credentials.json"):
        local_creds = "credentials.json"
    elif os.path.exists("../credentials.json"):
        local_creds = "../credentials.json"

    if local_creds:
        creds = ServiceAccountCredentials.from_json_keyfile_name(local_creds, scope)
        client = gspread.authorize(creds)
        return client.open("Content Performance Tracker")
    
    # Stop the app if Google credentials are not found
    else:
        st.error("❌ Critical Error: No Google Credentials found! Check 'credentials.json' locally or 'gcp_credentials' in Secrets.")
        st.stop()

# ----- CONFIG -----

# Fetch YouTube API key securely
YOUTUBE_API_KEY = get_secret("YOUTUBE_API_KEY")

# Google Sheet and worksheet names
GOOGLE_SHEET_NAME = "Content Performance Tracker"
VIDEOS_TAB = "YouTube Data"
COMMENTS_TAB = "YouTube Comments"

# Topics that will be searched on YouTube
TOPICS = ["digital marketing", "content marketing", "social media strategy", "Video content strategy"]

# Filters and limits for data collection
PUBLISHED_DAYS = 30
MAX_VIDEOS_PER_TOPIC = 30
MIN_VIEWS = 10000
MAX_COMMENTS_PER_VIDEO = 50 

# ----- HELPERS -----

# This function cleans text by removing extra spaces.
# It also avoids errors if the input is not a string.
def clean_text(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()

# This function collects YouTube videos and comments.
# Streamlit cache is used so the API is not called repeatedly.
@st.cache_data(show_spinner=False)
def collect_videos_and_comments():
    if not YOUTUBE_API_KEY:
        st.error("❌ YouTube API Key missing!")
        return pd.DataFrame(), pd.DataFrame()

    # Create YouTube API client
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # Only fetch videos published in the last given number of days
    published_after = (datetime.utcnow() - timedelta(days=PUBLISHED_DAYS)).isoformat("T") + "Z"
    all_videos = []
    all_comments = []

    # UI elements to show progress
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Loop through each topic
    for idx, topic in enumerate(TOPICS):
        status_text.write(f"🔎 Searching videos for topic: **{topic}**...")
        try:
            search_resp = youtube.search().list(
                q=topic,
                part="snippet",
                type="video",
                maxResults=MAX_VIDEOS_PER_TOPIC,
                order="viewCount",
                publishedAfter=published_after
            ).execute()
        except Exception as e:
            st.warning(f"YouTube search error for {topic}: {e}")
            continue

        items = search_resp.get("items", [])
        for item in items:
            video_id = item["id"]["videoId"]
            try:
                # Fetch video statistics and details
                v_resp = youtube.videos().list(part="statistics,snippet", id=video_id).execute()
            except Exception as e:
                continue
            
            if not v_resp.get("items"): 
                continue
            
            video = v_resp["items"][0]
            stats = video.get("statistics", {})
            snippet = video.get("snippet", {})
            
            # Filter videos based on minimum views
            views = int(stats.get("viewCount", 0))
            if views < MIN_VIEWS: 
                continue

            likes = int(stats.get("likeCount", 0)) if stats.get("likeCount") else 0
            comments_count = int(stats.get("commentCount", 0)) if stats.get("commentCount") else 0
            
            # Extract keywords from video description
            desc = snippet.get("description", "")
            tags = snippet.get("tags", [])
            words = re.findall(r'\b[a-zA-Z]{4,}\b', desc.lower())
            common_keywords = [w for w, _ in Counter(words).most_common(5)]

            # Store video details
            all_videos.append({
                "Topic": topic,
                "Video ID": video_id,
                "Video Title": clean_text(snippet.get("title", "")),
                "Channel": snippet.get("channelTitle", ""),
                "Published Date": snippet.get("publishedAt", ""),
                "Views": views,
                "Likes": likes,
                "Comments": comments_count,
                "Engagement Rate (%)": round(((likes + comments_count) / views) * 100, 2) if views else 0,
                "Tags": ", ".join(tags) if tags else "N/A",
                "Top Keywords": ", ".join(common_keywords),
                "Description": desc[:300] + "..."
            })

            # Fetch top comments if comments exist
            if comments_count > 0:
                try:
                    c_request = youtube.commentThreads().list(
                        part="snippet", videoId=video_id, maxResults=min(MAX_COMMENTS_PER_VIDEO, 100),
                        textFormat="plainText", order="relevance"
                    )
                    c_resp = c_request.execute()
                    count = 0
                    while c_resp and "items" in c_resp and count < MAX_COMMENTS_PER_VIDEO:
                        for citem in c_resp["items"]:
                            top = citem["snippet"]["topLevelComment"]["snippet"]
                            all_comments.append({
                                "Video ID": video_id,
                                "Video Title": clean_text(snippet.get("title", "")),
                                "Comment ID": citem["snippet"]["topLevelComment"]["id"],
                                "Comment Text": clean_text(top.get("textDisplay", "")),
                                "Author": top.get("authorDisplayName", ""),
                                "Like Count": top.get("likeCount", 0),
                                "Published At": top.get("publishedAt", ""),
                            })
                            count += 1
                            if count >= MAX_COMMENTS_PER_VIDEO: 
                                break
                        if "nextPageToken" in c_resp and count < MAX_COMMENTS_PER_VIDEO:
                            time.sleep(0.1)
                            c_resp = youtube.commentThreads().list(
                                part="snippet", videoId=video_id, maxResults=min(MAX_COMMENTS_PER_VIDEO - count, 100),
                                pageToken=c_resp.get("nextPageToken"), textFormat="plainText", order="relevance"
                            ).execute()
                        else: 
                            break
                except Exception: 
                    pass
        
        # Update progress bar
        progress_bar.progress((idx + 1) / len(TOPICS))

    status_text.success("✅ Data Collection Complete!")
    time.sleep(1)
    status_text.empty()
    return pd.DataFrame(all_videos), pd.DataFrame(all_comments)

# This function uploads video and comment data to Google Sheets
def upload_to_sheets(videos_df, comments_df):
    sheet = connect_sheets()
    try:
        wv = sheet.worksheet(VIDEOS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        wv = sheet.add_worksheet(title=VIDEOS_TAB, rows="2000", cols="20")
    
    if not videos_df.empty:
        wv.clear()
        wv.update(values=[videos_df.columns.tolist()] + videos_df.values.tolist(), range_name="A1")

    try:
        wc = sheet.worksheet(COMMENTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        wc = sheet.add_worksheet(title=COMMENTS_TAB, rows="5000", cols="30")
    
    if not comments_df.empty:
        wc.clear()
        wc.update(values=[comments_df.columns.tolist()] + comments_df.values.tolist(), range_name="A1")

    st.toast("Updated Google Sheets successfully!", icon="🚀")

# ----- STREAMLIT UI -----

# App title and description
st.title("📥 YouTube Data Collection")
st.markdown("Fetch the latest trending videos and comments for your marketing topics.")

# Create two columns in the UI
col1, col2 = st.columns(2)
with col1:
    st.info(f"**Topics:** {', '.join(TOPICS)}")
with col2:
    # Button to start scraping process
    if st.button("🚀 Start Scraping YouTube", type="primary"):
        with st.spinner("Connecting to YouTube API..."):
            videos_df, comments_df = collect_videos_and_comments()
            if not videos_df.empty:
                videos_df = videos_df.sort_values(by="Views", ascending=False)
                st.write("### 📹 Video Metrics")
                st.dataframe(videos_df.head(10))
                st.write("### 💬 Comment Samples")
                st.dataframe(comments_df.head(10))
                upload_to_sheets(videos_df, comments_df)
            else:
                st.warning("No videos found. Check API quota or topics.")
