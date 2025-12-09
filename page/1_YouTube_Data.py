"""
youtube_data.py
Fetch video metadata (as before) AND fetch up to N comments per video.
Writes two tabs:
 - "YouTube Data"       (video-level summary)
 - "YouTube Comments"   (comment-level rows for sentiment)
"""

import os
from collections import Counter
from datetime import datetime, timedelta
import re
import time

import gspread
import pandas as pd
from dotenv import load_dotenv
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv("secrettt.env")

# ----- CONFIG -----
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")  # replace if needed
GOOGLE_SHEET_NAME = "Content Performance Tracker"
VIDEOS_TAB = "YouTube Data"
COMMENTS_TAB = "YouTube Comments"
CREDENTIALS_FILE = "credentials.json"

TOPICS = ["digital marketing", "content marketing", "social media strategy", "Video content strategy"]
PUBLISHED_DAYS = 30
MAX_VIDEOS_PER_TOPIC = 30
MIN_VIEWS = 10000
MAX_COMMENTS_PER_VIDEO = 50  # how many comments to fetch per video (top-level)

# ----- HELPERS -----
def connect_sheets():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds).open(GOOGLE_SHEET_NAME)

def clean_text(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()

# ----- YOUTUBE CLIENT -----
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

def collect_videos_and_comments():
    published_after = (datetime.utcnow() - timedelta(days=PUBLISHED_DAYS)).isoformat("T") + "Z"
    all_videos = []
    all_comments = []

    for topic in TOPICS:
        print(f"Searching videos for topic: {topic}")
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
            print("YouTube search error:", e)
            continue

        for item in search_resp.get("items", []):
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
                        order="relevance"  # relevance tends to pull meaningful comments
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
                        # paginate
                        if "nextPageToken" in c_resp and count < MAX_COMMENTS_PER_VIDEO:
                            time.sleep(0.5)
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

    print("YouTube Data and YouTube Comments updated successfully.")

if __name__ == "__main__":
    videos_df, comments_df = collect_videos_and_comments()
    if not videos_df.empty:
        videos_df = videos_df.sort_values(by="Views", ascending=False)
    upload_to_sheets(videos_df, comments_df)
