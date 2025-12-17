import streamlit as st
import os
import json
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

# ----- AUTHENTICATION & SECRETS SETUP -----

# This function is used to fetch secret values like API tokens.
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
# It supports both Streamlit Cloud and local execution.
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

# Hugging Face API token for optimization
HF_TOKEN = get_secret("HF_TOKEN")

# Slack webhook URL for notifications
SLACK_WEBHOOK = get_secret("SLACK_WEBHOOK_URL")

# Source and destination Google Sheets tabs
SOURCE_TAB = "Generated_Marketing_Content"
OPTIMIZED_TAB = "Optimized_Content"

# Primary and fallback AI models
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ----- HELPERS -----

# This function sends a message to Slack
def send_slack(message):
    if not SLACK_WEBHOOK: 
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message})
    except Exception:
        pass

# This function loads previously generated content from Google Sheets
def load_generated_content():
    """Load generated marketing content from Google Sheets."""
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(SOURCE_TAB)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Tab '{SOURCE_TAB}' not found! Run the Content Generator first.")
        return pd.DataFrame()

# This function rewrites content to make it better using AI
def optimize_content(text, tone, platform, keywords):
    """Optimize content using trend-aware LLM rewriting."""
    if not HF_TOKEN:
        return None, None, "Missing HF Token"

    # Prompt sent to the AI model for optimization
    prompt = (
        f"You are a professional AI marketing editor. "
        f"Optimize the following {platform} post written in a {tone} tone. "
        f"Enhance it using trending keywords: {keywords}. "
        f"Keep it short, catchy, and audience-focused.\n\n"
        f"Original Content:\n{text}\n\n"
        f"Return the result in this format:\n"
        f"Optimized Content: <rewritten version>\n"
        f"Improvement Notes: <trend usage + changes>\n"
        f"Score (out of 10): <estimated improvement score>"
    )

    # Try the primary model first, then fallback if it fails
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            client = InferenceClient(api_key=HF_TOKEN)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert marketing copywriter."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500, 
                temperature=0.7,
            )
            output = response.choices[0].message["content"].strip()
            return output, model, None
        except Exception as e:
            print(f"Model {model} failed: {e}")
            continue

    return None, None, "All models failed."

# This function extracts optimized text, notes, and score from the AI output
def parse_optimization_output(output):
    """Robust Parser: Extracts content even if formatting is messy."""
    if not output: 
        return "N/A", "N/A", "N/A"
    
    optimized = ""
    notes = ""
    score = ""
    
    parts = output.split('\n')
    current_section = None
    
    # Go line by line and detect which section we are reading
    for line in parts:
        line = line.strip()
        if "Optimized Content:" in line:
            current_section = "optimized"
            optimized += line.replace("Optimized Content:", "").strip() + " "
        elif "Improvement Notes:" in line:
            current_section = "notes"
            notes += line.replace("Improvement Notes:", "").strip() + " "
        elif "Score" in line and "out of 10" in line:
            current_section = "score"
            score = line.replace("Score", "").replace("(out of 10)", "").replace(":", "").strip()
        elif current_section == "optimized":
            optimized += line + " "
        elif current_section == "notes":
            notes += line + " "
            
    # Fallback if AI output does not follow the expected format
    if not optimized.strip():
        optimized = output 
        notes = "Auto-parsed raw output"
        
    return optimized.strip(), notes.strip(), score.strip()

# This function uploads optimized results to Google Sheets
def upload_optimized_results(records):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(OPTIMIZED_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=OPTIMIZED_TAB, rows="1000", cols="20")

    # Add headers only if the sheet is empty
    if not ws.get_all_values():
        headers = [
            "Timestamp", "Product Info", "Content Type", "Tone", "Keywords", 
            "Original Content", "Optimized Content", "Improvement Notes", 
            "Optimization Score", "Model Used", "Error Message"
        ]
        ws.append_row(headers)

    rows = []
    for r in records:
        rows.append([
            r["Timestamp"], r["Product Info"], r["Content Type Requested"],
            r["Tone Requested"], r["Keywords Used"], r["Original Content"],
            r["Optimized Content"], r["Improvement Notes"], r["Optimization Score"],
            r["Model Used"], r["Error Message"]
        ])
    
    ws.append_rows(rows)
    st.toast(f"Uploaded {len(records)} optimized posts!", icon="✅")

# ----- STREAMLIT UI -----

# App title and description
st.title("✨ AI Content Optimizer")
st.markdown("Refine your generated content with trend-aware optimization.")

# Button to start optimization process
if st.button("🚀 Start Optimization Process", type="primary"):
    with st.spinner("Fetching generated content..."):
        df = load_generated_content()
    
    if df.empty:
        st.warning("No content found to optimize. Run the Content Generator first!")
    else:
        st.write(f"### Found {len(df)} posts to optimize")
        
        optimized_records = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total = len(df)
        for idx, row in df.iterrows():
            # Read original content from the sheet
            text = row.get("Content", "") or row.get("Generated Content", "")
            if not text: 
                continue

            status_text.write(f"Optimizing post {idx + 1}/{total}...")
            
            # Read metadata needed for optimization
            tone = row.get("Tone", "") or row.get("Tone Requested", "neutral")
            ctype = row.get("Content Type", "") or row.get("Content Type Requested", "post")
            keywords = row.get("Keywords", "") or row.get("Keywords Used", "")
            product = row.get("Product Info", "Unknown Product")
            
            # Optimize content using AI
            output, model, error = optimize_content(text, tone, ctype, keywords)
            
            # Parse AI output into structured fields
            opt_text, notes, score = parse_optimization_output(output)
            
            optimized_records.append({
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Product Info": product,
                "Content Type Requested": ctype,
                "Tone Requested": tone,
                "Keywords Used": keywords,
                "Original Content": text,
                "Optimized Content": opt_text,
                "Improvement Notes": notes,
                "Optimization Score": score,
                "Model Used": model,
                "Error Message": error,
            })
            
            # Update progress bar
            progress_bar.progress((idx + 1) / total)

        status_text.success("✅ Optimization Complete!")
        
        # Show optimization results in a table
        st.write("### Optimization Results")
        res_df = pd.DataFrame(optimized_records)
        
        if not res_df.empty:
            st.dataframe(
                res_df,
                column_config={
                    "Original Content": st.column_config.TextColumn("Original", width="medium"),
                    "Optimized Content": st.column_config.TextColumn("Optimized", width="large"),
                    "Improvement Notes": st.column_config.TextColumn("Notes", width="medium"),
                },
                hide_index=True
            )
            
            # Upload optimized content and notify Slack
            upload_optimized_results(optimized_records)
            send_slack(f"🎯 Optimized {len(optimized_records)} posts successfully!")
