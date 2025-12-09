# AI-Based Automated Content Marketing Optimizer

This project automatically collects and analyzes marketing-related content from **YouTube**, **Reddit**, and **Google News** to help identify trending topics, audience engagement, and performance patterns.  
It uploads all collected data into a single **Google Sheet** called *Content Performance Tracker* for easy visualization and comparison.

---

## 🔍 Overview

| Platform | Purpose | Output Tab in Sheet |
|-----------|----------|---------------------|
| **YouTube** | Fetches top marketing videos, engagement stats, and keywords | YouTube Data |
| **Reddit** | Collects trending marketing posts based on upvotes & comments | Reddit Data |
| **Google News** | Gathers latest marketing-related articles | Articles |

---

## ⚙️ Features
- Automatically gathers and updates marketing data  
- Uses APIs (YouTube, Reddit) and web scraping (Google News)  
- Calculates engagement metrics for better insights  
- Stores data neatly in Google Sheets for tracking and trend analysis  

---

## 🧩 Setup Instructions

### 1. Install Dependencies
All required libraries are listed in the `requirements.txt` file.  
Run this command:
```bash
pip install -r requirements.txt
