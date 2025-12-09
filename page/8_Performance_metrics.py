"""
performance_metrics.py
Creates ONE clean tab = Content_Insights
Uses Sentiment_Results_All (your existing sheet)
"""

import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
import requests
from datetime import datetime

# config
SHEET_NAME = "Content Performance Tracker"
CREDENTIALS = "credentials.json"
INPUT_TAB = "Sentiment_Results_All"
OUTPUT_TAB = "Content_Insights"

def connect_sheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME)

def safe_get(sheet, tab):
    try:
        return sheet.worksheet(tab)
    except:
        return None

def main():
    sheet = connect_sheet()
    ws = safe_get(sheet, INPUT_TAB)

    if ws is None:
        print("Sentiment_Results_All is missing.")
        return

    df = pd.DataFrame(ws.get_all_records())

    # Clean missing values
    df = df.fillna("")

    # Convert compound scores to float safely
    df["compound"] = pd.to_numeric(df["compound"], errors="coerce").fillna(0)

    # -------- METRICS ----------
    total_items = len(df)
    positive_pct = round((df["Sentiment_Label"].eq("positive").mean()) * 100, 2)
    negative_pct = round((df["Sentiment_Label"].eq("negative").mean()) * 100, 2)
    neutral_pct = round((df["Sentiment_Label"].eq("neutral").mean()) * 100, 2)

    avg_sentiment = round(df["compound"].mean(), 3)

    # top & bottom content
    top_row = df.sort_values(by="compound", ascending=False).head(1)
    bottom_row = df.sort_values(by="compound", ascending=True).head(1)

    top_text = top_row["Text"].values[0][:120]
    bottom_text = bottom_row["Text"].values[0][:120]

    # Most active platform
    most_active = df["Source"].value_counts().idxmax()

    # Most positive / negative platform
    platform_scores = df.groupby("Source")["compound"].mean()

    most_positive_platform = platform_scores.idxmax()
    most_negative_platform = platform_scores.idxmin()

    # Most common topic
    if "Topic" in df.columns:
        most_common_topic = df["Topic"].value_counts().idxmax()
    else:
        most_common_topic = "N/A"

    # ---------- BUILD TABLE -----------
    out = [
        ["Metric", "Value"],
        ["Total Items Analyzed", total_items],
        ["Positive %", positive_pct],
        ["Negative %", negative_pct],
        ["Neutral %", neutral_pct],
        ["Average Sentiment Score", avg_sentiment],
        ["Top Content Snippet", top_text],
        ["Bottom Content Snippet", bottom_text],
        ["Most Active Platform", most_active],
        ["Most Positive Platform", most_positive_platform],
        ["Most Negative Platform", most_negative_platform],
        ["Most Common Topic", most_common_topic],
        ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ]

    # ---------- WRITE -----------
    out_ws = safe_get(sheet, OUTPUT_TAB)
    if out_ws:
        out_ws.clear()
    else:
        out_ws = sheet.add_worksheet(OUTPUT_TAB, rows=200, cols=2)

    out_ws.update(out)

    print("Content Insights Updated Successfully!")

if __name__ == "__main__":
    main()
