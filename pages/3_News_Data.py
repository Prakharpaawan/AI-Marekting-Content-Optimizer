"""
Improved Google News Article Scraper (2025-compatible)
Collects article titles + links + full text.

Writes results into:
 - "Articles" tab in Google Sheets
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
from urllib.parse import urljoin

# ---------- CONFIG ----------
TOPICS = ["digital marketing", "content strategy", "social media trends"]
GOOGLE_SHEET_NAME = "Content Performance Tracker"
TAB_NAME = "Articles"
CREDENTIALS_FILE = "credentials.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


# ---------- SHEETS ----------
def connect_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds).open(GOOGLE_SHEET_NAME)


# ---------- FETCH GOOGLE NEWS RESULTS ----------
def get_google_news_links(topic):
    url = f"https://news.google.com/search?q={topic.replace(' ', '%20')}&hl=en-IN&gl=IN&ceid=IN:en"

    print(f"Fetching: {topic}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    links = set()

    # Common patterns Google News uses
    selectors = [
        "a.JtKRv",
        "a.WwrzSb",
        "a.VDXfz",
        "h3 a",
        "h4 a",
    ]

    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href")
            if not href:
                continue

            # Google News relative links start with "./"
            if href.startswith("./"):
                href = urljoin("https://news.google.com", href[1:])

            title = a.text.strip()

            if title and href.startswith("http"):
                links.add((title, href))

    return list(links)


# ---------- FETCH FULL ARTICLE TEXT ----------
def fetch_article_text(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove unnecessary tags
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()

        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        full_text = " ".join(paragraphs)

        return full_text[:5000] if full_text else ""
    except:
        return ""


# ---------- UPLOAD ----------
def upload_articles(df):
    sheet = connect_sheets()
    try:
        ws = sheet.worksheet(TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=TAB_NAME, rows="5000", cols="20")

    ws.clear()
    ws.update(values=[df.columns.tolist()] + df.values.tolist(), range_name="A1")

    print("Uploaded successfully to Sheets!")


# ---------- MAIN ----------
if __name__ == "__main__":
    all_rows = []

    for topic in TOPICS:
        results = get_google_news_links(topic)
        print(f" - Found {len(results)} articles for this topic")

        for title, link in results:
            text = fetch_article_text(link)
            snippet = text[:200] + "..." if text else title

            all_rows.append({
                "Topic": topic,
                "Title": title,
                "Link": link,
                "Full Article Text": text,
                "Snippet": snippet,
                "Collected At": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            })

            time.sleep(0.5)

    df = pd.DataFrame(all_rows)

    if df.empty:
        print("⚠️ No articles collected. Google may be rate-limiting.")
    else:
        print(f"✅ Collected {len(df)} total articles!")
        upload_articles(df)
