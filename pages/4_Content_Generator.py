import streamlit as st
import os
import json
import re
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from huggingface_hub import InferenceClient
from nltk.corpus import stopwords
import nltk
import requests

# Download nltk resource quietly
nltk.download("stopwords", quiet=True)
STOPWORDS = set(stopwords.words("english"))

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
        from dotenv import load_dotenv
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON (Robust Path Check)"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # A. Try Cloud Secrets (Streamlit Cloud)
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

    # B. Try Local File (Laptop) - CHECK BOTH LOCATIONS
    if os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    elif os.path.exists("../credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    else:
        st.error("❌ Critical Error: credentials.json not found in current or parent directory.")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----
HF_TOKEN = get_secret("HF_TOKEN")
SLACK_WEBHOOK_URL = get_secret("SLACK_WEBHOOK_URL")

GENERATED_TAB_NAME = "Generated_Marketing_Content"
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ----- HELPERS -----
def send_slack_message(message):
    if not SLACK_WEBHOOK_URL: return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    except Exception as e:
        print(f"Slack Error: {e}")

def generate_marketing_content(product_info, content_type, tone, keywords):
    if not HF_TOKEN:
        return None, None, "Missing HF_TOKEN"

    prompt = (
        f"Generate a {tone} {content_type} for this product:\n"
        f"{product_info}\n"
        f"Include these keywords if possible: {', '.join(keywords)}.\n"
        f"Keep it catchy, professional, and suitable for {content_type}."
    )

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
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
            return text, model, None
        except Exception as e:
            print(f"Model {model} failed: {e}")
            continue

    return None, None, "All models failed."

def upload_generated_content(records):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(GENERATED_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=GENERATED_TAB_NAME, rows="1000", cols="20")

    # If sheet is empty, add headers
    if not ws.get_all_values():
        headers = ["Timestamp", "Product Info", "Content Type", "Tone", "Keywords", "Model", "Content", "Error"]
        ws.append_row(headers)

    # Prepare rows
    rows_to_add = []
    for r in records:
        rows_to_add.append([
            r["Timestamp"], r["Product Info"], r["Content Type Requested"],
            r["Tone Requested"], r["Keywords Used"], r["Model Used"],
            r["Generated Content"], r["Error Message"]
        ])
    
    ws.append_rows(rows_to_add)
    st.toast(f"Uploaded {len(records)} posts to Sheets!", icon="✅")

# ----- STREAMLIT UI -----
st.title("✍️ AI Content Generator")
st.markdown("Generate multi-platform marketing posts for your products instantly.")

with st.form("gen_form"):
    product_name = st.text_input("Product Name", "LumiCharge Pro")
    product_desc = st.text_area("Product Description", "A smart desk lamp with wireless charging...")
    
    col1, col2 = st.columns(2)
    with col1:
        content_types = st.multiselect("Content Types", 
            ["Tweet", "LinkedIn Post", "Instagram Caption", "Ad Copy"], 
            default=["Tweet", "LinkedIn Post"])
    with col2:
        tones = st.multiselect("Tones", ["Professional", "Witty", "Urgent", "Friendly"], default=["Professional"])
        
    keywords = st.text_input("Keywords (comma separated)", "smart, efficiency, design")
    
    submitted = st.form_submit_button("🚀 Generate Content")

if submitted:
    if not product_desc:
        st.error("Please enter a product description.")
    else:
        status = st.status("🤖 AI Agents working...", expanded=True)
        results = []
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        
        # Loop through combinations
        total_ops = len(content_types) * len(tones)
        completed = 0
        
        for ctype in content_types:
            for tone in tones:
                status.write(f"Drafting {tone} {ctype}...")
                content, model, err = generate_marketing_content(product_desc, ctype, tone, kw_list)
                
                results.append({
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Product Info":
