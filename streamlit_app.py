import streamlit as st
import pandas as pd
import os
from datetime import date

DATA_FILE = "athlete_log.csv"

st.set_page_config(
    page_title="Athlete Tracker",
    layout="wide"
)

st.title("Athlete Daily Tracker")

today = str(date.today())

with st.form("daily_form"):

    st.subheader("Subjective Metrics")

    sessions = st.number_input(
        "Training Sessions",
        0,
        5,
        1
    )

    intensity = st.slider(
        "Training Intensity",
        1,
        10,
        5
    )

    feeling = st.slider(
        "Overall Feeling",
        1,
        10,
        5
    )

    mental = st.slider(
        "Mental Game",
        1,
        10,
        5
    )

    fatigue = st.slider(
        "Physical Fatigue",
        1,
        10,
        5
    )

    confidence = st.slider(
        "Confidence",
        1,
        10,
        5
    )

    focus = st.text_input(
        "Training Focus"
    )

    next_focus = st.text_input(
        "Next Focus"
    )

    notes = st.text_area(
        "Notes"
    )

    submitted = st.form_submit_button(
        "Save Entry"
    )

if submitted:

    row = pd.DataFrame([{
        "Date": today,
        "Sessions": sessions,
        "Intensity": intensity,
        "Feeling": feeling,
        "Mental": mental,
        "Fatigue": fatigue,
        "Confidence": confidence,
        "Focus": focus,
        "NextFocus": next_focus,
        "Notes": notes
    }])

    if os.path.exists(DATA_FILE):
        existing = pd.read_csv(DATA_FILE)
        existing = existing[
            existing["Date"] != today
        ]
        df = pd.concat(
            [existing, row],
            ignore_index=True
        )
    else:
        df = row

    df.to_csv(DATA_FILE, index=False)

    st.success("Saved!")

if os.path.exists(DATA_FILE):

    st.subheader("History")

    df = pd.read_csv(DATA_FILE)

    st.dataframe(df)

    st.line_chart(
        df.set_index("Date")[
            ["Feeling", "Intensity"]
        ]
    )
