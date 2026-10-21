"""
Pipeline A: Automated Garmin Connect -> Supabase Daily Biometric Sync
Fetches the past 7 days of Garmin Connect metrics and upserts them into Supabase.
"""
import os
import json
import time
import base64
import tempfile
from uuid import UUID
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
SUPABASE_USER_ID = os.environ.get("SUPABASE_USER_ID", "").strip()
GARMIN_TIMEZONE = os.environ.get("GARMIN_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"


def validate_env():
    try:
        UUID(SUPABASE_USER_ID)
    except ValueError as exc:
        raise ValueError("SUPABASE_USER_ID must be the destination account UUID from the website account settings.") from exc
    if not SUPABASE_URL.startswith("https://") or ".supabase.co" not in SUPABASE_URL:
        raise ValueError(
            f"SUPABASE_URL looks invalid or empty (got: '{RAW_URL}'). "
            "Check GitHub Settings -> Secrets -> Actions -> SUPABASE_URL."
        )
    if SYNC_DAYS < 1:
        raise ValueError("SYNC_DAYS must be at least 1.")
    ZoneInfo(GARMIN_TIMEZONE)
    if not SUPABASE_KEY:
        raise ValueError("SUPABASE_SERVICE_KEY secret is empty or missing in GitHub Secrets.")


def login_garmin() -> Garmin:
    # Method A: If a cached OAuth token exists in GitHub Secrets, use it (bypasses 429 IP rate limits!)
    if GARMIN_TOKEN_B64:
        print("Restoring Garmin session from GARMIN_TOKEN_BASE64 (bypasses 429 login limits)...")
        with tempfile.TemporaryDirectory() as token_dir:
            data = json.loads(base64.b64decode(GARMIN_TOKEN_B64, validate=True))
            for fname, content in data.items():
                if fname not in {"oauth1_token.json", "oauth2_token.json"}:
                    raise ValueError(f"Unexpected Garmin token filename: {fname}")
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
                    "Garmin authentication failed after three attempts. "
                    "See instructions to add GARMIN_TOKEN_BASE64 to GitHub Secrets."
                ) from e


def upsert_to_supabase(row: dict):
    endpoint = f"{SUPABASE_URL}/rest/v1/garmin_daily_metrics?on_conflict=user_id,date"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,missing=default",
    }
    resp = requests.post(endpoint, headers=headers, json=row, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Supabase error ({resp.status_code}): {resp.text}")


def build_metrics_row(target_date, summary, daily_sleep, activities):
    """Use the dashboard schema; omit absent metrics and browser-owned fields.

    In particular, never send manual_logs or hydration_ml: a Garmin refresh
    must preserve the values already stored by the dashboard.
    """
    row = {"user_id": SUPABASE_USER_ID, "date": target_date}
    for column, source in {
        "steps": "totalSteps",
        "resting_hr": "restingHeartRate",
        "body_battery": "bodyBatteryHighestValue",
        "stress_avg": "averageStressLevel",
    }.items():
        value = summary.get(source)
        if value is not None and value >= 0:
            row[column] = int(value)

    moderate = summary.get("moderateIntensityMinutes")
    vigorous = summary.get("vigorousIntensityMinutes")
    if moderate is not None or vigorous is not None:
        row["active_minutes"] = int((moderate or 0) + 2 * (vigorous or 0))

    sleep_seconds = daily_sleep.get("sleepTimeSeconds")
    if sleep_seconds is not None and sleep_seconds >= 0:
        row["sleep_hours"] = round(sleep_seconds / 3600, 1)
    scores = daily_sleep.get("sleepScores") or {}
    sleep_score = (scores.get("overall") or {}).get("value")
    if sleep_score is not None and sleep_score >= 0:
        row["sleep_score"] = int(sleep_score)

    row["activities"] = [{
        "name": activity.get("activityName") or "Garmin Activity",
        "duration_min": round((activity.get("duration") or 0) / 60),
        "avg_hr": activity.get("averageHR"),
        "calories": activity.get("calories"),
        "type": (activity.get("activityType") or {}).get("typeKey", "other"),
    } for activity in activities]
    return row


def fetch_training_readiness(garmin, target_date):
    """Return the morning score, or omit it when Garmin has no measurement."""
    try:
        data = garmin.get_training_readiness(target_date)
    except Exception as exc:
        # Optional metric: unsupported devices or unavailable endpoints should
        # not prevent the day's steps, sleep and activities from syncing.
        print(f"  Training readiness request failed for {target_date}: "
              f"{type(exc).__name__}: {exc}")
        return {}

    entries = [data] if isinstance(data, dict) else data or []
    entries = [entry for entry in entries if isinstance(entry, dict)]
    morning = next((entry for entry in entries
                    if entry.get("inputContext") == "AFTER_WAKEUP_RESET"), None)
    entry = morning if morning is not None else (entries[0] if entries else {})
    score = entry.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100:
        print(f"  Training readiness for {target_date}: {score}")
        return {"training_readiness": int(score)}
    print(f"  No training readiness score returned for {target_date}; "
          "preserving any existing database value.")
    return {}


def sync_metrics():
    validate_env()
    garmin = login_garmin()
    today = datetime.now(ZoneInfo(GARMIN_TIMEZONE)).date()

    for i in range(SYNC_DAYS):
        target_date = (today - timedelta(days=i)).isoformat()
        print(f"Fetching Garmin telemetry for {target_date}...")

        summary = garmin.get_user_summary(target_date) or {}
        sleep_data = garmin.get_sleep_data(target_date) or {}
        daily_sleep = sleep_data.get("dailySleepDTO", {}) or {}

        activities = garmin.get_activities_by_date(target_date, target_date) or []
        row = build_metrics_row(target_date, summary, daily_sleep, activities)
        row.update(fetch_training_readiness(garmin, target_date))

        upsert_to_supabase(row)
        print(f"  ✓ Synced {target_date}: {row.get('steps')} steps, "
              f"{row.get('sleep_hours')}h sleep, {len(row['activities'])} activities")


if __name__ == "__main__":
    sync_metrics()
