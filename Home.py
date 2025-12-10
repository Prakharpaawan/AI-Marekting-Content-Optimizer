import streamlit as st

# Configure the page layout to be wide for a dashboard feel
st.set_page_config(
    page_title="AI Marketing Optimizer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- HEADER SECTION ---
st.title("AI-Based Automated Content Marketing Optimizer")
st.markdown("**Project By:** Prakhar Paawan | **Status:** Active System")
st.divider()

# --- PROJECT STATEMENT ---
st.header("Project Statement")
st.markdown("""
This project develops an advanced AI system that generates and optimizes marketing content 
by analyzing audience engagement and trends to create high-impact campaigns. 

Leveraging Large Language Models (LLMs) like OpenAI GPT and Meta LLaMA for content creation 
and sentiment analysis, the platform integrates with social media APIs, Google Sheets for 
performance metrics, and Slack for team collaboration. It suggests content variations, 
predicts viral potential, and automates A/B testing to maximize ROI on digital campaigns.
""")

st.divider()

# --- STRATEGIC OUTCOMES (Grid Layout) ---
st.header("Key Outcomes")
col1, col2 = st.columns(2)

with col1:
    st.info("**Automated Content Generation**\n\nCreates optimized content variations tailored for maximum engagement.")
    st.info("**Predictive Analytics**\n\nForecasts viral potential and campaign performance before publishing.")

with col2:
    st.info("**Streamlined A/B Testing**\n\nRuns simulations with real-time adjustments to refine strategy.")
    st.info("**Enhanced ROI**\n\nDelivers data-driven insights and precise audience targeting.")

st.divider()

# --- SYSTEM MODULES ---
st.header("System Modules")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown("#### 1. Content Engine")
    st.caption("Generation & Optimization")
    st.markdown("""
    - Creates content using LLMs.
    - Optimizes based on engagement trends.
    """)

with c2:
    st.markdown("#### 2. Sentiment Analysis")
    st.caption("Trend Monitoring")
    st.markdown("""
    - Analyzes audience reactions.
    - Predicts performance via sentiment signals.
    """)

with c3:
    st.markdown("#### 3. Metrics Hub")
    st.caption("Performance Tracking")
    st.markdown("""
    - Tracks metrics in Google Sheets.
    - Sends automated alerts via Slack.
    """)

with c4:
    st.markdown("#### 4. Prediction Coach")
    st.caption("A/B Testing & Forecasting")
    st.markdown("""
    - Runs automated variant tests.
    - Provides strategic campaign recommendations.
    """)

st.divider()

# --- FOOTER / NAVIGATION ---
st.markdown("""
### Navigation Instructions
Select a module from the **sidebar on the left** to begin using the application.
""")

# Simple system check at the bottom
if "gcp_credentials" in st.secrets or os.path.exists("credentials.json"):
    st.success("System Connection: Google Cloud Services Connected")
else:
    st.error("System Connection: Credentials Missing")
