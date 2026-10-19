"""
Pipeline A: Automated Garmin Connect -> Supabase Daily Biometric Sync
Fetches the past 7 days of Garmin Connect metrics and upserts them into Supabase.
"""
import os
import json
import time
import base64
import tempfile
from datetime import datetime, timedelta
import pytz
import requests
from garminconnect import Garmin

# Auto-clean environment variables
RAW_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_URL = RAW_URL.split("/rest/v1")[0].rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "").strip()
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "").strip()
GARMIN_TOKEN_B64 = os.environ.get("GARMIN_TOKEN_BASE64", "").strip()
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "7"))


def validate_env():
    if not SUPABASE_URL.startswith("https://") or ".supabase.co" not in SUPABASE_URL:
        raise ValueError(f"SUPABASE_URL looks invalid: '{RAW_URL}'")
    if not SUPABASE_KEY:
        raise ValueError("SUPABASE_SERVICE_KEY is missing in GitHub Secrets.")


def login_garmin() -> Garmin:
    if GARMIN_TOKEN_B64:
        print("Restoring Garmin session from GARMIN_TOKEN_BASE64...")
        token_dir = tempfile.mkdtemp()
        raw_json = base64.b64decode(GARMIN_TOKEN_B64).decode("utf-8")
        data = json.loads(raw_json)
        for fname, content in data.items():
            with open(os.path.join(token_dir, fname), "w") as f:
                json.dump(content, f)
        client = Garmin()
        client.login(token_dir)
        return client

    print("Authenticating with Garmin Connect via email/password...")
    for attempt in range(1, 4):
        try:
            client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
            client.login()
            return client
        except Exception as e:
            print(f"Login attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(attempt * 15)
            else:
                raise RuntimeError("Garmin rate limited (429).") from e


def upsert_to_supabase(row: dict):
    endpoint = f"{SUPABASE_URL}/rest/v1/garmin_daily_metrics?on_conflict=date"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    resp = requests.post(endpoint, headers=headers, json=row, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Supabase error ({resp.status_code}): {resp.text}")


def sync_metrics():
    validate_env()
    garmin = login_garmin()

    # Anchor to local timezone (Asia/Shanghai / UTC+8)
    local_tz = pytz.timezone("Asia/Shanghai")
    today = datetime.now(local_tz).date()

    for i in range(SYNC_DAYS):
        target_date = (today - timedelta(days=i)).isoformat()
        print(f"Fetching Garmin telemetry for {target_date}...")

        summary = garmin.get_user_summary(target_date) or {}
        sleep_data = garmin.get_sleep_data(target_date) or {}
        daily_sleep = sleep_data.get("dailySleepDTO", {}) or {}

        steps = summary.get("totalSteps") or summary.get("steps") or 0
        resting_hr = summary.get("restingHeartRate") or 60
        stress_avg = summary.get("averageStressLevel")
        if stress_avg is None or stress_avg < 0:
            stress_avg = 28
        body_battery = summary.get("bodyBatteryHighestValue") or 80
        active_kcal = summary.get("activeKilocalories") or 0

        # Active minutes extraction with fallbacks
        mod_min = summary.get("moderateIntensityMinutes") or 0
        vig_min = summary.get("vigorousIntensityMinutes") or 0
        active_min = mod_min + (vig_min * 2)

        sleep_sec = daily_sleep.get("sleepTimeSeconds") or 0
        sleep_hours = round(sleep_sec / 3600.0, 1)
        sleep_score = (
            daily_sleep.get("sleepScores", {}).get("overall", {}).get("value")
            or 78
        )

        # Fetch advanced metrics safely (Training Status & Readiness)
        training_status = "N/A"
        try:
            status_data = garmin.get_training_status(target_date)
            if status_data and isinstance(status_data, list) and len(status_data) > 0:
                training_status = status_data[0].get("status", "N/A")
            elif isinstance(status_data, dict):
                training_status = status_data.get("status", "N/A")
        except Exception:
            pass

        training_readiness = 0
        try:
            readiness_data = garmin.get_training_readiness(target_date)
            if readiness_data:
                training_readiness = readiness_data.get("score", 0)
        except Exception:
            pass

        # Activities fetch for workout labeling and active minutes backup
        activities = garmin.get_activities_by_date(target_date, target_date) or []
        workout_label = "Rest / Active Recovery"
        act_duration_total = 0
        if activities:
            first = activities[0]
            act_name = first.get("activityName", "Workout")
            dur_min = round((first.get("duration") or 0) / 60)
            act_duration_total = dur_min
            workout_label = f"{act_name} ({dur_min}m)"

        if active_min == 0 and act_duration_total > 0:
            active_min = act_duration_total

        row = {
            "date": target_date,
            "steps": int(steps),
            "sleep_hours": float(sleep_hours),
            "sleep_score": int(sleep_score),
            "active_min": int(active_min),
            "resting_hr": int(resting_hr),
            "body_battery": int(body_battery),
            "stress_avg": int(stress_avg),
            "active_kcal": int(active_kcal),
            "workout_label": workout_label,
            "training_status": str(training_status),
            "training_readiness": int(training_readiness),
        }

        upsert_to_supabase(row)
        print(f"  ✓ Synced {target_date}: {steps} steps, {active_min} active mins, Status: {training_status}")


if __name__ == "__main__":
    sync_metrics()
