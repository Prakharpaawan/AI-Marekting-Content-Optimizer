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

# ----- AUTHENTICATION & SECRETS SETUP (Universal Fix) -----
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    # 1. Try Streamlit Secrets (Cloud)
    try:
        if hasattr(st, "secrets") and key_name in st.secrets:
            return st.secrets[key_name]
    except Exception:
        pass 

    # 2. Try Local .env (Laptop)
    try:
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # A. Try Cloud Secrets
    try:
        if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client.open("Content Performance Tracker")
    except Exception:
        pass

    # B. Try Local File
    if os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    elif os.path.exists("../credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    else:
        st.error("❌ Critical Error: No Google Credentials found!")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----
HF_TOKEN = get_secret("HF_TOKEN")
SLACK_WEBHOOK = get_secret("SLACK_WEBHOOK_URL")

SOURCE_TAB = "Generated_Marketing_Content"
OPTIMIZED_TAB = "Optimized_Content"
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ----- HELPERS -----
def send_slack(message):
    if not SLACK_WEBHOOK: return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message})
    except Exception:
        pass

def load_generated_content():
    """Load generated marketing content from Google Sheets."""
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(SOURCE_TAB)
        return pd.DataFrame(ws.get_all_records())
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Tab '{SOURCE_TAB}' not found!")
        return pd.DataFrame()

def optimize_content(text, tone, platform, keywords):
    """Optimize content using trend-aware LLM rewriting."""
    if not HF_TOKEN:
        return None, None, "Missing HF Token"

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
            print(f"Model {model} failed: {e}")
            continue

    return None, None, "All models failed."

def parse_optimization_output(output):
    """Extract optimized content, notes, and score."""
    if not output: return "", "", ""
    lines = output.split("\n")
    optimized = next((l.replace("Optimized Content:", "").strip() for l in lines if "Optimized Content:" in l), "")
    notes = next((l.replace("Improvement Notes:", "").strip() for l in lines if "Improvement Notes:" in l), "")
    score = next((l.replace("Score", "").replace(":", "").strip() for l in lines if "Score" in l), "")
    return optimized, notes, score

def upload_optimized_results(records):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(OPTIMIZED_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=OPTIMIZED_TAB, rows="1000", cols="20")

    if not ws.get_all_values():
        headers = ["Timestamp", "Product Info", "Content Type", "Tone", "Keywords", "Original", "Optimized", "Notes", "Score", "Model", "Error"]
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
st.title("✨ AI Content Optimizer")
st.markdown("Refine your generated content with trend-aware optimization.")

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
            text = row.get("Generated Content", "")
            if not text: continue

            status_text.write(f"Optimizing post {idx + 1}/{total}...")
            
            output, model, error = optimize_content(
                text, 
                row.get("Tone Requested", "neutral"),
                row.get("Content Type Requested", "post"),
                row.get("Keywords Used", "")
            )
            
            opt_text, notes, score = parse_optimization_output(output)
            
            optimized_records.append({
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Product Info": row.get("Product Info", ""),
                "Content Type Requested": row.get("Content Type Requested", ""),
                "Tone Requested": row.get("Tone Requested", ""),
                "Keywords Used": row.get("Keywords Used", ""),
                "Original Content": text,
                "Optimized Content": opt_text,
                "Improvement Notes": notes,
                "Optimization Score": score,
                "Model Used": model,
                "Error Message": error,
            })
            
            progress_bar.progress((idx + 1) / total)

        status_text.success("✅ Optimization Complete!")
        
        # Show Results
        st.write("### Optimization Results")
        res_df = pd.DataFrame(optimized_records)
        if not res_df.empty:
            st.dataframe(res_df[["Original Content", "Optimized Content", "Optimization Score"]])
            upload_optimized_results(optimized_records)
            send_slack(f"🎯 Optimized {len(optimized_records)} posts successfully!")
