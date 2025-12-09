import streamlit as st
import os
import json
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from urllib.parse import urljoin

# ----- AUTHENTICATION SETUP (Universal Fix) -----
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
TOPICS = ["digital marketing", "content strategy", "social media trends"]
TAB_NAME = "Articles"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# ----- SCRAPING LOGIC -----
@st.cache_data(show_spinner=False)
def fetch_news_data():
    all_rows = []
    
    # Progress UI
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, topic in enumerate(TOPICS):
        status_text.write(f"📰 Searching news for: **{topic}**...")
        url = f"https://news.google.com/search?q={topic.replace(' ', '%20')}&hl=en-IN&gl=IN&ceid=IN:en"
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            links = set()
            # Common patterns Google News uses
            selectors = ["a.JtKRv", "a.WwrzSb", "a.VDXfz", "h3 a", "h4 a"]
            
            for sel in selectors:
                for a in soup.select(sel):
                    href = a.get("href")
                    if not href: continue
                    
                    if href.startswith("./"):
                        href = urljoin("https://news.google.com", href[1:])
                    
                    title = a.text.strip()
                    if title and href.startswith("http"):
                        links.add((title, href))
            
            # Fetch content for found links (limit to 5 per topic for speed)
            for title, link in list(links)[:5]:
                try:
                    art_resp = requests.get(link, headers=HEADERS, timeout=5)
                    art_soup = BeautifulSoup(art_resp.text, "html.parser")
                    
                    # Clean up
                    for tag in art_soup(["script", "style", "header", "footer", "nav"]):
                        tag.decompose()
                        
                    paragraphs = [p.get_text(" ", strip=True) for p in art_soup.find_all("p")]
                    full_text = " ".join(paragraphs)[:5000]
                    snippet = full_text[:200] + "..." if full_text else title
                    
                    all_rows.append({
                        "Topic": topic,
                        "Title": title,
                        "Link": link,
                        "Full Article Text": full_text,
                        "Snippet": snippet,
                        "Collected At": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except:
                    continue # Skip failed articles
                    
        except Exception as e:
            st.warning(f"Error fetching topic {topic}: {e}")
            
        progress_bar.progress((idx + 1) / len(TOPICS))
        time.sleep(0.5)

    status_text.success("✅ News Scraping Complete!")
    return pd.DataFrame(all_rows)

def upload_articles(df):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=TAB_NAME, rows="5000", cols="20")

    ws.clear()
    ws.update(values=[df.columns.tolist()] + df.astype(str).values.tolist(), range_name="A1")
    st.toast("Uploaded articles to Google Sheets!", icon="🚀")

# ----- STREAMLIT UI -----
st.title("📰 Industry News Tracker")
st.markdown("Scrape the latest articles from Google News for your marketing topics.")

col1, col2 = st.columns(2)
with col1:
    st.info(f"**Topics:** {', '.join(TOPICS)}")
with col2:
    if st.button("🚀 Start Scraping News", type="primary"):
        with st.spinner("Fetching latest articles..."):
            news_df = fetch_news_data()
            
            if not news_df.empty:
                st.write(f"### 📄 Found {len(news_df)} Articles")
                st.dataframe(news_df[["Topic", "Title", "Snippet"]].head(10))
                upload_articles(news_df)
            else:
                st.warning("No articles found. Google might be rate-limiting.")
