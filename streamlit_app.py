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


def push_csv_to_github(df, entry_date_str):

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
        "message": f"Update athlete log {entry_date_str}",
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
def get_garmin_data(target_date: date):

    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        return {}, {}

    debug = {}

    try:
        from garminconnect import Garmin

        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()

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

        # Intensity minutes come straight out of the same daily stats
        # payload, no extra API call needed. Garmin counts vigorous
        # minutes double toward the weekly intensity minutes goal.
        moderate_min = stats.get("moderateIntensityMinutes")
        vigorous_min = stats.get("vigorousIntensityMinutes")

        garmin["ModerateIntensityMinutes"] = moderate_min
        garmin["VigorousIntensityMinutes"] = vigorous_min
        garmin["TotalIntensityMinutes"] = (moderate_min or 0) + (vigorous_min or 0) * 2

        # -------------------------
        # Optional Metrics
        # -------------------------

        try:
            sleep_score = (
                (sleep_dto.get("sleepScores") or {})
                .get("overall", {})
                .get("value")
            )

            if sleep_score is not None:
                garmin["SleepScore"] = sleep_score
            else:
                debug["SleepScore"] = (
                    "No sleep score in response — only devices with advanced "
                    "sleep tracking report this, and it may not be ready yet "
                    "for that night's sleep."
                )

        except Exception as e:
            debug["SleepScore"] = f"{type(e).__name__}: {e}"

        try:
            stress = client.get_stress_data(date_str)

            # Garmin computes an overall daily stress score itself — prefer
            # that directly rather than deriving our own average/max. The
            # exact key name has varied a bit across accounts and library
            # versions (overallStressLevel / avgStressLevel), so check both.
            raw_score = stress.get("overallStressLevel")
            if raw_score in (None, -1):
                raw_score = stress.get("avgStressLevel")

            if raw_score not in (None, -1):
                garmin["StressScore"] = raw_score
            else:
                # Fall back to averaging the raw per-minute readings only if
                # Garmin didn't supply a precomputed score for this date.
                stress_values = [
                    x for x in stress.get("stressValuesArray", [])
                    if isinstance(x, (int, float)) and x >= 0
                ]

                if stress_values:
                    garmin["StressScore"] = round(sum(stress_values) / len(stress_values))
                    debug["Stress"] = (
                        "Garmin didn't return a precomputed daily stress score for "
                        "this date, so this is an average of the raw readings instead."
                    )
                else:
                    debug["Stress"] = (
                        "Call succeeded but returned no valid (non -1) readings "
                        "for this date — device may not have synced stress data yet."
                    )

        except Exception as e:
            debug["Stress"] = f"{type(e).__name__}: {e}"

        try:
            body_battery_data = client.get_body_battery(date_str)

            # API returns a list of entries (one per day in the queried range)
            if isinstance(body_battery_data, list) and body_battery_data:
                body_battery_data = body_battery_data[0]

            raw_values = (
                body_battery_data.get("bodyBatteryValuesArray", [])
                if isinstance(body_battery_data, dict)
                else []
            )

            values = []

            for entry in raw_values:
                # entries may be plain numbers or [timestamp, value] pairs
                v = entry[-1] if isinstance(entry, (list, tuple)) and entry else entry
                if isinstance(v, (int, float)):
                    values.append(v)

            if values:
                garmin["BodyBatteryStart"] = values[0]
                garmin["BodyBatteryEnd"] = values[-1]
            else:
                shape_info = (
                    list(body_battery_data.keys())
                    if isinstance(body_battery_data, dict)
                    else type(body_battery_data).__name__
                )
                debug["BodyBattery"] = (
                    f"Got a response but no usable numeric values found. "
                    f"Response shape: {shape_info}"
                )

        except Exception as e:
            debug["BodyBattery"] = f"{type(e).__name__}: {e}"

        # VO2 Max lives under get_max_metrics(), not get_user_summary().
        # Real response shape: {"generic": {"vo2MaxValue": 44.0, ...}, "cycling": {...}}
        # NOTE: this endpoint is known to sometimes return the *latest* VO2max
        # regardless of the date_str you pass in, rather than a true historical
        # value for that specific day — treat backfilled VO2Max with caution.
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
# ENTRY DATE SELECTION (backfill support)
# =====================================================

entry_date_obj = st.date_input(
    "Which day are you logging?",
    value=date.today(),
    max_value=date.today()
)
entry_date_str = str(entry_date_obj)

days_back = (date.today() - entry_date_obj).days

if days_back == 0:
    date_choice = "Today"
elif days_back == 1:
    date_choice = "Yesterday"
else:
    date_choice = entry_date_obj.strftime("%A, %B %d")

if days_back != 0:
    st.caption(
        f"Backfilling **{entry_date_str}**. Garmin metrics below are pulled "
        f"for that specific date — most fields honor this, but VO2Max can "
        f"lag or return the most recent value regardless of date (see debug panel)."
    )

# =====================================================
# PLANNED FOCUS (reminder from the day before the entry date)
# =====================================================

st.header(f"🎯 Planned Focus for {date_choice}")

if not df.empty:

    try:
        temp_df = df.copy()
        temp_df["Date"] = pd.to_datetime(temp_df["Date"])

        prior_day = entry_date_obj - timedelta(days=1)

        prior_entry = temp_df[temp_df["Date"].dt.date == prior_day]

        if not prior_entry.empty:
            st.info(prior_entry.iloc[0]["TomorrowsFocus"])
        else:
            st.info("No focus recorded.")

    except Exception:
        pass

# =====================================================
# GARMIN METRICS
# =====================================================

st.header(f"⌚ Garmin Metrics — {date_choice} ({entry_date_str})")

header_col, button_col = st.columns([5, 1])

with button_col:
    if st.button("🔄 Refresh", help="Force a fresh pull from Garmin (bypasses the 1-hour cache)"):
        get_garmin_data.clear()
        st.rerun()

garmin, garmin_debug = get_garmin_data(entry_date_obj)

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
        st.metric("Sleep Score", garmin.get("SleepScore", "-"))

    with c6:
        st.metric("Intensity Minutes", garmin.get("TotalIntensityMinutes", "-"))

    with c7:
        st.metric("Activities Logged", garmin.get("NumActivities", "-"))

    with c8:
        st.metric("Activity Duration (min)", garmin.get("ActivityDurationMin", "-"))

    if garmin.get("ActivityNames"):
        st.caption(f"Activities: {garmin['ActivityNames']}")

else:
    st.info("No Garmin data loaded yet — fill in the fields manually below, or hit Refresh once Garmin is set up.")

if garmin_debug:
    with st.expander("🔧 Garmin debug info (why some fields may be blank)"):
        for key, msg in garmin_debug.items():
            st.caption(f"**{key}**: {msg}")

# =====================================================
# DAILY TRAINING FORM
# =====================================================

st.header("📝 Daily Training Log")

st.write("Session Type")
scol1, scol2 = st.columns(2)
with scol1:
    gym_session = st.checkbox("Gym")
with scol2:
    training_session = st.checkbox("Training")

only_gym = gym_session and not training_session

if only_gym:
    st.caption(
        "Gym-only session — hiding the mental game, what worked/didn't, and "
        "tomorrow's focus fields below, since those are aimed at technical/tactical "
        "training days."
    )

with st.form("training_log"):

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

    # Mental Game: integer score + short text note (skipped for gym-only days)
    if not only_gym:
        mental_game = st.number_input(
            "Mental Game (score)",
            min_value=1, max_value=10, value=5, step=1, format="%d"
        )
        mental_game_notes = st.text_input("Mental Game Notes")
    else:
        mental_game = None
        mental_game_notes = ""

    intensity = st.slider("Training Intensity", 1, 10, 5)

    focus = st.text_input("Today's Focus")

    if not only_gym:
        worked_well = st.text_area("What Worked Well?")
        didnt_work = st.text_area("What Didn't Work?")
        tomorrows_focus = st.text_area("Tomorrow's Focus")
    else:
        worked_well = ""
        didnt_work = ""
        tomorrows_focus = ""

    st.markdown("---")
    st.subheader("⌚ Garmin Data")
    st.caption(
        "Auto-filled from Garmin above. Edit any field below to correct it or "
        "fill it in by hand if the sync missed it."
    )


    gcol1, gcol2, gcol3, gcol4 = st.columns(4)

    with gcol1:
        m_steps = st.number_input(
            "Steps", min_value=0, step=1,
            value=int(garmin.get("Steps") or 0)
        )
        m_distance = st.number_input(
            "Distance (m)", min_value=0.0,
            value=float(garmin.get("Distance") or 0.0)
        )

    with gcol2:
        m_calories = st.number_input(
            "Calories", min_value=0, step=1,
            value=int(garmin.get("Calories") or 0)
        )
        m_resting_hr = st.number_input(
            "Resting HR", min_value=0, step=1,
            value=int(garmin.get("RestingHR") or 0)
        )

    with gcol3:
        m_sleep_hours = st.number_input(
            "Sleep Hours", min_value=0.0, step=0.1, format="%.2f",
            value=float(garmin.get("SleepHours") or 0.0)
        )
        m_vo2max = st.number_input(
            "VO2 Max", min_value=0.0, step=0.1,
            value=float(garmin.get("VO2Max") or 0.0)
        )
        m_sleep_score = st.number_input(
            "Sleep Score", min_value=0, max_value=100, step=1,
            value=int(garmin.get("SleepScore") or 0)
        )

    with gcol4:
        m_stress_score = st.number_input(
            "Stress Score", min_value=0.0,
            value=float(garmin.get("StressScore") or 0.0)
        )

    gcol5, gcol6, gcol7, gcol8 = st.columns(4)

    with gcol5:
        m_bb_start = st.number_input(
            "Body Battery Start", min_value=0, max_value=100, step=1,
            value=int(garmin.get("BodyBatteryStart") or 0)
        )

    with gcol6:
        m_bb_end = st.number_input(
            "Body Battery End", min_value=0, max_value=100, step=1,
            value=int(garmin.get("BodyBatteryEnd") or 0)
        )

    with gcol7:
        m_num_activities = st.number_input(
            "Num Activities", min_value=0, step=1,
            value=int(garmin.get("NumActivities") or 0)
        )

    with gcol8:
        m_activity_duration = st.number_input(
            "Activity Duration (min)", min_value=0.0,
            value=float(garmin.get("ActivityDurationMin") or 0.0)
        )

    gcol9, gcol10 = st.columns(2)

    with gcol9:
        m_moderate_intensity = st.number_input(
            "Moderate Intensity Min", min_value=0, step=1,
            value=int(garmin.get("ModerateIntensityMinutes") or 0)
        )

    with gcol10:
        m_vigorous_intensity = st.number_input(
            "Vigorous Intensity Min", min_value=0, step=1,
            value=int(garmin.get("VigorousIntensityMinutes") or 0)
        )

    m_activity_distance = st.number_input(
        "Activity Distance (km)", min_value=0.0,
        value=float(garmin.get("ActivityDistanceKm") or 0.0)
    )
    m_activity_names = st.text_input(
        "Activity Names", value=garmin.get("ActivityNames") or ""
    )

    submitted = st.form_submit_button("Save Entry")

# =====================================================
# SAVE ENTRY
# =====================================================

if submitted:

    gym_bool = bool(gym_session)
    training_bool = bool(training_session)

    new_entry = pd.DataFrame([{

        "Date": entry_date_str,
        "Gym": gym_bool,
        "Training": training_bool,

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

        # Garmin fields below come from the form inputs, which are
        # pre-filled from the Garmin auto-sync but can be overridden
        # or filled in manually if the sync failed.
        "Steps": m_steps,
        "Distance": m_distance,
        "Calories": m_calories,
        "RestingHR": m_resting_hr,
        "SleepHours": m_sleep_hours,
        "SleepScore": m_sleep_score,
        "StressScore": m_stress_score,
        "BodyBatteryStart": m_bb_start,
        "BodyBatteryEnd": m_bb_end,
        "VO2Max": m_vo2max,
        "ModerateIntensityMinutes": m_moderate_intensity,
        "VigorousIntensityMinutes": m_vigorous_intensity,
        "TotalIntensityMinutes": m_moderate_intensity + (m_vigorous_intensity * 2),

        "NumActivitiesGarmin": m_num_activities,
        "ActivityDurationMin": m_activity_duration,
        "ActivityDistanceKm": m_activity_distance,
        "ActivityNames": m_activity_names,
    }])

    if not df.empty:
        df = df[df["Date"] != entry_date_str]

    df = pd.concat([df, new_entry], ignore_index=True)

    if push_csv_to_github(df, entry_date_str):
        st.success(f"Entry saved for {entry_date_str} ({date_choice})!")
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

        for col in ["SleepHours", "RestingHR"]:
            if col in plot_df:
                cols.append(col)

        if cols:
            st.line_chart(plot_df.set_index("Date")[cols])

    st.subheader("Training History")

    st.dataframe(
        plot_df.sort_values("Date", ascending=False)
    )
