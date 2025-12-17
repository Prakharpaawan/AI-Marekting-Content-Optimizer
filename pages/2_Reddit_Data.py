import streamlit as st
import os
import json
import praw
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone

# ----- AUTHENTICATION SETUP -----

# This function is used to get secret values like API keys.
# It first checks Streamlit Cloud secrets.
# If not found, it tries to load values from a local .env file.
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
# It works both on Streamlit Cloud and on a local system.
def connect_sheets():
    """Connect to Google Sheets (Works on Cloud & Local)"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # First try to use Google credentials stored in Streamlit secrets
    if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
        try:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            
            # Fix private key formatting issue
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client.open("Content Performance Tracker")
        except Exception as e:
            st.error(f"Secret Error: {e}")
            st.stop()

    # If cloud secrets are not available, try local credentials.json file
    local_creds = None
    if os.path.exists("credentials.json"):
        local_creds = "credentials.json"
    elif os.path.exists("../credentials.json"):
        local_creds = "../credentials.json"

    if local_creds:
        creds = ServiceAccountCredentials.from_json_keyfile_name(local_creds, scope)
        client = gspread.authorize(creds)
        return client.open("Content Performance Tracker")
    
    # Stop the app if no Google credentials are found
    else:
        st.error("❌ Critical Error: No Google Credentials found! Check 'credentials.json' locally or 'gcp_credentials' in Secrets.")
        st.stop()

# ----- CONFIG -----

# Fetch Reddit API credentials securely
REDDIT_CLIENT_ID = get_secret("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = get_secret("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = get_secret("REDDIT_USER_AGENT")

# Google Sheet and worksheet names
GOOGLE_SHEET_NAME = "Content Performance Tracker"
POSTS_TAB = "Reddit Posts"
COMMENTS_TAB = "Reddit Comments"

# List of subreddits to monitor
SUBREDDITS = [
    "marketing",
    "content_marketing",
    "socialmedia",
    "DigitalMarketing",
    "SEO",
    "EmailMarketing",
    "PPC"
]

# Limits to control performance and filter quality posts
POST_LIMIT = 50 
MIN_UPVOTES = 15
MIN_COMMENTS = 3

# ----- APP LOGIC -----

# This function fetches posts and comments from Reddit.
# Streamlit cache is used to avoid repeated API calls.
@st.cache_data(show_spinner=False)
def fetch_reddit_data():
    if not REDDIT_CLIENT_ID:
        st.error("❌ Reddit Keys Missing! Check your .env or Streamlit Secrets.")
        return pd.DataFrame(), pd.DataFrame()

    # Create Reddit API client using PRAW
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    all_posts = []
    all_comments = []
    
    # UI elements for showing progress
    status_text = st.empty()
    progress_bar = st.progress(0)

    total_steps = len(SUBREDDITS)

    # Loop through each subreddit
    for idx, sub in enumerate(SUBREDDITS):
        status_text.write(f"🔎 Scraping r/{sub}...")
        
        try:
            subreddit = reddit.subreddit(sub)

            # Fetch hot posts from the subreddit
            for post in subreddit.hot(limit=POST_LIMIT):

                # Filter out posts with low engagement
                if post.score < MIN_UPVOTES or post.num_comments < MIN_COMMENTS:
                    continue

                # Store main post details
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

                # Fetch only top-level comments to save time
                try:
                    post.comments.replace_more(limit=0)
                    for comment in post.comments[:5]:  # Top 5 comments per post
                        all_comments.append({
                            "Post ID": post.id,
                            "Comment Text": comment.body[:300],
                            "Score": comment.score,
                            "Comment URL": f"https://www.reddit.com{post.permalink}"
                        })
                except Exception:
                    pass 

        except Exception as e:
            st.warning(f"Error accessing r/{sub}: {e}")
        
        # Update progress bar after each subreddit
        progress_bar.progress((idx + 1) / total_steps)

    status_text.success("✅ Reddit Scraping Complete!")
    return pd.DataFrame(all_posts), pd.DataFrame(all_comments)

# This function uploads Reddit posts and comments to Google Sheets
def upload_to_sheets(posts_df, comments_df):
    sheet = connect_sheets()

    # Handle Reddit posts worksheet
    try:
        ws_posts = sheet.worksheet(POSTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_posts = sheet.add_worksheet(title=POSTS_TAB, rows="2000", cols="20")

    if not posts_df.empty:
        ws_posts.clear()
        ws_posts.update("A1", [posts_df.columns.tolist()] + posts_df.astype(str).values.tolist())

    # Handle Reddit comments worksheet
    try:
        ws_comments = sheet.worksheet(COMMENTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_comments = sheet.add_worksheet(title=COMMENTS_TAB, rows="3000", cols="20")

    if not comments_df.empty:
        ws_comments.clear()
        ws_comments.update("A1", [comments_df.columns.tolist()] + comments_df.astype(str).values.tolist())

    st.toast("Uploaded to Google Sheets successfully!", icon="🚀")

# ----- STREAMLIT UI -----

# App title and description
st.title("💬 Reddit Trend Monitor")
st.markdown("Monitor discussions across top marketing subreddits to identify audience pain points.")

# Create two columns in the UI
col1, col2 = st.columns(2)
with col1:
    st.info(f"**Subreddits:** {', '.join(SUBREDDITS)}")
with col2:
    # Button to start Reddit scraping
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
