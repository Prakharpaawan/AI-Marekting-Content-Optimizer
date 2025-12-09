"""
simulated_ab_testing.py
Instant A/B Testing — No posting required.
Replaces AB_Testing tab every run (NO append).
"""

import argparse
import os
import time
from datetime import datetime
import pandas as pd
import requests

import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
from huggingface_hub import InferenceClient

load_dotenv("secrettt.env")

nltk.download("vader_lexicon", quiet=True)
sid = SentimentIntensityAnalyzer()

#  CONFIG 
GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"

GENERATED_TAB = "Generated_Marketing_Content"
AB_TAB = "AB_Testing"

HF_TOKEN = os.getenv("HF_TOKEN")
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")


#  HELPERS 
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


def safe_get(sheet, tab):
    try:
        return sheet.worksheet(tab)
    except:
        return None


#  GENERATE VARIANT 
def llm_variant(original, product, content_type, tone):
    prompt = (
        f"Create a Variant B of the following {content_type}.\n"
        f"Modify CTA, structure, tone slightly but keep meaning.\n"
        f"Maintain tone: {tone}\n\n"
        f"Product:\n{product}\n\n"
        f"Original:\n{original}\n\n"
        f"Return only Variant B."
    )

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            client = InferenceClient(api_key=HF_TOKEN)
            rsp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You create high-quality Variant B marketing content."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=180,
                temperature=0.8
            )
            return rsp.choices[0].message["content"].strip()
        except:
            continue

    return None


#  SIMULATED SCORE FUNCTIONS 
def sentiment_score(text):
    return sid.polarity_scores(text)["compound"]


def keyword_score(text):
    words = text.lower().split()
    keywords = ["smart", "innovative", "boost", "growth", "AI", "automation"]
    count = sum(1 for w in words if w in keywords)
    return min(count / 5, 1.0)


def readability_score(text):
    length = len(text.split())
    if length < 8:
        return 0.4
    if length > 60:
        return 0.5
    return 1.0


def cta_strength(text):
    ctas = ["buy now", "start today", "learn more", "explore", "try now"]
    return 1.0 if any(c in text.lower() for c in ctas) else 0.4


def trend_score(text):
    trends = ["2025", "trending", "modern", "automation", "AI"]
    return 1.0 if any(t.lower() in text.lower() for t in trends) else 0.5


def final_score(text):
    s = sentiment_score(text)
    k = keyword_score(text)
    r = readability_score(text)
    c = cta_strength(text)
    tr = trend_score(text)

    score = (0.30 * s +
             0.20 * k +
             0.20 * r +
             0.20 * tr +
             0.10 * c)

    return round(score, 3)


#  A/B CREATE
def create_ab_tests():
    sheet = connect_to_sheets()
    ws = safe_get(sheet, GENERATED_TAB)

    df = pd.DataFrame(ws.get_all_records())

    # Prepare fresh A/B sheet 
    ab_ws = safe_get(sheet, AB_TAB)
    if ab_ws:
        ab_ws.clear()
    else:
        ab_ws = sheet.add_worksheet(AB_TAB, rows=2000, cols=20)

    headers = [
        "Test ID", "Timestamp", "Product Info", "Content Type", "Tone",
        "A_Text", "B_Text", "Score A", "Score B", "Winner"
    ]
    ab_ws.update("A1", [headers])

    results = []

    for idx, row in df.iterrows():
        original = row["Generated Content"]
        product = row["Product Info"]
        ctype = row["Content Type Requested"]
        tone = row["Tone Requested"]

        variant = llm_variant(original, product, ctype, tone)
        if not variant:
            continue

        score_a = final_score(original)
        score_b = final_score(variant)

        winner = "A" if score_a > score_b else "B"

        test_id = f"T{int(time.time())}-{idx}"

        results.append([
            test_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            product,
            ctype,
            tone,
            original,
            variant,
            score_a,
            score_b,
            winner
        ])

        send_slack(
            f":large_green_circle: Instant A/B Test Completed\n"
            f"Product: {product[:40]}\n"
            f"Winner: *{winner}*\n"
            f"A = {score_a} | B = {score_b}"
        )

        time.sleep(0.3)

    # Write all results (replace mode)
    if results:
        ab_ws.append_rows(results)

    send_slack(":dart: All A/B Tests Completed (Replaced old results).")


#  MAIN 
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()

    if args.create:
        create_ab_tests()
    else:
        print("Use: python ab_testing.py --create")
