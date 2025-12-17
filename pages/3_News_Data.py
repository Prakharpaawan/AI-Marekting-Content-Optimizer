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

# This function connects the app to Google Sheets.
# It works both on Streamlit Cloud and on a local system.
def connect_sheets():
    """Connect to Google Sheets using Cloud Secrets OR Local JSON (Robust Path Check)"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # First try to read Google credentials from Streamlit Cloud secrets
    try:
        if hasattr(st, "secrets") and "gcp_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_credentials"])
            
            # Fix private key formatting if required
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
        # Stop the app if credentials file is missing
        st.error("❌ Critical Error: credentials.json not found in current or parent directory.")
        st.stop()
        
    client = gspread.authorize(creds)
    return client.open("Content Performance Tracker")

# ----- CONFIG -----

# Topics to search on Google News
TOPICS = ["digital marketing", "content strategy", "social media trends"]

# Google Sheets tab name
TAB_NAME = "Articles"

# Headers used to avoid being blocked while scraping
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# ----- SCRAPING LOGIC -----

# This function scrapes news articles related to the given topics.
# Streamlit cache is used to avoid repeated scraping.
@st.cache_data(show_spinner=False)
def fetch_news_data():
    all_rows = []
    
    # UI elements to show progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Loop through each topic
    for idx, topic in enumerate(TOPICS):
        status_text.write(f"📰 Searching news for: **{topic}**...")
        
        # Google News search URL
        url = f"https://news.google.com/search?q={topic.replace(' ', '%20')}&hl=en-IN&gl=IN&ceid=IN:en"
        
        try:
            # Fetch Google News search results page
            resp = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            links = set()
            
            # Different HTML patterns used by Google News
            selectors = ["a.JtKRv", "a.WwrzSb", "a.VDXfz", "h3 a", "h4 a"]
            
            # Extract article links and titles
            for sel in selectors:
                for a in soup.select(sel):
                    href = a.get("href")
                    if not href: 
                        continue
                    
                    # Convert relative URLs to full URLs
                    if href.startswith("./"):
                        href = urljoin("https://news.google.com", href[1:])
                    
                    title = a.text.strip()
                    if title and href.startswith("http"):
                        links.add((title, href))
            
            # Fetch article content (limited for performance)
            for title, link in list(links)[:5]:
                try:
                    art_resp = requests.get(link, headers=HEADERS, timeout=5)
                    art_soup = BeautifulSoup(art_resp.text, "html.parser")
                    
                    # Remove unnecessary tags
                    for tag in art_soup(["script", "style", "header", "footer", "nav"]):
                        tag.decompose()
                        
                    # Extract text from paragraph tags
                    paragraphs = [p.get_text(" ", strip=True) for p in art_soup.find_all("p")]
                    full_text = " ".join(paragraphs)[:5000]
                    
                    # Short preview of the article
                    snippet = full_text[:200] + "..." if full_text else title
                    
                    # Store article data
                    all_rows.append({
                        "Topic": topic,
                        "Title": title,
                        "Link": link,
                        "Full Article Text": full_text,
                        "Snippet": snippet,
                        "Collected At": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except:
                    continue # Skip articles that fail to load
                    
        except Exception as e:
            st.warning(f"Error fetching topic {topic}: {e}")
            
        # Update progress bar
        progress_bar.progress((idx + 1) / len(TOPICS))
        time.sleep(0.5)

    status_text.success("✅ News Scraping Complete!")
    return pd.DataFrame(all_rows)

# This function uploads scraped articles to Google Sheets
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

# App title and description
st.title("📰 Industry News Tracker")
st.markdown("Scrape the latest articles from Google News for your marketing topics.")

# Create two columns in the UI
col1, col2 = st.columns(2)
with col1:
    st.info(f"**Topics:** {', '.join(TOPICS)}")
with col2:
    # Button to start scraping news
    if st.button("🚀 Start Scraping News", type="primary"):
        with st.spinner("Fetching latest articles..."):
            news_df = fetch_news_data()
            
            if not news_df.empty:
                st.write(f"### 📄 Found {len(news_df)} Articles")
                st.dataframe(news_df[["Topic", "Title", "Snippet"]].head(10))
                upload_articles(news_df)
            else:
                st.warning("No articles found. Google might be rate-limiting.")
