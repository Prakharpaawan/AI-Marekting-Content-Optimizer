import streamlit as st
import os
import json
import time
from datetime import datetime
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

# ----- NLTK SETUP -----

# Check if the VADER sentiment lexicon is already available
# If not available, download it automatically
try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    nltk.download('vader_lexicon')

# Initialize the VADER sentiment analyzer
sid = SentimentIntensityAnalyzer()

# ----- AUTHENTICATION SETUP -----

# This function is used to fetch secret values like API keys.
# It first checks Streamlit Cloud secrets.
# If not found, it loads values from a local .env file.
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    try:
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

# This function connects the app to Google Sheets.
# It works both on Streamlit Cloud and on a local system.
def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # First try to load Google credentials from Streamlit Cloud secrets
    try:
        if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            
            # Fix formatting issue in private key
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client.open("Content Performance Tracker")
    except Exception:
        pass

    # If cloud secrets are not available, try local credentials.json
    if os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    elif os.path.exists("../credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    else:
        # Stop the app if Google credentials are missing
        st.error("❌ Critical Error: No Google Credentials found!")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----

# Hugging Face API token for AI text generation
HF_TOKEN = get_secret("HF_TOKEN")

# Slack webhook URL for notifications
SLACK_WEBHOOK = get_secret("SLACK_WEBHOOK_URL")

# Google Sheets tab names
GENERATED_TAB = "Generated_Marketing_Content"
AB_TAB = "AB_Testing"

# Primary and fallback AI models
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ----- HELPERS -----

# This function sends a message to Slack
def send_slack(text):
    if not SLACK_WEBHOOK: 
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": text})
    except Exception:
        pass

# This function safely fetches a worksheet by name
def safe_get_worksheet(sheet, tab_name):
    try:
        return sheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return None

# ----- VARIANT GENERATION -----

# This function creates a Variant B using an AI model
def llm_variant(original, product, content_type, tone):
    if not HF_TOKEN: 
        return None

    # Prompt sent to the AI model
    prompt = (
        f"Create a Variant B of the following {content_type}.\n"
        f"Modify CTA, structure, tone slightly but keep meaning.\n"
        f"Maintain tone: {tone}\n\n"
        f"Product:\n{product}\n\n"
        f"Original:\n{original}\n\n"
        f"Return only Variant B content."
    )

    # Try primary model first, fallback if it fails
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            client = InferenceClient(api_key=HF_TOKEN)
            rsp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You create high-quality Variant B marketing content."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=400,
                temperature=0.8
            )
            return rsp.choices[0].message["content"].strip()
        except Exception:
            continue

    return None

# ----- SCORING -----

# This function calculates a final score for a piece of content
def final_score(text):
    if not text: 
        return 0.0
    
    # Sentiment score from VADER
    s = sid.polarity_scores(text)["compound"]
    
    # Keyword presence score
    words = text.lower().split()
    keywords = ["smart", "innovative", "boost", "growth", "AI", "automation", "free", "now"]
    k_score = min(sum(1 for w in words if w in keywords) / 5, 1.0)
    
    # Readability score based on text length
    length = len(words)
    r_score = 1.0 if 8 <= length <= 60 else 0.5
    
    # Call-to-action strength score
    ctas = ["buy now", "start today", "learn more", "explore", "try now", "link in bio"]
    c_score = 1.0 if any(c in text.lower() for c in ctas) else 0.4
    
    # Final weighted score
    score = (0.3 * s) + (0.2 * k_score) + (0.2 * r_score) + (0.3 * c_score)
    return round(score, 3)

# ----- MAIN LOGIC -----

# This function runs A/B testing on generated content
def run_ab_test():
    sheet = connect_sheets()
    ws = safe_get_worksheet(sheet, GENERATED_TAB)
    if not ws:
        st.error(f"Tab '{GENERATED_TAB}' not found. Run Content Generator first.")
        return pd.DataFrame()

    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        st.warning("No content found to test.")
        return pd.DataFrame()

    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(df)
    for idx, row in df.iterrows():
        # Read original content (supports old and new column names)
        original = row.get("Content", "") or row.get("Generated Content", "")
        if not original: 
            continue

        product = row.get("Product Info", "Product")
        ctype = row.get("Content Type", "") or row.get("Content Type Requested", "Post")
        tone = row.get("Tone", "") or row.get("Tone Requested", "Neutral")

        status_text.write(f"Generating Variant B for Item {idx + 1}...")
        
        # Generate AI variant
        variant = llm_variant(original, product, ctype, tone)
        if not variant: 
            continue

        # Score both variants
        score_a = final_score(original)
        score_b = final_score(variant)
        winner = "Variant A" if score_a >= score_b else "Variant B"

        # Store test results
        results.append({
            "Test ID": f"T{int(time.time())}-{idx}",
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Product": product,
            "Content Type": ctype,
            "Variant A (Original)": original,
            "Variant B (AI)": variant,
            "Score A": score_a,
            "Score B": score_b,
            "Winner": winner
        })
        
        # Update progress bar
        progress_bar.progress((idx + 1) / total)

    status_text.success("✅ A/B Testing Complete!")
    return pd.DataFrame(results)

# This function uploads A/B test results to Google Sheets
def upload_results(df):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(AB_TAB)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=AB_TAB, rows="1000", cols="20")
    
    ws.update(values=[df.columns.tolist()] + df.astype(str).values.tolist(), range_name="A1")
    st.toast(f"Uploaded {len(df)} A/B tests to Sheets!", icon="🚀")

# ----- STREAMLIT UI -----

# App title and description
st.title("⚖️ A/B Testing Simulator")
st.markdown("Compare your original content against AI-generated variants to find the winner.")

# Button to start A/B testing
if st.button("🚀 Start A/B Simulation", type="primary"):
    with st.spinner("Connecting to Google Sheets..."):
        results_df = run_ab_test()
    
    if not results_df.empty:
        st.write(f"### 🏆 Test Results ({len(results_df)} Tests)")
        
        # Show comparison table
        st.dataframe(
            results_df[["Product", "Variant A (Original)", "Variant B (AI)", "Score A", "Score B", "Winner"]],
            column_config={
                "Variant A (Original)": st.column_config.TextColumn("Original", width="medium"),
                "Variant B (AI)": st.column_config.TextColumn("Challenger", width="medium"),
                "Winner": st.column_config.TextColumn("Winner", width="small"),
            },
            hide_index=True
        )
        
        # Count wins for each variant
        a_wins = len(results_df[results_df["Winner"] == "Variant A"])
        b_wins = len(results_df[results_df["Winner"] == "Variant B"])
        
        col1, col2 = st.columns(2)
        col1.metric("Original Wins", a_wins)
        col2.metric("AI Variant Wins", b_wins)
        
        # Upload results and notify Slack
        upload_results(results_df)
        send_slack(f"⚖️ A/B Testing Done: {a_wins} A vs {b_wins} B wins.")
