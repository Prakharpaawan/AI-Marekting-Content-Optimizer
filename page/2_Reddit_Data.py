import os

import praw
import pandas as pd
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone

load_dotenv("secrettt.env")

# ===========================
# CONFIGURATION
# ===========================
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")

GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"

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

POST_LIMIT = 100
MIN_UPVOTES = 15
MIN_COMMENTS = 3


# ===========================
# FETCH REDDIT POSTS
# ===========================
def fetch_reddit_posts():
    print("Connecting to Reddit API...")

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    all_posts = []

    for sub in SUBREDDITS:
        print(f"Fetching posts from r/{sub}...")
        subreddit = reddit.subreddit(sub)

        for post in subreddit.hot(limit=POST_LIMIT):

            if post.score < MIN_UPVOTES or post.num_comments < MIN_COMMENTS:
                continue

            all_posts.append({
                "Subreddit": sub,
                "Title": post.title,
                "Upvotes": post.score,
                "Comments": post.num_comments,
                "URL": f"https://www.reddit.com{post.permalink}",
                "Created Date": datetime.fromtimestamp(post.created_utc, timezone.utc).strftime("%Y-%m-%d"),
                "Post Text": post.selftext[:500] + "..." if post.selftext else "N/A (Link Post)",
                "Post ID": post.id
            })

    print(f"Collected {len(all_posts)} posts.\n")
    return pd.DataFrame(all_posts)


# ===========================
# FETCH COMMENTS FOR EACH POST
# ===========================
def fetch_comments_for_posts(df_posts):
    print("Fetching comments for posts...")

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    all_comments = []

    for _, row in df_posts.iterrows():
        post_id = row["Post ID"]
        post_url = row["URL"]

        try:
            submission = reddit.submission(url=post_url)
            submission.comments.replace_more(limit=0)

            for comment in submission.comments:
                all_comments.append({
                    "Post ID": post_id,
                    "Comment Text": comment.body[:300],
                    "Score": comment.score,
                    "Comment URL": post_url
                })

        except Exception as e:
            print(f"Error fetching comments for {post_url}: {e}")

    print(f"Collected {len(all_comments)} comments.\n")
    return pd.DataFrame(all_comments)


# ===========================
# UPLOAD TO GOOGLE SHEETS
# ===========================
def upload_to_google_sheets(posts_df, comments_df):
    print("Uploading Reddit posts + comments to Google Sheets...")

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    sheet = client.open(GOOGLE_SHEET_NAME)

    # ---------- Posts Tab ----------
    try:
        ws_posts = sheet.worksheet(POSTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_posts = sheet.add_worksheet(title=POSTS_TAB, rows="2000", cols="20")

    ws_posts.clear()
    ws_posts.update("A1", [posts_df.columns.tolist()] + posts_df.values.tolist())

    # ---------- Comments Tab ----------
    try:
        ws_comments = sheet.worksheet(COMMENTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws_comments = sheet.add_worksheet(title=COMMENTS_TAB, rows="3000", cols="20")

    ws_comments.clear()
    ws_comments.update("A1", [comments_df.columns.tolist()] + comments_df.values.tolist())

    print("Upload complete!")


# ===========================
# MAIN
# ===========================
if __name__ == "__main__":

    posts_df = fetch_reddit_posts()

    if posts_df.empty:
        print("No Reddit posts found. Exiting.")
        exit()

    comments_df = fetch_comments_for_posts(posts_df)

    upload_to_google_sheets(posts_df, comments_df)

    print("\nReddit data collection completed successfully!")
