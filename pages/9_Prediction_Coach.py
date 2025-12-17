import streamlit as st
import os
import json
import time
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from dotenv import load_dotenv

# ----- AUTHENTICATION SETUP -----

# This function fetches secret values like API keys.
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

# Slack webhook URL for notifications
SLACK_WEBHOOK = get_secret("SLACK_WEBHOOK_URL")

# Google Sheets tab names
AB_TAB = "AB_Testing"
OUTPUT_TAB = "Prediction_Coach"

# Platforms used for prediction
PLATFORMS = ["Twitter", "Instagram", "LinkedIn", "YouTube"]

# ----- HELPERS -----

# This function sends a short message to Slack
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

# ----- PREDICTION LOGIC -----

# This function adjusts score based on platform-specific rules
def platform_modifier(text, platform):
    text_l = (text or "").lower()
    length = len(text_l.split())
    mod = 0.0

    # Rules for Twitter posts
    if platform == "Twitter":
        if length <= 30: mod += 0.08
        if "#" in text_l or "trending" in text_l: mod += 0.05
        if "!" in text_l: mod += 0.02
        if length > 50: mod -= 0.05

    # Rules for Instagram posts
    if platform == "Instagram":
        if 8 <= length <= 60: mod += 0.07
        if "#" in text_l: mod += 0.07
        if any(w in text_l for w in ["amazing", "fun", "love", "cute"]): mod += 0.04

    # Rules for LinkedIn posts
    if platform == "LinkedIn":
        if length >= 20: mod += 0.08
        if any(w in text_l for w in ["insight", "data", "strategy", "growth"]): mod += 0.06
        if length < 10: mod -= 0.03

    # Rules for YouTube descriptions/titles
    if platform == "YouTube":
        if length >= 40: mod += 0.07
        if any(w in text_l for w in ["how to", "tutorial", "guide", "watch"]): mod += 0.05

    return round(mod, 3)

# This function suggests best posting time for each platform
def suggest_posting_time(platform):
    if platform == "Twitter": return "5-8 PM (Weekdays)"
    if platform == "Instagram": return "6-9 PM (Weekdays)"
    if platform == "LinkedIn": return "8-10 AM (Mornings)"
    if platform == "YouTube": return "5-8 PM (Weekends)"
    return "Anytime"

# This function predicts viral potential for all platforms
def compute_viral_prediction(base_score, text):
    platform_scores = {}
    for p in PLATFORMS:
        mod = platform_modifier(text, p)
        viral = 0.7 * float(base_score) + 0.3 * mod
        viral = max(0.0, min(1.0, viral))
        platform_scores[p] = round(viral, 3)

    best_platform = max(platform_scores, key=lambda k: platform_scores[k])
    return platform_scores, best_platform

# ----- MAIN LOGIC -----

# This function runs prediction analysis on A/B testing results
def run_prediction_coach():
    sheet = connect_sheets()
    ws = safe_get_worksheet(sheet, AB_TAB)
    
    if not ws:
        st.error(f"Tab '{AB_TAB}' not found. Run A/B Testing first.")
        return pd.DataFrame()

    df_ab = pd.DataFrame(ws.get_all_records())
    if df_ab.empty:
        st.warning("No A/B test data found.")
        return pd.DataFrame()

    results = []
    progress_bar = st.progress(0)
    total = len(df_ab)

    for idx, row in df_ab.iterrows():
        # Read A and B variant text safely
        a_text = row.get("A_Text", "") or row.get("Variant A (Original)", "")
        b_text = row.get("B_Text", "") or row.get("Variant B (AI)", "")
        
        # Safely convert scores to float
        try:
            score_a = float(row.get("Score A", 0))
            score_b = float(row.get("Score B", 0))
        except ValueError:
            score_a = 0.5
            score_b = 0.5

        # Predict viral potential for both variants
        p_scores_a, best_plat_a = compute_viral_prediction(score_a, a_text)
        p_scores_b, best_plat_b = compute_viral_prediction(score_b, b_text)

        best_score_a = p_scores_a[best_plat_a]
        best_score_b = p_scores_b[best_plat_b]

        # Decide final recommended variant
        if best_score_a >= best_score_b:
            rec_variant = "A (Original)"
            rec_platform = best_plat_a
            final_text = a_text
            final_score = best_score_a
        else:
            rec_variant = "B (AI)"
            rec_platform = best_plat_b
            final_text = b_text
            final_score = best_score_b
            
        post_time = suggest_posting_time(rec_platform)
        reason = f"Variant {rec_variant} wins (A={best_score_a}, B={best_score_b}) on {rec_platform}"

        # Store final recommendation
        results.append({
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Product": row.get("Product Info", "") or row.get("Product", ""),
            "Winner": rec_variant,
            "Best Platform": rec_platform,
            "Viral Score": final_score,
            "Recommended Time": post_time,
            "Winning Text": final_text,
            "Recommendation_Reason": reason,
            "Score_A_Predicted": best_score_a,
            "Score_B_Predicted": best_score_b
        })
        
        # Update progress bar
        progress_bar.progress((idx + 1) / total)

    return pd.DataFrame(results)

# This function uploads prediction results to Google Sheets
def upload_predictions(sheet, df):
    try:
        try:
            ws = sheet.worksheet(OUTPUT_TAB)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=OUTPUT_TAB, rows="1000", cols="20")
        
        ws.update(values=[df.columns.tolist()] + df.astype(str).values.tolist(), range_name="A1")
        st.toast("Predictions uploaded to Google Sheets!", icon="🚀")
    except Exception as e:
        st.error(f"Upload failed: {e}")

# ----- STREAMLIT UI -----

# App title and description
st.title("🔮 Prediction Coach")
st.markdown("AI-driven advice on where and when to post your winning content.")

# Button to start prediction analysis
if st.button("🚀 Run Prediction Analysis", type="primary"):
    with st.spinner("Analyzing viral potential..."):
        sheet = connect_sheets()
        results_df = run_prediction_coach()
    
    if not results_df.empty:
        # Calculate overall metrics
        avg_viral = results_df["Viral Score"].mean()
        top_platform = results_df["Best Platform"].mode()[0]
        
        col1, col2 = st.columns(2)
        col1.metric("Avg Viral Potential", f"{avg_viral:.2f}/1.0")
        col2.metric("Top Recommended Platform", top_platform)
        
        st.write("### 📢 Strategy Recommendations")
        
        # Show detailed recommendations
        st.dataframe(
            results_df[
                [
                    "Product", 
                    "Score_A_Predicted", "Score_B_Predicted", 
                    "Winner", "Best Platform", "Recommended Time", 
                    "Viral Score", 
                    "Winning Text", "Recommendation_Reason"
                ]
            ],
            column_config={
                "Winning Text": st.column_config.TextColumn("Content", width="medium"),
                "Viral Score": st.column_config.ProgressColumn("Viral Potential", min_value=0, max_value=1),
                "Recommendation_Reason": st.column_config.TextColumn("Why?", width="medium"),
            },
            hide_index=True
        )
        
        # Upload results and notify Slack
        upload_predictions(sheet, results_df)
        send_slack(f"🔮 Prediction Coach finished. Top platform: {top_platform}")
