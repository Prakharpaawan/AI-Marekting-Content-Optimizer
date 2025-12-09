import os

import requests
from dotenv import load_dotenv

load_dotenv("secrettt.env")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

def send_slack_message(message):
    """Send a simple text notification to Slack."""
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK_URL, json=payload)
