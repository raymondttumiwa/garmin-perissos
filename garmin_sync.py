"""
Pipeline A: Automated Garmin Connect -> Supabase Daily Biometric Sync
Fetches the past 7 days of Garmin Connect metrics and upserts them into Supabase.
"""
import os
import json
import time
import base64
import tempfile
from datetime import date, timedelta
import requests
from garminconnect import Garmin

# 1. Auto-clean environment variables so trailing slashes or spaces never crash the script
RAW_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_URL = RAW_URL.split("/rest/v1")[0].rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "").strip()
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "").strip()
GARMIN_TOKEN_B64 = os.environ.get("GARMIN_TOKEN_BASE64", "").strip()
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "7"))


def validate_env():
    if not SUPABASE_URL.startswith("https://") or ".supabase.co" not in SUPABASE_URL:
        raise ValueError(
            f"SUPABASE_URL looks invalid or empty (got: '{RAW_URL}'). "
            "Check GitHub Settings -> Secrets -> Actions -> SUPABASE_URL."
        )
    if not SUPABASE_KEY:
        raise ValueError("SUPABASE_SERVICE_KEY secret is empty or missing in GitHub Secrets.")


def login_garmin() -> Garmin:
    # Method A: If a cached OAuth token exists in GitHub Secrets, use it (bypasses 429 IP rate limits!)
    if GARMIN_TOKEN_B64:
        print("Restoring Garmin session from GARMIN_TOKEN_BASE64 (bypasses 429 login limits)...")
        token_dir = tempfile.mkdtemp()
        raw_json = base64.b64decode(GARMIN_TOKEN_B64).decode("utf-8")
        data = json.loads(raw_json)
        for fname, content in data.items():
            with open(os.path.join(token_dir, fname), "w") as f:
                json.dump(content, f)
        client = Garmin()
        client.login(token_dir)
        return client

    # Method B: Standard email/password login with retry backoff
    print("Authenticating with Garmin Connect via email/password...")
    for attempt in range(1, 4):
        try:
            client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
            client.login()
            return client
        except Exception as e:
            print(f"Login attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                wait_sec = attempt * 15
                print(f"Waiting {wait_sec}s before retry...")
                time.sleep(wait_sec)
            else:
                raise RuntimeError(
                    "Garmin blocked the GitHub runner IP with HTTP 429. "
                    "See instructions to add GARMIN_TOKEN_BASE64 to GitHub Secrets."
                ) from e


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
    today = date.today()

    for i in range(SYNC_DAYS):
        target_date = (today - timedelta(days=i)).isoformat()
        print(f"Fetching Garmin telemetry for {target_date}...")

        summary = garmin.get_user_summary(target_date) or {}
        sleep_data = garmin.get_sleep_data(target_date) or {}
        daily_sleep = sleep_data.get("dailySleepDTO", {}) or {}

        steps = summary.get("totalSteps") or 0
        resting_hr = summary.get("restingHeartRate") or 60
        stress_avg = summary.get("averageStressLevel")
        if stress_avg is None or stress_avg < 0:
            stress_avg = 28
        body_battery = summary.get("bodyBatteryHighestValue") or 80
        active_kcal = summary.get("activeKilocalories") or 0

        mod_min = summary.get("moderateIntensityMinutes") or 0
        vig_min = summary.get("vigorousIntensityMinutes") or 0
        active_min = mod_min + (vig_min * 2)

        sleep_sec = daily_sleep.get("sleepTimeSeconds") or 0
        sleep_hours = round(sleep_sec / 3600.0, 1)
        sleep_score = (
            daily_sleep.get("sleepScores", {}).get("overall", {}).get("value")
            or 78
        )

        activities = garmin.get_activities_by_date(target_date, target_date) or []
        workout_label = "Rest / Active Recovery"
        if activities:
            first = activities[0]
            act_name = first.get("activityName", "Workout")
            dur_min = round((first.get("duration") or 0) / 60)
            workout_label = f"{act_name} ({dur_min}m)"
            if active_min == 0 and dur_min > 0:
                active_min = dur_min

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
        }

        upsert_to_supabase(row)
        print(f"  ✓ Synced {target_date}: {steps} steps, {sleep_hours}h sleep ({ workout_label })")


if __name__ == "__main__":
    sync_metrics()
