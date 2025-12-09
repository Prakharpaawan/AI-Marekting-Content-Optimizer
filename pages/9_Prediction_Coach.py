# prediction_coach.py
"""
Prediction Coach
- Reads AB_Testing tab (created by ab_testing.py)
- Runs platform simulations and computes predicted viral score
- Writes results to Prediction_Coach tab and sends Slack summary
"""

import os
import time
from datetime import datetime
import pandas as pd
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
import requests

load_dotenv("secrettt.env")

# CONFIG
GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"
AB_TAB = "AB_Testing"
OUTPUT_TAB = "Prediction_Coach"

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

PLATFORMS = ["Twitter", "Instagram", "LinkedIn", "YouTube"]


def send_slack(text):
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text})
    except:
        pass


def connect_to_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(GOOGLE_SHEET_NAME)


def safe_get(ws, name):
    try:
        return ws.worksheet(name)
    except:
        return None


#  PLATFORM SIMULATION 
def platform_modifier(text, platform):
    text_l = (text or "").lower()
    length = len(text_l.split())
    mod = 0.0

    # Twitter rules
    if platform == "Twitter":
        if length <= 30:
            mod += 0.08
        if "#" in text_l or "trending" in text_l:
            mod += 0.05
        if "!" in text_l:
            mod += 0.02

    # Instagram rules
    if platform == "Instagram":
        if 8 <= length <= 60:
            mod += 0.07
        if "#" in text_l:
            mod += 0.07
        if any(w in text_l for w in ["amazing", "fun", "love", "cute"]):
            mod += 0.04

    # LinkedIn rules    
    if platform == "LinkedIn":
        if length >= 20:
            mod += 0.08
        if any(w in text_l for w in ["insight", "data", "strategy", "productivity", "growth"]):
            mod += 0.06

    # YouTube rules
    if platform == "YouTube":
        if length >= 40:
            mod += 0.07
        if any(w in text_l for w in ["how to", "tutorial", "guide", "watch"]):
            mod += 0.05

    # penalties
    if platform == "Twitter" and length > 50:
        mod -= 0.05
    if platform == "LinkedIn" and length < 10:
        mod -= 0.03

    return round(mod, 3)


#  POSTING TIME 
def suggest_posting_time(platform):
    if platform == "Twitter":
        return "5-8 PM (weekday evenings)"
    if platform == "Instagram":
        return "6-9 PM (weekday evenings)"
    if platform == "LinkedIn":
        return "8-10 AM (weekday mornings)"
    if platform == "YouTube":
        return "5-8 PM (weekend evenings)"
    return "Anytime"


#  VIRAL PREDICTION 
def compute_viral_prediction(base_score, text):
    platform_scores = {}
    for p in PLATFORMS:
        mod = platform_modifier(text, p)
        viral = 0.7 * float(base_score) + 0.3 * mod
        viral = max(0.0, min(1.0, viral))
        platform_scores[p] = round(viral, 3)

    best_platform = max(platform_scores, key=lambda k: platform_scores[k])
    return platform_scores, best_platform


#  MAIN 
def main():
    send_slack(":rocket: Prediction Coach starting...")

    try:
        sheet = connect_to_sheets()
    except Exception as e:
        send_slack(f":x: Error connecting to Google Sheets: {e}")
        return

    ab_ws = safe_get(sheet, AB_TAB)
    if ab_ws is None:
        send_slack(":warning: AB_Testing tab missing.")
        return

    rows = ab_ws.get_all_records()
    if not rows:
        send_slack(":warning: AB_Testing tab is empty.")
        return

    df_ab = pd.DataFrame(rows)
    output_rows = []

    for _, row in df_ab.iterrows():
        a_text = row.get("A_Text", "")
        b_text = row.get("B_Text", "")
        score_a = float(row["Score A"])
        score_b = float(row["Score B"])

        # Viral predictions
        platform_scores_a, best_platform_a = compute_viral_prediction(score_a, a_text)
        platform_scores_b, best_platform_b = compute_viral_prediction(score_b, b_text)

        best_score_a = platform_scores_a[best_platform_a]
        best_score_b = platform_scores_b[best_platform_b]

        # Choose winner
        recommended_variant = "A" if best_score_a >= best_score_b else "B"
        recommended_platform = best_platform_a if recommended_variant == "A" else best_platform_b
        posting_time = suggest_posting_time(recommended_platform)

        reason = f"Variant {recommended_variant} wins (A={best_score_a}, B={best_score_b}) on {recommended_platform}"

        output_rows.append({
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Product Info": row.get("Product Info", ""),
            "Content Type": row.get("Content Type", ""),
            "Tone": row.get("Tone", ""),
            "A_Text": a_text,
            "B_Text": b_text,
            "Score_A": score_a,
            "Score_B": score_b,
            "Best_Platform_A": best_platform_a,
            "Best_Platform_A_Score": best_score_a,
            "Best_Platform_B": best_platform_b,
            "Best_Platform_B_Score": best_score_b,
            "Recommended_Variant": recommended_variant,
            "Recommended_Platform": recommended_platform,
            "Recommended_Posting_Time": posting_time,
            "Recommendation_Reason": reason
        })

        # Slack update
        send_slack(
            f":mag: Prediction Result\n"
            f"Recommended Variant: {recommended_variant}\n"
            f"Platform: {recommended_platform}\n"
            f"Posting Time: {posting_time}\n"
            f"Reason: {reason}"
        )

    # Upload result
    try:
        ws = sheet.worksheet(OUTPUT_TAB)
        ws.clear()
    except:
        ws = sheet.add_worksheet(OUTPUT_TAB, rows=2000, cols=20)

    df_out = pd.DataFrame(output_rows)
    headers = df_out.columns.tolist()
    values = [headers] + df_out.fillna("").values.tolist()
    ws.update("A1", values)

    send_slack(":white_check_mark: Prediction Coach completed.")


if __name__ == "__main__":
    main()
