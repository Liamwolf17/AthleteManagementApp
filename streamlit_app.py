import streamlit as st
import pandas as pd
import base64
import requests
from datetime import date

# =========================================
# GITHUB CONFIG
# =========================================

GITHUB_TOKEN = "AthleteManager"
REPO = "Liamwolf17/AthleteManagementApp"
FILE_PATH = "athlete_log.csv"
BRANCH = "main"

API_URL = f"https://api.github.com/repos/{AthleteManagementApp}/contents/{athlete_log.csv}"

# =========================================
# FUNCTIONS
# =========================================

def get_existing_csv():

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}"
    }

    r = requests.get(API_URL, headers=headers)

    if r.status_code == 200:

        content = r.json()["content"]
        decoded = base64.b64decode(content).decode("utf-8")

        return pd.read_csv(pd.compat.StringIO(decoded))

    return pd.DataFrame()


def push_csv_to_github(df):

    csv_data = df.to_csv(index=False)

    b64_content = base64.b64encode(
        csv_data.encode()
    ).decode()

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Get SHA if file exists
    r = requests.get(API_URL, headers=headers)

    sha = None
    if r.status_code == 200:
        sha = r.json()["sha"]

    payload = {
        "message": f"Update athlete log {date.today()}",
        "content": b64_content,
        "branch": BRANCH
    }

    if sha:
        payload["sha"] = sha

    r = requests.put(API_URL, json=payload, headers=headers)

    if r.status_code not in [200, 201]:
        st.error(f"GitHub upload failed: {r.text}")
    else:
        st.success("Saved to GitHub!")

# =========================================
# UI
# =========================================

st.title("Athlete Tracker (GitHub Sync)")

today = str(date.today())

with st.form("daily_form"):

    sessions = st.number_input("Training Sessions", 0, 5, 1)
    intensity = st.slider("Intensity", 1, 10, 5)
    feeling = st.slider("Feeling", 1, 10, 5)
    mental = st.slider("Mental Game", 1, 10, 5)
    fatigue = st.slider("Fatigue", 1, 10, 5)
    confidence = st.slider("Confidence", 1, 10, 5)

    focus = st.text_input("Training Focus")
    next_focus = st.text_input("Next Focus")

    submitted = st.form_submit_button("Save")

if submitted:

    new_row = pd.DataFrame([{
        "Date": today,
        "Sessions": sessions,
        "Intensity": intensity,
        "Feeling": feeling,
        "Mental": mental,
        "Fatigue": fatigue,
        "Confidence": confidence,
        "Focus": focus,
        "NextFocus": next_focus
    }])

    df = get_existing_csv()

    if "Date" in df.columns:
        df = df[df["Date"] != today]

    df = pd.concat([df, new_row], ignore_index=True)

    push_csv_to_github(df)

# =========================================
# DISPLAY
# =========================================

df = get_existing_csv()

if not df.empty:
    st.dataframe(df)
    st.line_chart(df.set_index("Date")[["Feeling", "Intensity", "Fatigue"]])
