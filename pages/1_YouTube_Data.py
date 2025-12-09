import streamlit as st
import os
from collections import Counter
from datetime import datetime, timedelta
import re
import time
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# ----- AUTHENTICATION & SECRETS SETUP (Universal Fix) -----
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    # 1. Try Streamlit Secrets (Cloud)
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    
    # 2. Try Local .env (Laptop)
    try:
        from dotenv import load_dotenv
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # A. Try Cloud Secrets (Streamlit)
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    
    # B. Try Local File (Laptop)
    elif os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    
    else:
        st.error("❌ Critical Error: No Google Credentials found! Check Streamlit Secrets or credentials.json.")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----
# Get Key safely using the helper function
YOUTUBE_API_KEY = get_secret("YOUTUBE_API_KEY")

GOOGLE_SHEET_NAME = "Content Performance Tracker"
VIDEOS_TAB = "YouTube Data"
COMMENTS_TAB = "YouTube Comments"

TOPICS = ["digital marketing", "content marketing", "social media strategy", "Video content strategy"]
PUBLISHED_DAYS = 30
MAX_VIDEOS_PER_TOPIC = 30
MIN_VIEWS = 10000
MAX_COMMENTS_PER_VIDEO = 50 

# ----- HELPERS -----
def clean_text(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()

def collect_videos_and_comments():
    if not YOUTUBE_API_KEY:
        st.error("❌ YouTube API Key missing!")
        return pd.DataFrame(), pd.DataFrame()

    # Initialize YouTube Client inside the function to avoid global errors
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    published_after = (datetime.utcnow() - timedelta(days=PUBLISHED_DAYS)).isoformat("T") + "Z"
    all_videos = []
    all_comments = []

    progress_bar = st.progress(0)
    status_text = st.empty()

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
            
            # fetch full video snippet + stats
            try:
                v_resp = youtube.videos().list(part="statistics,snippet", id=video_id).execute()
            except Exception as e:
                print("Video fetch error:", e)
                continue
            
            if not v_resp.get("items"):
                continue
            
            video = v_resp["items"][0]
            stats = video.get("statistics", {})
            snippet = video.get("snippet", {})

            views = int(stats.get("viewCount", 0))
            if views < MIN_VIEWS:
                continue

            likes = int(stats.get("likeCount", 0)) if stats.get("likeCount") else 0
            comments_count = int(stats.get("commentCount", 0)) if stats.get("commentCount") else 0
            desc = snippet.get("description", "")
            tags = snippet.get("tags", [])

            # keyword summary from description
            words = re.findall(r'\b[a-zA-Z]{4,}\b', desc.lower())
            common_keywords = [w for w, _ in Counter(words).most_common(5)]
            keyword_summary = ", ".join(common_keywords)

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
                "Top Keywords": keyword_summary,
                "Description": desc[:300] + ("..." if len(desc) > 300 else "")
            })

            # fetch comments for this video (top-level)
            if comments_count > 0:
                try:
                    c_request = youtube.commentThreads().list(
                        part="snippet",
                        videoId=video_id,
                        maxResults=min(MAX_COMMENTS_PER_VIDEO, 100),
                        textFormat="plainText",
                        order="relevance"
                    )
                    c_resp = c_request.execute()
                    count = 0
                    while c_resp and "items" in c_resp and count < MAX_COMMENTS_PER_VIDEO:
                        for citem in c_resp["items"]:
                            top = citem["snippet"]["topLevelComment"]["snippet"]
                            comment_text = clean_text(top.get("textDisplay", ""))
                            all_comments.append({
                                "Video ID": video_id,
                                "Video Title": clean_text(snippet.get("title", "")),
                                "Comment ID": citem["snippet"]["topLevelComment"]["id"],
                                "Comment Text": comment_text,
                                "Author": top.get("authorDisplayName", ""),
                                "Like Count": top.get("likeCount", 0),
                                "Published At": top.get("publishedAt", ""),
                            })
                            count += 1
                            if count >= MAX_COMMENTS_PER_VIDEO:
                                break
                        
                        if "nextPageToken" in c_resp and count < MAX_COMMENTS_PER_VIDEO:
                            time.sleep(0.2) # slightly faster sleep for UI
                            c_resp = youtube.commentThreads().list(
                                part="snippet",
                                videoId=video_id,
                                maxResults=min(MAX_COMMENTS_PER_VIDEO - count, 100),
                                pageToken=c_resp.get("nextPageToken"),
                                textFormat="plainText",
                                order="relevance"
                            ).execute()
                        else:
                            break
                except Exception as e:
                    print(f"Could not fetch comments for {video_id}: {e}")
        
        # Update progress bar
        progress_bar.progress((idx + 1) / len(TOPICS))

    status_text.success("✅ Data Collection Complete!")
    return pd.DataFrame(all_videos), pd.DataFrame(all_comments)

def upload_to_sheets(videos_df, comments_df):
    sheet = connect_sheets()
    
    # Videos
    try:
        wv = sheet.worksheet(VIDEOS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        wv = sheet.add_worksheet(title=VIDEOS_TAB, rows="2000", cols="20")
    
    v_data = [videos_df.columns.tolist()] + videos_df.values.tolist() if not videos_df.empty else []
    if v_data:
        wv.clear()
        wv.update(values=v_data, range_name="A1")

    # Comments
    try:
        wc = sheet.worksheet(COMMENTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        wc = sheet.add_worksheet(title=COMMENTS_TAB, rows="5000", cols="30")
    
    c_data = [comments_df.columns.tolist()] + comments_df.values.tolist() if not comments_df.empty else []
    if c_data:
        wc.clear()
        wc.update(values=c_data, range_name="A1")

    st.toast("Updated Google Sheets successfully!", icon="🚀")

# ----- STREAMLIT UI -----
st.title("📥 YouTube Data Collection")
st.markdown("Fetch the latest trending videos and comments for your marketing topics.")

col1, col2 = st.columns(2)
with col1:
    st.info(f"**Topics:** {', '.join(TOPICS)}")
with col2:
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
