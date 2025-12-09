"""
AI Content Optimizer (Trend-Aware + Slack Alerts)

Optimizes content generated earlier by improving tone, clarity,
and trend alignment. Sends real-time updates to Slack.
"""

# ===================== IMPORTS =====================
import os

import gspread
import pandas as pd
import requests
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from huggingface_hub import InferenceClient

load_dotenv("secrettt.env")


# ===================== CONFIG =====================
GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"
SOURCE_TAB = "Generated_Marketing_Content"
OPTIMIZED_TAB = "Optimized_Content"

HF_TOKEN = os.getenv("HF_TOKEN")
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# Slack Webhook
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")


# ===================== SLACK HELPERS =====================
def send_slack(message):
    """Send a message to Slack."""
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message})
    except Exception as e:
        print("Slack Error:", e)


# ===================== GOOGLE SHEETS AUTH =====================
def connect_to_sheets():
    """Authenticate and connect to Google Sheets."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client_sheets = gspread.authorize(creds)
    return client_sheets.open(GOOGLE_SHEET_NAME)


# ===================== LOAD GENERATED CONTENT =====================
def load_generated_content():
    """Load generated marketing content from Google Sheets."""
    print(" Fetching generated content...")
    send_slack("📥 *Starting content optimization process...*")

    sheet = connect_to_sheets()
    ws = sheet.worksheet(SOURCE_TAB)
    df = pd.DataFrame(ws.get_all_records())

    send_slack(f"📄 Loaded *{len(df)} posts* for optimization.")
    return df


# ===================== OPTIMIZE CONTENT =====================
def optimize_content(text, tone, platform, keywords):
    """Optimize content using trend-aware LLM rewriting."""
    prompt = (
        f"You are a professional AI marketing editor. "
        f"Optimize the following {platform} post written in a {tone} tone. "
        f"Analyze it using current digital marketing trends and audience engagement patterns. "
        f"Enhance it using trending keywords or phrases such as: {keywords}. "
        f"Keep it short, catchy, grammatically correct, and audience-focused.\n\n"
        f"Original Content:\n{text}\n\n"
        f"Return the result in this format:\n"
        f"Optimized Content: <rewritten version>\n"
        f"Improvement Notes: <trend usage + changes>\n"
        f"Score (out of 10): <estimated improvement score>"
    )

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            client = InferenceClient(api_key=HF_TOKEN)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert marketing copywriter."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.7,
            )

            output = response.choices[0].message["content"].strip()
            return output, model, None

        except Exception as e:
            send_slack(f"⚠️ Model `{model}` failed: {e}")

    return None, None, "Both models failed."


# ===================== PARSE LLM OUTPUT =====================
def parse_optimization_output(output):
    """Extract optimized content, notes, and score."""
    if not output:
        return "", "", ""

    lines = output.split("\n")
    optimized = next((l.replace("Optimized Content:", "").strip() for l in lines if "Optimized Content:" in l), "")
    notes = next((l.replace("Improvement Notes:", "").strip() for l in lines if "Improvement Notes:" in l), "")
    score = next((l.replace("Score", "").replace(":", "").strip() for l in lines if "Score" in l), "")

    return optimized, notes, score


# ===================== UPLOAD RESULTS =====================
def upload_optimized_results(records):
    """Upload optimized content to Google Sheets."""
    sheet = connect_to_sheets()

    try:
        ws = sheet.worksheet(OPTIMIZED_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=OPTIMIZED_TAB, rows="1000", cols="20")

    headers = [
        "Timestamp", "Product Info", "Content Type Requested", "Tone Requested",
        "Keywords Used", "Original Content", "Optimized Content",
        "Improvement Notes", "Optimization Score", "Model Used", "Error Message",
    ]

    rows = [[r.get(h, "") for h in headers] for r in records]
    ws.clear()

    # FIXED: Prevent positional argument deprecation warning
    ws.update(range_name="A1", values=[headers] + rows)

    send_slack(f"📤 *Uploaded {len(records)} optimized posts to Google Sheets.*")


# ===================== MAIN PROCESS =====================
def main():
    print("\n Starting Trend-Aware AI Content Optimizer...")
    df = load_generated_content()
    optimized_records = []

    for _, row in df.iterrows():
        text = row.get("Generated Content", "")
        if not text:
            continue

        tone = row.get("Tone Requested", "neutral")
        content_type = row.get("Content Type Requested", "post")
        product = row.get("Product Info", "N/A")
        keywords = row.get("Keywords Used", "")

        output, model, error = optimize_content(text, tone, content_type, keywords)
        optimized_text, notes, score = parse_optimization_output(output)

        optimized_records.append({
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Product Info": product,
            "Content Type Requested": content_type,
            "Tone Requested": tone,
            "Keywords Used": keywords,
            "Original Content": text,
            "Optimized Content": optimized_text,
            "Improvement Notes": notes,
            "Optimization Score": score,
            "Model Used": model,
            "Error Message": error,
        })

        send_slack(
            f"🟢 Optimized *{content_type}* for *{product[:30]}...*\n"
            f"Model: `{model}`"
        )

    upload_optimized_results(optimized_records)
    send_slack("🎯 *Trend-aware optimization completed successfully!*")


# ===================== ENTRY =====================
if __name__ == "__main__":
    main()
