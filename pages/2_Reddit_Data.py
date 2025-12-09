import streamlit as st
import os
import praw
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone

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
REDDIT_CLIENT_ID = get_secret("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = get_secret("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = get_secret("REDDIT_USER_AGENT")

GOOGLE_SHEET_NAME = "Content Performance Tracker"
POSTS_TAB = "Reddit Posts"
COMMENTS_TAB = "Reddit Comments"

SUBREDDITS = [
    "marketing",
    "content_marketing",
    "socialmedia",
    "DigitalMarketing",
    "SEO",
    "EmailMarketing",
    "PPC"
]

# Reduced slightly for web performance, you can increase if needed
POST_LIMIT = 50 
MIN_UPVOTES = 15
MIN_COMMENTS = 3

# ----- APP LOGIC -----
def fetch_reddit_data():
    if not REDDIT_CLIENT_ID:
        st.error("❌ Reddit Keys Missing! Check your .env or Streamlit Secrets.")
        return pd.DataFrame(), pd.DataFrame()

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    all_posts = []
    all_comments = []
    
    # UI Progress components
    status_text = st.empty()
    progress_bar = st.progress(0)

    total_steps = len(SUBREDDITS)

    for idx, sub in enumerate(SUBREDDITS):
        status_text.write(f"🔎 Scraping r/{sub}...")
        
        try:
            subreddit = reddit.subreddit(sub)
            # Fetch Posts
            for post in subreddit.hot(limit=POST_LIMIT):
                if post.score < MIN_UPVOTES or post.num_comments < MIN_COMMENTS:
                    continue

                post_data = {
                    "Subreddit": sub,
                    "Title": post.title,
                    "Upvotes": post.score,
                    "Comments": post.num_comments,
                    "URL": f"https://www.reddit.com{post.permalink}",
                    "Created Date": datetime.fromtimestamp(post.created_utc, timezone.utc).strftime("%Y-%m-%d"),
                    "Post Text": post.selftext[:500] + "..." if post.selftext else "N/A (Link Post)",
                    "Post ID": post.id
                }
                all_posts.append(post_data)

                # Fetch Comments (Only top level to save time)
                try:
                    post.comments.replace_more(limit=0)
                    for comment in post.comments[:5]: # Grab top 5 comments per post
                        all_comments.append({
                            "Post ID": post.id,
                            "Comment Text": comment.body[:300],
                            "Score": comment.score,
                            "Comment URL": f"https://www.reddit.com{post.permalink}"
                        })
                except Exception as e:
                    pass # Skip comment errors

        except Exception as e:
            st.warning(f"Error accessing r/{sub}: {e}")
        
        # Update progress
        progress_bar.progress((idx + 1) / total_steps)

    status_text.success("✅ Reddit Scraping Complete!")
    return pd.DataFrame(all_posts), pd.DataFrame(all_comments)

def upload_to_sheets(posts_df, comments_df):
    sheet = connect_sheets()

    # ---------- Posts Tab ----------
    try:
        ws_posts = sheet.worksheet(POSTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_posts = sheet.add_worksheet(title=POSTS_TAB, rows="2000", cols="20")

    if not posts_df.empty:
        ws_posts.clear()
        ws_posts.update("A1", [posts_df.columns.tolist()] + posts_df.astype(str).values.tolist())

    # ---------- Comments Tab ----------
    try:
        ws_comments = sheet.worksheet(COMMENTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_comments = sheet.add_worksheet(title=COMMENTS_TAB, rows="3000", cols="20")

    if not comments_df.empty:
        ws_comments.clear()
        ws_comments.update("A1", [comments_df.columns.tolist()] + comments_df.astype(str).values.tolist())

    st.toast("Uploaded to Google Sheets successfully!", icon="🚀")

# ----- STREAMLIT UI -----
st.title("💬 Reddit Trend Monitor")
st.markdown("Monitor discussions across top marketing subreddits to identify audience pain points.")

col1, col2 = st.columns(2)
with col1:
    st.info(f"**Subreddits:** {', '.join(SUBREDDITS)}")
with col2:
    if st.button("🚀 Start Scraping Reddit", type="primary"):
        with st.spinner("Connecting to Reddit API..."):
            posts_df, comments_df = fetch_reddit_data()
            
            if not posts_df.empty:
                st.write(f"### 📝 Found {len(posts_df)} Posts")
                st.dataframe(posts_df.head(10))
                
                st.write(f"### 🗣️ Found {len(comments_df)} Comments")
                st.dataframe(comments_df.head(10))
                
                upload_to_sheets(posts_df, comments_df)
            else:
                st.warning("No posts found matching criteria.")
