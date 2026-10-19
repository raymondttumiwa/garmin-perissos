"""
Pipeline A: Automated Garmin Connect -> Supabase Daily Biometric Sync
Fetches the past 7 days of Garmin Connect metrics and upserts them into Supabase.
"""
import os
from datetime import date, timedelta
from garminconnect import Garmin
from supabase import create_client, Client

GARMIN_EMAIL = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
USER_ID = os.environ.get("USER_ID", "default")


def sync_last_7_days():
    print("Authenticating with Garmin Connect...")
    garmin = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    garmin.login()

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    today = date.today()

    for offset in range(7):
        target_date = (today - timedelta(days=offset)).isoformat()
        print(f"Fetching Garmin telemetry for {target_date}...")

        # 1. Daily Summary (Steps, RHR, Stress, Body Battery, Active Minutes)
        stats = garmin.get_stats(target_date) or {}
        steps = stats.get("totalSteps") or 0
        resting_hr = stats.get("restingHeartRate") or 0
        stress_avg = stats.get("averageStressLevel") or 0
        body_battery = stats.get("bodyBatteryHighestValue") or 0
        mod_min = stats.get("moderateIntensityMinutes") or 0
        vig_min = stats.get("vigorousIntensityMinutes") or 0
        active_minutes = mod_min + (vig_min * 2)

        # 2. Sleep Duration & Sleep Score
        sleep_hours = 0.0
        sleep_score = 0
        try:
            sleep_data = garmin.get_sleep_data(target_date) or {}
            daily_sleep = sleep_data.get("dailySleepDTO") or {}
            sleep_sec = daily_sleep.get("sleepTimeSeconds") or 0
            sleep_hours = round(sleep_sec / 3600.0, 2)
            sleep_score = (
                daily_sleep.get("sleepScores", {})
                .get("overall", {})
                .get("value")
                or 0
            )
        except Exception as e:
            print(f"Sleep fetch warning on {target_date}: {e}")

        # 3. Hydration
        hydration_ml = 0
        try:
            hyd = garmin.get_hydration_data(target_date) or {}
            hydration_ml = int(hyd.get("valueInML") or 0)
        except Exception:
            pass

        # 4. Recorded Workouts / Activities for the day
        activities_payload = []
        try:
            raw_acts = garmin.get_activities_by_date(target_date, target_date) or []
            for act in raw_acts:
                activities_payload.append({
                    "name": act.get("activityName", "Workout"),
                    "duration_min": round((act.get("duration") or 0) / 60),
                    "avg_hr": act.get("averageHR"),
                    "calories": round(act.get("calories") or 0),
                    "type": act.get("activityType", {}).get("typeKey", "workout")
                })
        except Exception as e:
            print(f"Activities warning on {target_date}: {e}")

        row = {
            "user_id": USER_ID,
            "date": target_date,
            "steps": steps,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
            "active_minutes": active_minutes,
            "body_battery": body_battery,
            "resting_hr": resting_hr,
            "stress_avg": stress_avg,
            "hydration_ml": hydration_ml,
            "activities": activities_payload,
        }

        supabase.table("garmin_daily_metrics").upsert(row).execute()
        print(f"Upserted {target_date}: {steps} steps, {sleep_hours}h sleep, RHR {resting_hr}")


if __name__ == "__main__":
    sync_last_7_days()
