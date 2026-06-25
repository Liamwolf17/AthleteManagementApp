import streamlit as st
import pandas as pd
import base64
import requests
from datetime import date, timedelta
from io import StringIO

# =====================================================
# CONFIG
# =====================================================

st.set_page_config(
    page_title="Athlete Management App",
    layout="wide"
)

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")

REPO = "Liamwolf17/AthleteManagementApp"
FILE_PATH = "athlete_log.csv"
BRANCH = "main"

API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

# Garmin Credentials
GARMIN_EMAIL = st.secrets.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = st.secrets.get("GARMIN_PASSWORD", "")

# =====================================================
# GITHUB FUNCTIONS
# =====================================================

def get_existing_csv():

    headers = {}

    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    r = requests.get(API_URL, headers=headers)

    if r.status_code == 200:

        content = r.json().get("content", "")
        decoded = base64.b64decode(content).decode("utf-8")

        try:
            return pd.read_csv(StringIO(decoded))
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    return pd.DataFrame()


def push_csv_to_github(df):

    if not GITHUB_TOKEN:
        st.error("No GitHub token configured.")
        return False

    csv_data = df.to_csv(index=False)
    b64_content = base64.b64encode(csv_data.encode()).decode()

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    sha = None
    r = requests.get(API_URL, headers=headers)

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
        st.error(f"GitHub upload failed:\n{r.text}")
        return False

    return True


# =====================================================
# GARMIN FUNCTIONS
# =====================================================

@st.cache_data(ttl=3600)
def get_garmin_data():

    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        return {}, {}

    debug = {}

    try:
        from garminconnect import Garmin

        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()

        target_date = date.today()
        date_str = target_date.strftime("%Y-%m-%d")

        stats = client.get_stats(date_str)
        sleep = client.get_sleep_data(date_str)

        sleep_dto = sleep.get("dailySleepDTO", {})
        sleep_seconds = sleep_dto.get("sleepTimeSeconds") or 0

        garmin = {
            "Steps": stats.get("totalSteps"),
            "Distance": stats.get("totalDistance"),
            "Calories": stats.get("totalKilocalories"),
            "RestingHR": stats.get("restingHeartRate"),
            "SleepHours": round(sleep_seconds / 3600, 2),
        }

        # -------------------------
        # Optional Metrics
        # -------------------------

        try:
            stress = client.get_stress_data(date_str)

            stress_values = [
                x for x in stress.get("stressValuesArray", [])
                if isinstance(x, (int, float)) and x >= 0
            ]

            if stress_values:
                garmin["AvgStress"] = sum(stress_values) / len(stress_values)
                garmin["MaxStress"] = max(stress_values)
            else:
                debug["Stress"] = (
                    "Call succeeded but returned no valid (non -1) readings "
                    "for this date — device may not have synced stress data yet."
                )

        except Exception as e:
            debug["Stress"] = f"{type(e).__name__}: {e}"

        try:
            body_battery = client.get_body_battery(date_str)

            values = [
                x for x in body_battery.get("bodyBatteryValuesArray", [])
                if isinstance(x, (int, float))
            ]

            if values:
                garmin["BodyBatteryStart"] = values[0]
                garmin["BodyBatteryEnd"] = values[-1]
            else:
                debug["BodyBattery"] = "Call succeeded but returned no values for this date."

        except Exception as e:
            debug["BodyBattery"] = f"{type(e).__name__}: {e}"

        # VO2 Max lives under get_max_metrics(), not get_user_summary().
        # Real response shape: {"generic": {"vo2MaxValue": 44.0, ...}, "cycling": {...}}
        try:
            max_metrics = client.get_max_metrics(date_str)
            generic = (max_metrics or {}).get("generic") or {}

            if generic.get("vo2MaxValue") is not None:
                garmin["VO2Max"] = generic.get("vo2MaxValue")
            else:
                debug["VO2Max"] = (
                    "No vo2MaxValue in response — this endpoint is known to "
                    "return empty/'latest' data inconsistently for some accounts "
                    "and library versions, and only updates after a qualifying "
                    "run or ride."
                )

        except Exception as e:
            debug["VO2Max"] = f"{type(e).__name__}: {e}"

        # -------------------------
        # Training Readiness
        # -------------------------

        try:
            readiness = client.get_training_readiness(date_str)

            # API returns a list of records; most recent entry is what we want
            if isinstance(readiness, list) and readiness:
                readiness = readiness[0]

            if isinstance(readiness, dict) and readiness:
                garmin["TrainingReadiness"] = readiness.get("score")
                garmin["TrainingReadinessLevel"] = readiness.get("level")
            else:
                debug["TrainingReadiness"] = (
                    "Empty response — your device/account may not support "
                    "Training Readiness (requires a compatible newer Garmin watch)."
                )

        except Exception as e:
            debug["TrainingReadiness"] = f"{type(e).__name__}: {e}"

        # -------------------------
        # Heart Rate Variability (overnight)
        # -------------------------

        try:
            hrv = client.get_hrv_data(date_str)
            hrv_summary = (hrv or {}).get("hrvSummary", {})

            if hrv_summary:
                garmin["HRVLastNight"] = hrv_summary.get("lastNightAvg")
                garmin["HRVWeeklyAvg"] = hrv_summary.get("weeklyAvg")
                garmin["HRVStatus"] = hrv_summary.get("status")
            else:
                debug["HRV"] = (
                    "Empty response — your device/account may not support "
                    "HRV Status (requires a compatible newer Garmin watch)."
                )

        except Exception as e:
            debug["HRV"] = f"{type(e).__name__}: {e}"

        # -------------------------
        # Activities Actually Logged on the Watch
        # -------------------------

        try:
            activities = client.get_activities_by_date(date_str, date_str)

            if activities:
                garmin["NumActivities"] = len(activities)

                garmin["ActivityDurationMin"] = round(
                    sum((a.get("duration") or 0) for a in activities) / 60,
                    1
                )

                garmin["ActivityDistanceKm"] = round(
                    sum((a.get("distance") or 0) for a in activities) / 1000,
                    2
                )

                names = []

                for a in activities:
                    name = a.get("activityName")
                    if not name:
                        name = a.get("activityType", {}).get("typeKey", "Activity")
                    names.append(name)

                garmin["ActivityNames"] = ", ".join(names)

        except Exception as e:
            debug["Activities"] = f"{type(e).__name__}: {e}"

        return garmin, debug

    except Exception as e:
        st.warning(f"Garmin sync failed: {e}")
        return {}, {"_login_or_setup": f"{type(e).__name__}: {e}"}


# =====================================================
# LOAD DATA
# =====================================================

df = get_existing_csv()

# =====================================================
# HEADER
# =====================================================

st.title("🏆 Athlete Management App")

# =====================================================
# YESTERDAY'S FOCUS
# =====================================================

st.header("🎯 Yesterday's Focus")

if not df.empty:

    try:
        temp_df = df.copy()
        temp_df["Date"] = pd.to_datetime(temp_df["Date"])

        yesterday = (pd.Timestamp.today() - pd.Timedelta(days=1)).date()

        yest = temp_df[temp_df["Date"].dt.date == yesterday]

        if not yest.empty:
            st.info(yest.iloc[0]["TomorrowsFocus"])
        else:
            st.info("No focus recorded.")

    except:
        pass

# =====================================================
# GARMIN METRICS
# =====================================================

st.header("⌚ Garmin Metrics")

garmin, garmin_debug = get_garmin_data()

if garmin:

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("Steps", garmin.get("Steps", "-"))

    with c2:
        sleep_hours = garmin.get("SleepHours")
        st.metric("Sleep Hours", round(sleep_hours, 1) if sleep_hours else "-")

    with c3:
        st.metric("Resting HR", garmin.get("RestingHR", "-"))

    with c4:
        st.metric("Calories", garmin.get("Calories", "-"))

    c5, c6, c7, c8 = st.columns(4)

    with c5:
        st.metric(
            "Training Readiness",
            garmin.get("TrainingReadiness", "-"),
            help=garmin.get("TrainingReadinessLevel")
        )

    with c6:
        st.metric(
            "HRV (last night)",
            garmin.get("HRVLastNight", "-"),
            help=garmin.get("HRVStatus")
        )

    with c7:
        st.metric("Activities Logged", garmin.get("NumActivities", "-"))

    with c8:
        st.metric("Activity Duration (min)", garmin.get("ActivityDurationMin", "-"))

    if garmin.get("ActivityNames"):
        st.caption(f"Activities: {garmin['ActivityNames']}")

if garmin_debug:
    with st.expander("🔧 Garmin debug info (why some fields may be blank)"):
        for key, msg in garmin_debug.items():
            st.caption(f"**{key}**: {msg}")

# =====================================================
# DAILY TRAINING FORM
# =====================================================

st.header("📝 Daily Training Log")

with st.form("training_log"):

    num_sessions = st.number_input("Number of Sessions", 0, 10, 1)

    # Feel Before: integer score + short text note
    feel_before = st.number_input(
        "Feel Before Training (score)",
        min_value=1, max_value=10, value=5, step=1, format="%d"
    )
    feel_before_notes = st.text_input("Feel Before Notes")

    # Feel After: integer score + short text note
    feel_after = st.number_input(
        "Feel After Training (score)",
        min_value=1, max_value=10, value=5, step=1, format="%d"
    )
    feel_after_notes = st.text_input("Feel After Notes")

    # Mental Game: integer score + short text note
    mental_game = st.number_input(
        "Mental Game (score)",
        min_value=1, max_value=10, value=5, step=1, format="%d"
    )
    mental_game_notes = st.text_input("Mental Game Notes")

    intensity = st.slider("Training Intensity", 1, 10, 5)

    focus = st.text_input("Today's Focus")
    worked_well = st.text_area("What Worked Well?")
    didnt_work = st.text_area("What Didn't Work?")
    tomorrows_focus = st.text_area("Tomorrow's Focus")

    submitted = st.form_submit_button("Save Entry")

# =====================================================
# SAVE ENTRY
# =====================================================

if submitted:

    new_entry = pd.DataFrame([{

        "Date": str(date.today()),
        "NumSessions": num_sessions,

        "FeelBefore": feel_before,
        "FeelBeforeNotes": feel_before_notes,

        "FeelAfter": feel_after,
        "FeelAfterNotes": feel_after_notes,

        "MentalGame": mental_game,
        "MentalGameNotes": mental_game_notes,

        "Intensity": intensity,
        "Focus": focus,
        "WorkedWell": worked_well,
        "DidntWork": didnt_work,
        "TomorrowsFocus": tomorrows_focus,

        "Steps": garmin.get("Steps"),
        "Distance": garmin.get("Distance"),
        "Calories": garmin.get("Calories"),
        "RestingHR": garmin.get("RestingHR"),
        "SleepHours": garmin.get("SleepHours"),
        "AvgStress": garmin.get("AvgStress"),
        "MaxStress": garmin.get("MaxStress"),
        "BodyBatteryStart": garmin.get("BodyBatteryStart"),
        "BodyBatteryEnd": garmin.get("BodyBatteryEnd"),
        "VO2Max": garmin.get("VO2Max"),

        "TrainingReadiness": garmin.get("TrainingReadiness"),
        "TrainingReadinessLevel": garmin.get("TrainingReadinessLevel"),

        "HRVLastNight": garmin.get("HRVLastNight"),
        "HRVWeeklyAvg": garmin.get("HRVWeeklyAvg"),
        "HRVStatus": garmin.get("HRVStatus"),

        "NumActivitiesGarmin": garmin.get("NumActivities"),
        "ActivityDurationMin": garmin.get("ActivityDurationMin"),
        "ActivityDistanceKm": garmin.get("ActivityDistanceKm"),
    }])

    if not df.empty:
        df = df[df["Date"] != str(date.today())]

    df = pd.concat([df, new_entry], ignore_index=True)

    if push_csv_to_github(df):
        st.success("Entry saved!")
        st.rerun()

# =====================================================
# DASHBOARD
# =====================================================

if not df.empty:

    st.header("📈 Performance Trends")

    plot_df = df.copy()
    plot_df["Date"] = pd.to_datetime(plot_df["Date"])
    plot_df = plot_df.sort_values("Date")

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Feeling Trends")

        st.line_chart(
            plot_df.set_index("Date")[[
                "FeelBefore", "FeelAfter", "MentalGame"
            ]]
        )

    with c2:
        st.subheader("Recovery Trends")

        cols = []

        for col in ["SleepHours", "RestingHR", "HRVLastNight", "TrainingReadiness"]:
            if col in plot_df:
                cols.append(col)

        if cols:
            st.line_chart(plot_df.set_index("Date")[cols])

    st.subheader("Training History")

    st.dataframe(
        plot_df.sort_values("Date", ascending=False)
    )
