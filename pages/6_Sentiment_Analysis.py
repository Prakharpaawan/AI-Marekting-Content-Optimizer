# unified_sentiment_metrics.py
"""
Unified Sentiment & Metrics (Option B — Balanced text)
Reads platform tabs, combines content, runs sentiment, writes results and dashboard,
and posts summarized alerts to Slack.

Usage:
    python unified_sentiment_metrics.py

Notes:
- Make sure credentials.json is present (service account for Google Sheets).
- Update SLACK_WEBHOOK if you want alerts to a different webhook.
"""

import os
import math
import re
from datetime import datetime
import pandas as pd
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import requests

load_dotenv("secrettt.env")

# ensure vader lexicon exists
nltk.download("vader_lexicon", quiet=True)

# ------------- CONFIG -------------
GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"

# Input tabs (expected to exist in your sheet)
YOUTUBE_TAB = "YouTube Data"
YOUTUBE_COMMENTS_TAB = "YouTube Comments"       # if you have this (optional)
REDDIT_TAB = "Reddit Data"
REDDIT_COMMENTS_TAB = "Reddit Comments"         # if you have this (optional)
ARTICLES_TAB = "Articles"

# Output tabs that this script will create/overwrite
ALL_SOURCES_TAB = "All_Content_Sources"
SENTIMENT_RESULTS_TAB = "Sentiment_Results_All"
DASHBOARD_TAB = "Performance_Dashboard"

# Slack webhook (replace if you want another)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

# Thresholds for labeling and alerts
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05
NEGATIVE_SHARE_ALERT = 0.30  # send Slack alert if negative % > 30%

# ------------- HELPERS -------------
def send_slack(text):
    """Post a simple message to Slack webhook (best-effort)."""
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
    except Exception:
        pass


def connect_to_sheets():
    """Authenticate with Google Sheets and return a Worksheet client (gspread.Spreadsheet)."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(GOOGLE_SHEET_NAME)


def safe_get_sheet(spreadsheet, name):
    """Return worksheet object or None if not found."""
    try:
        return spreadsheet.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return None


def first_n(text, n):
    if not isinstance(text, str):
        return ""
    return text.strip()[:n]


def normalize_whitespace(s):
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s).strip()


# ------------- READERS -------------
def read_tab_df(spreadsheet, tab_name):
    """Read sheet tab into a DataFrame or return empty DataFrame if missing."""
    ws = safe_get_sheet(spreadsheet, tab_name)
    if ws is None:
        return pd.DataFrame()
    rows = ws.get_all_records()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_all_sources_df(ss):
    """
    Build combined DataFrame (Option B balanced):
      - youtube: Title + first 300 chars of Description
      - reddit posts: Title + first 400 chars of Post Text
      - reddit comments: full comment text
      - articles: Title + first 300 chars of Link/summary (if exists)
    The result has columns:
      Source, Content Type, Text, URL, Topic, Date, Raw (original dict)
    """
    pieces = []

    # YouTube data (Title + description snippet)
    yt = read_tab_df(ss, YOUTUBE_TAB)
    if not yt.empty:
        for _, r in yt.iterrows():
            title = r.get("Video Title") or r.get("Title") or ""
            desc = r.get("Description") or ""
            text = normalize_whitespace(f"{title}. {first_n(desc,300)}")
            pieces.append({
                "Source": "YouTube",
                "Content Type": "video",
                "Text": text,
                "URL": r.get("URL") or r.get("Video URL") or "",
                "Topic": r.get("Topic", ""),
                "Date": r.get("Published Date") or r.get("Published At") or "",
                "Raw": r
            })

    # YouTube comments (if present) — treat as comment content
    ytc = read_tab_df(ss, YOUTUBE_COMMENTS_TAB)
    if not ytc.empty:
        for _, r in ytc.iterrows():
            comment = r.get("Comment") or r.get("Text") or r.get("Comment Text") or ""
            text = normalize_whitespace(comment)
            pieces.append({
                "Source": "YouTube",
                "Content Type": "comment",
                "Text": text,
                "URL": r.get("URL") or "",
                "Topic": r.get("Topic", ""),
                "Date": r.get("Published Date") or r.get("Date") or "",
                "Raw": r
            })

    # Reddit posts
    rd = read_tab_df(ss, REDDIT_TAB)
    if not rd.empty:
        for _, r in rd.iterrows():
            title = r.get("Title") or ""
            post_text = r.get("Post Text") or r.get("Selftext") or ""
            text = normalize_whitespace(f"{title}. {first_n(post_text,400)}")
            pieces.append({
                "Source": "Reddit",
                "Content Type": "post",
                "Text": text,
                "URL": r.get("URL") or "",
                "Topic": r.get("Subreddit", ""),
                "Date": r.get("Created Date") or r.get("Date") or "",
                "Raw": r
            })

    # Reddit comments (if present)
    rdc = read_tab_df(ss, REDDIT_COMMENTS_TAB)
    if not rdc.empty:
        for _, r in rdc.iterrows():
            comment = r.get("Comment") or r.get("Body") or r.get("Text") or ""
            pieces.append({
                "Source": "Reddit",
                "Content Type": "comment",
                "Text": normalize_whitespace(comment),
                "URL": r.get("URL") or "",
                "Topic": r.get("Subreddit", ""),
                "Date": r.get("Created Date") or r.get("Date") or "",
                "Raw": r
            })

    # Articles (title + snippet)
    art = read_tab_df(ss, ARTICLES_TAB)
    if not art.empty:
        for _, r in art.iterrows():
            title = r.get("Title") or r.get("Headline") or ""
            snippet = r.get("Summary", "") or r.get("Link Summary", "") or r.get("Link", "")
            # first 300 chars of snippet
            pieces.append({
                "Source": "News",
                "Content Type": "article",
                "Text": normalize_whitespace(f"{title}. {first_n(snippet,300)}"),
                "URL": r.get("Link") or r.get("URL") or "",
                "Topic": r.get("Topic", ""),
                "Date": r.get("Date") or "",
                "Raw": r
            })

    if not pieces:
        return pd.DataFrame()

    df = pd.DataFrame(pieces)
    # ensure Text is str
    df["Text"] = df["Text"].fillna("").astype(str)
    return df


# ------------- SENTIMENT -------------
def run_sentiment(df):
    """Run VADER sentiment and return DataFrame with scores and label."""
    sid = SentimentIntensityAnalyzer()
    scores = df["Text"].apply(lambda t: sid.polarity_scores(t) if isinstance(t, str) and t.strip() else {"neg":0.0,"neu":1.0,"pos":0.0,"compound":0.0})
    scores_df = pd.DataFrame(list(scores))
    out = pd.concat([df.reset_index(drop=True), scores_df.reset_index(drop=True)], axis=1)

    def label_row(c):
        if c >= POSITIVE_THRESHOLD:
            return "positive"
        if c <= NEGATIVE_THRESHOLD:
            return "negative"
        return "neutral"

    out["Sentiment_Label"] = out["compound"].apply(label_row)
    return out


# ------------- AGGREGATIONS & DASHBOARD -------------
def build_dashboard(sent_df):
    """
    Build aggregated metrics per Content Type (video, post, comment, article).
    Returns a DataFrame with summary rows.
    """
    if sent_df.empty:
        return pd.DataFrame()

    group_cols = ["Content Type"]
    agg = sent_df.groupby(group_cols).agg(
        Posts=("Text", "count"),
        Avg_Compound=("compound", "mean"),
        Avg_Positive=("pos", "mean"),
        Avg_Negative=("neg", "mean"),
    ).reset_index()

    # compute percent positive/negative counts
    pct = sent_df.groupby("Content Type")["Sentiment_Label"].value_counts(normalize=True).unstack(fill_value=0)
    pct = pct.rename(columns=lambda c: f"PCT_{c.upper()}" )

    agg = agg.merge(pct, on="Content Type", how="left")
    # round numbers nicely
    agg[["Avg_Compound", "Avg_Positive", "Avg_Negative"]] = agg[["Avg_Compound", "Avg_Positive", "Avg_Negative"]].round(3)
    # convert proportions to percentages for PCT_ columns if present
    for col in agg.columns:
        if col.startswith("PCT_"):
            agg[col] = (agg[col] * 100).round(1)

    return agg


# ------------- UPLOAD OUTPUTS -------------
def upload_df_to_sheet(spreadsheet, df, tab_name):
    """Create or overwrite a sheet tab with the given dataframe."""
    if df is None:
        return
    try:
        try:
            ws = spreadsheet.worksheet(tab_name)
            # clear existing
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols="20")
        # prepare values: list of lists
        values = [df.columns.values.tolist()] + df.fillna("").values.tolist()
        # gspread update order: (values, range_name)
        ws.update(values, "A1", value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"Failed to upload tab {tab_name}: {e}")


# ------------- MAIN WORKFLOW -------------
def main():
    send_slack(":rocket: Starting Unified Sentiment & Metrics (Option B - balanced)")
    print("Starting Unified Sentiment & Metrics (Option B - balanced)")

    try:
        ss = connect_to_sheets()
    except Exception as e:
        msg = f"ERROR: Could not connect to Google Sheets: {e}"
        print(msg)
        send_slack(f":x: {msg}")
        return

    # 1) Combine content
    combined = build_all_sources_df(ss)
    if combined.empty:
        msg = "No content found in source tabs. Ensure tabs exist and contain data."
        print(msg)
        send_slack(f":warning: {msg}")
        return

    # 2) Save combined content tab
    upload_df_to_sheet(ss, combined[["Source","Content Type","Text","URL","Topic","Date"]], ALL_SOURCES_TAB)
    send_slack(f":inbox_tray: Combined {len(combined)} items into *{ALL_SOURCES_TAB}*")

    # 3) Run sentiment
    sentiment_df = run_sentiment(combined)
    # push to Sentiment_Results_All (include scores)
    sentiment_out = sentiment_df.drop(columns=["Raw"], errors="ignore")
    upload_df_to_sheet(ss, sentiment_out, SENTIMENT_RESULTS_TAB)
    send_slack(f":receipt: Saved {len(sentiment_out)} sentiment results to *{SENTIMENT_RESULTS_TAB}*")

    # 4) Build dashboard
    dashboard = build_dashboard(sentiment_out)
    if dashboard.empty:
        print("Dashboard empty.")
    else:
        upload_df_to_sheet(ss, dashboard, DASHBOARD_TAB)
        send_slack(":bar_chart: Updated performance metrics dashboard.")

    # 5) Post a short summary and alert if negative share high
    # Create per content-type summary text
    summary_lines = []
    for _, row in dashboard.iterrows():
        ctype = row["Content Type"]
        posts = int(row["Posts"])
        avg = float(row["Avg_Compound"])
        pct_pos = float(row.get("PCT_POSITIVE", 0.0))
        pct_neg = float(row.get("PCT_NEGATIVE", 0.0))
        summary_lines.append(f"• {ctype}\n   - Posts: {posts}\n   - Avg Sentiment: {avg:.2f}\n   - Positive: {pct_pos:.0f}%\n   - Negative: {pct_neg:.0f}%")

    summary_text = "*Daily Sentiment Summary*\n" + "\n".join(summary_lines)
    send_slack(f":bar_chart: {summary_text}")

    # alert condition: any content type with negative percentage > threshold
    alerts = []
    for _, row in dashboard.iterrows():
        pct_neg = float(row.get("PCT_NEGATIVE", 0.0))
        if pct_neg / 100.0 > NEGATIVE_SHARE_ALERT:
            alerts.append((row["Content Type"], pct_neg))

    if alerts:
        alert_text = ":rotating_light: *Negative sentiment spike detected*:\n" + "\n".join(
            [f"- {ctype}: {pct:.1f}% negative" for ctype, pct in alerts]
        )
        send_slack(alert_text)

    send_slack(":dart: Sentiment analysis completed successfully!")
    print("Done.")


if __name__ == "__main__":
    main()
