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

# ----- NLTK SETUP (Robust Fix) -----

# This checks if NLTK stopwords are already available.
# If not, it downloads them automatically.
import nltk
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

# Load English stopwords into a set for faster lookup
from nltk.corpus import stopwords
STOPWORDS = set(stopwords.words("english"))

# ----- AUTHENTICATION SETUP -----

# This function fetches secrets like API tokens.
# It first checks Streamlit Cloud secrets.
# If not found, it loads values from a local .env file.
def get_secret(key_name):
    """Fetch secret from Streamlit Cloud OR Local .env file"""
    if hasattr(st, "secrets") and key_name in st.secrets:
        return st.secrets[key_name]
    try:
        from dotenv import load_dotenv
        load_dotenv("secrettt.env")
        return os.getenv(key_name)
    except ImportError:
        return None

# This function connects the app to Google Sheets.
# It supports both Streamlit Cloud and local execution.
def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # First try to load credentials from Streamlit Cloud secrets
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

# Hugging Face API token for AI content generation
HF_TOKEN = get_secret("HF_TOKEN")

# Slack webhook URL for notifications
SLACK_WEBHOOK_URL = get_secret("SLACK_WEBHOOK_URL")

# Google Sheets tab name for storing generated content
GENERATED_TAB_NAME = "Generated_Marketing_Content"

# Primary and fallback AI models
PRIMARY_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ----- HELPERS -----

# This function sends a message to Slack when content is generated
def send_slack_message(message):
    if not SLACK_WEBHOOK_URL: 
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    except Exception as e:
        print(f"Slack Error: {e}")

# This function generates marketing content using AI models
def generate_marketing_content(product_info, content_type, tone, keywords):
    if not HF_TOKEN:
        return None, None, "Missing HF_TOKEN"

    # Prompt sent to the AI model
    prompt = (
        f"Generate a {tone} {content_type} for this product:\n"
        f"{product_info}\n"
        f"Include these keywords if possible: {', '.join(keywords)}.\n"
        f"Keep it catchy, professional, and suitable for {content_type}."
    )

    # Try primary model first, then fallback model if needed
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            client = InferenceClient(api_key=HF_TOKEN)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a creative AI marketing assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0.7,
            )
            text = response.choices[0].message["content"].strip()
            return text, model, None
        except Exception as e:
            print(f"Model {model} failed: {e}")
            continue

    return None, None, "All models failed."

# This function uploads generated content to Google Sheets
def upload_generated_content(records):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(GENERATED_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=GENERATED_TAB_NAME, rows="1000", cols="20")

    # Clear the sheet first so old data is removed
    ws.clear()

    # Column headers for the sheet
    headers = [
        "Timestamp", "Product Info", "Content Type", "Tone",
        "Keywords", "Model", "Generated Content", "Error Message"
    ]

    # Prepare rows to upload
    rows_to_add = []
    for r in records:
        rows_to_add.append([
            r["Timestamp"], r["Product Info"], r["Content Type Requested"],
            r["Tone Requested"], r["Keywords Used"], r["Model Used"],
            r["Generated Content"], r["Error Message"]
        ])
    
    # Upload headers and data starting from the first cell
    ws.update(values=[headers] + rows_to_add, range_name="A1")
    
    st.toast(f"Uploaded {len(records)} fresh posts (Sheet Cleared)!", icon="✅")

# ----- STREAMLIT UI -----

# App title and description
st.title("✍️ AI Content Generator")
st.markdown("Generate multi-platform marketing posts for your products instantly.")

# Form to collect user input
with st.form("gen_form"):
    product_name = st.text_input("Product Name", "LumiCharge Pro")
    product_desc = st.text_area("Product Description", "A smart desk lamp with wireless charging...")
    
    col1, col2 = st.columns(2)
    with col1:
        content_types = st.multiselect(
            "Content Types",
            ["Tweet", "LinkedIn Post", "Instagram Caption", "Ad Copy"],
            default=["Tweet", "LinkedIn Post"]
        )
    with col2:
        tones = st.multiselect(
            "Tones",
            ["Professional", "Witty", "Urgent", "Friendly"],
            default=["Professional"]
        )
        
    keywords = st.text_input("Keywords (comma separated)", "smart, efficiency, design")
    
    submitted = st.form_submit_button("🚀 Generate Content")

# Run content generation when form is submitted
if submitted:
    if not product_desc:
        st.error("Please enter a product description.")
    else:
        status = st.status("🤖 AI Agents working...", expanded=True)
        results = []
        
        # Convert keyword input into a list
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        
        completed = 0
        
        # Generate content for each content type and tone
        for ctype in content_types:
            for tone in tones:
                status.write(f"Drafting {tone} {ctype}...")
                content, model, err = generate_marketing_content(
                    product_desc, ctype, tone, kw_list
                )
                
                results.append({
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Product Info": product_name,
                    "Content Type Requested": ctype,
                    "Tone Requested": tone,
                    "Keywords Used": keywords,
                    "Model Used": model,
                    "Generated Content": content,
                    "Error Message": err
                })
                
                # Send Slack notification if content is generated
                if content:
                    send_slack_message(f"✨ New {ctype} generated for {product_name}!")
                
                completed += 1
        
        status.update(label="✅ Generation Complete!", state="complete", expanded=False)
        
        # Show generated content on the UI
        for res in results:
            with st.expander(f"{res['Tone Requested']} {res['Content Type Requested']}", expanded=True):
                if res['Error Message']:
                    st.error(res['Error Message'])
                else:
                    st.write(res['Generated Content'])
                    st.caption(f"Model: {res['Model Used']}")
        
        # Upload results to Google Sheets
        if results:
            upload_generated_content(results)
