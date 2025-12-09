import streamlit as st

# Configure the page title and icon
st.set_page_config(
    page_title="AI Marketing Optimizer",
    page_icon="🚀",
    layout="centered"
)

# Main Title
st.title("🚀 AI Content Marketing Optimizer")

# Introduction Logic
st.markdown("""
---
### 📌 Welcome to the Dashboard
This application uses Artificial Intelligence to automate the entire lifecycle of marketing content. 

**👈 Select a module from the sidebar to get started.**

#### 🛠️ Available Modules:

* **📥 Data Collection**: Scrape real-time trends from **YouTube**, **Reddit**, and **Google News**.
* **🤖 Content Studio**: 
    * **Generator**: Create AI posts for Twitter, LinkedIn, and Instagram.
    * **Optimizer**: Refine content for better engagement using trends.
* **📊 Analysis & Strategy**:
    * **Sentiment Analysis**: Understand how the audience feels.
    * **A/B Testing**: Simulate campaign variations (Variant A vs. Variant B).
    * **Prediction Coach**: Get AI recommendations on where and when to post.
    * **Performance Metrics**: View the final summary report.

---
**Status:** ✅ System Online | 🔐 Connected to Google Sheets
""")

# Optional: Add a simple image or success message to show it loaded
st.success("System Ready. Please navigate using the sidebar menu on the left.")
