"""
AI Content Generator (Multi-Product + Multi-Platform)

Generate marketing content for multiple products (e.g., smart gadgets)
across multiple platforms (Twitter, Instagram, LinkedIn, etc.)
and log everything neatly in Google Sheets.

Now includes:
✅ Slack alerts for each generated content
✅ Slack alerts for model failures
"""

# IMPORTS 
import os
import re
import pandas as pd
from datetime import datetime
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from nltk.corpus import stopwords
import nltk
from huggingface_hub import InferenceClient
import requests   # <-- for Slack

load_dotenv("secrettt.env")

nltk.download("stopwords")
STOPWORDS = set(stopwords.words("english"))


# ---------- CONFIG ----------
GOOGLE_SHEET_NAME = "Content Performance Tracker"
CREDENTIALS_FILE = "credentials.json"
GENERATED_TAB_NAME = "Generated_Marketing_Content"

HF_TOKEN = os.getenv("HF_TOKEN")
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ---------- SLACK CONFIG ----------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

def send_slack_message(message):
    """Send notification to Slack channel."""
    try:
        payload = {"text": message}
        requests.post(SLACK_WEBHOOK_URL, json=payload)
    except Exception as e:
        print("Slack Error:", e)


# ---------- GOOGLE SHEETS AUTH ----------
def connect_to_sheets():
    """Authenticate and connect to Google Sheets."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client_sheets = gspread.authorize(creds)
    return client_sheets.open(GOOGLE_SHEET_NAME)


# ---------- TEXT HELPERS ----------
def clean_text(text):
    """Clean and normalize text."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"http\S+", " ", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text):
    """Split text into clean tokens."""
    return [w for w in clean_text(text).split() if w not in STOPWORDS and len(w) > 2]


# ---------- CONTENT GENERATION ----------
def generate_marketing_content(product_info, content_type, tone, keywords):
    """Generate platform-specific marketing content."""
    prompt = (
        f"Generate a {tone} {content_type} for this product:\n"
        f"{product_info}\n"
        f"Include these keywords if possible: {', '.join(keywords)}.\n"
        f"Keep it catchy, professional, and suitable for {content_type}."
    )

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        print(f"\n Trying model: {model}")
        try:
            client = InferenceClient(api_key=HF_TOKEN)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a creative AI marketing assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.7,
            )

            text = response.choices[0].message["content"].strip()

            # SLACK ALERT → success
            send_slack_message(
                f"🟢 Generated {content_type} for product: *{product_info[:30]}...*\nModel: {model}"
            )

            print(f"Generated {content_type} using {model}")
            return text, model, None

        except Exception as e:
            # SLACK ALERT → model failed
            send_slack_message(f"🔴 Model failed: {model}\nError: {e}")
            print(f" Model {model} failed: {e}")

    # If all models fail
    return None, None, "All models failed."


# ---------- UPLOAD RESULTS ----------
def upload_generated_content(records):
    """Upload generated results to Google Sheets."""
    sheet = connect_to_sheets()
    try:
        ws = sheet.worksheet(GENERATED_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=GENERATED_TAB_NAME, rows="1000", cols="20")

    headers = [
        "Timestamp",
        "Product Info",
        "Content Type Requested",
        "Tone Requested",
        "Keywords Used",
        "Model Used",
        "Generated Content",
        "Error Message",
    ]
    data_rows = [[r.get(h, "") for h in headers] for r in records]
    ws.clear()
    ws.update("A1", [headers] + data_rows)

    # SLACK ALERT
    send_slack_message(f"📤 Uploaded {len(records)} generated posts to Google Sheets.")

    print(f"📤 Uploaded {len(records)} rows to Google Sheets → {GENERATED_TAB_NAME}")


# ---------- MAIN ----------
def main():
    print("\nStarting AI Multi-Product, Multi-Platform Content Generator")

    # Define common trending keywords
    common_keywords = [
        "marketing", "content", "strategy", "digital", "growth",
        "productivity", "innovation", "design", "smart", "brand"
    ]

    # Define products
    products = [
        {
            "name": "LumiCharge Pro",
            "info": "Introducing 'LumiCharge Pro' — a smart desk lamp with wireless charging, adjustable brightness, and minimalist design for productivity and comfort.",
        },
        {
            "name": "WorkPod Mini",
            "info": "Meet 'WorkPod Mini' — a compact, soundproof workspace pod with ergonomic lighting and smart temperature control designed for focus and creativity.",
        },
    ]

    # Define platforms
    content_requests = [
        {"type": "tweet", "tone": "exciting"},
        {"type": "short ad copy", "tone": "persuasive"},
        {"type": "Instagram caption", "tone": "fun and trendy"},
        {"type": "LinkedIn post", "tone": "professional and inspiring"},
        {"type": "YouTube description", "tone": "informative"},
        {"type": "Facebook post", "tone": "friendly and engaging"},
    ]

    generated_records = []

    # Loop through products and platforms
    for product in products:
        print(f"\nGenerating content for: {product['name']}")
        send_slack_message(f"✨ Starting content generation for product: {product['name']}")

        for req in content_requests:
            product_keywords = common_keywords[:5] if product["name"] == "LumiCharge Pro" else common_keywords[5:]

            content, model, error = generate_marketing_content(
                product_info=product["info"],
                content_type=req["type"],
                tone=req["tone"],
                keywords=product_keywords,
            )

            generated_records.append({
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Product Info": product["info"],
                "Content Type Requested": req["type"],
                "Tone Requested": req["tone"],
                "Keywords Used": ", ".join(product_keywords),
                "Model Used": model,
                "Generated Content": content,
                "Error Message": error,
            })

    upload_generated_content(generated_records)

    # Final Slack alert
    send_slack_message("🎯 Content generation completed successfully!")

    print("\n🎯 Content generation completed successfully for all products!")


# ENTRY 
if __name__ == "__main__":
    main()
