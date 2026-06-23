import streamlit as st
import pandas as pd
import base64
import requests
from datetime import date
from io import StringIO
import os

# =========================================
# GITHUB CONFIG
# =========================================

# load token from secret / env — DO NOT hardcode in source
GITHUB_TOKEN = "AthleteManager"
REPO = "Liamwolf17/AthleteManagementApp"
FILE_PATH = "athlete_log.csv"
BRANCH = "main"

API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

# =========================================
# FUNCTIONS
# =========================================

def get_existing_csv():
    if not GITHUB_TOKEN:
        st.warning("No GitHub token configured — running in read-only mode.")
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    r = requests.get(API_URL, headers=headers)
    if r.status_code == 200:
        content = r.json().get("content", "")
        decoded = base64.b64decode(content).decode("utf-8")
        return pd.read_csv(StringIO(decoded))
    else:
        # helpful debug info
        st.write(f"GET {API_URL} returned {r.status_code}: {r.text}")
    return pd.DataFrame()


def push_csv_to_github(df):
    if not GITHUB_TOKEN:
        st.error("No GitHub token configured; cannot push to GitHub.")
        return

    csv_data = df.to_csv(index=False)
    b64_content = base64.b64encode(csv_data.encode()).decode()

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Get SHA if file exists
    r = requests.get(API_URL, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"Update athlete log {date.today()}",
        "content": b64_content,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(API_URL, json=payload, headers=headers)
    if r.status_code not in [200, 201]:
        st.error(f"GitHub upload failed ({r.status_code}): {r.text}")
    else:
        st.success("Saved to GitHub!")


# =========================================
# MAIN APP
# =========================================

st.title("Athlete Management App")

# Load existing data
df = get_existing_csv()

# Display current data
if not df.empty:
    st.subheader("Current Athlete Log")
    st.dataframe(df)
else:
    st.info("No athlete log found. Start adding entries below.")

# Add new entry
st.subheader("Add New Entry")
col1, col2, col3 = st.columns(3)
with col1:
    athlete_name = st.text_input("Athlete Name")
with col2:
    entry_date = st.date_input("Date")
with col3:
    performance = st.text_input("Performance/Notes")

if st.button("Add Entry"):
    if athlete_name and performance:
        new_entry = pd.DataFrame([{
            "Athlete": athlete_name,
            "Date": entry_date,
            "Performance": performance
        }])
        df = pd.concat([df, new_entry], ignore_index=True)
        push_csv_to_github(df)
        st.rerun()
    else:
        st.warning("Please fill in all fields.")
