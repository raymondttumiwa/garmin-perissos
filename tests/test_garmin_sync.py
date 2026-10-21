import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

# Unit tests require neither Garmin credentials nor installed network clients.
spec = importlib.util.spec_from_file_location(
    'garmin_sync_under_test', Path(__file__).resolve().parents[1] / 'garmin_sync.py'
)
sync = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    'garminconnect': types.SimpleNamespace(Garmin=Mock()),
    'requests': types.SimpleNamespace(post=Mock()),
}):
    spec.loader.exec_module(sync)


class MetricsTests(unittest.TestCase):
    def test_import_requires_an_explicit_account_uuid(self):
        for user_id in ('', 'default', 'someone-elses-name'):
            with patch.object(sync, 'SUPABASE_USER_ID', user_id):
                with self.assertRaisesRegex(ValueError, 'destination account UUID'):
                    sync.validate_env()

    def test_training_readiness_prefers_morning_and_preserves_zero(self):
        garmin = Mock()
        garmin.get_training_readiness.return_value = [
            {"score": 75}, {"score": 0, "inputContext": "AFTER_WAKEUP_RESET"},
        ]
        self.assertEqual(sync.fetch_training_readiness(garmin, '2026-10-21'),
                         {"training_readiness": 0})
        garmin.get_training_readiness.assert_called_once_with('2026-10-21')

    def test_training_readiness_missing_invalid_and_failed(self):
        garmin = Mock()
        for payload in (None, [], {}, {"score": -1}, {"score": 101}, {"score": None}):
            garmin.get_training_readiness.return_value = payload
            self.assertEqual(sync.fetch_training_readiness(garmin, '2026-10-21'), {})
        garmin.get_training_readiness.side_effect = RuntimeError('unavailable')
        self.assertEqual(sync.fetch_training_readiness(garmin, '2026-10-21'), {})

    def test_training_readiness_single_snapshot(self):
        garmin = Mock()
        garmin.get_training_readiness.return_value = {"score": 83}
        self.assertEqual(sync.fetch_training_readiness(garmin, '2026-10-21'),
                         {"training_readiness": 83})

    def test_dashboard_contract_and_all_workouts(self):
        row = sync.build_metrics_row('2026-10-21', {
            'totalSteps': 1234, 'moderateIntensityMinutes': 20,
            'vigorousIntensityMinutes': 10, 'bodyBatteryHighestValue': 0,
        }, {'sleepTimeSeconds': 27000, 'sleepScores': {'overall': {'value': 82}}}, [
            {'activityName': 'Run', 'duration': 1800, 'averageHR': 140,
             'calories': 300, 'activityType': {'typeKey': 'running'}},
            {'activityName': 'Walk', 'duration': 600},
        ])
        self.assertEqual(row['user_id'], sync.SUPABASE_USER_ID)
        self.assertEqual(row['active_minutes'], 40)
        self.assertEqual(row['sleep_hours'], 7.5)
        self.assertEqual(row['body_battery'], 0)
        self.assertEqual(len(row['activities']), 2)
        self.assertEqual(row['activities'][0]['duration_min'], 30)
        self.assertEqual(row['activities'][0]['type'], 'running')
        self.assertTrue({'manual_logs', 'hydration_ml', 'active_min', 'workout_label'}.isdisjoint(row))

    def test_missing_readings_do_not_replace_existing_measurements(self):
        row = sync.build_metrics_row('2026-10-21', {'averageStressLevel': -1},
                                     {'sleepScores': None}, [])
        self.assertEqual(set(row), {'user_id', 'date', 'activities'})

    def test_upsert_uses_date_and_preserves_omitted_columns(self):
        row = sync.build_metrics_row('2026-10-21', {'totalSteps': 0}, {}, [])
        with patch.object(sync.requests, 'post', return_value=Mock(ok=True)) as post:
            sync.upsert_to_supabase(row)
        self.assertTrue(post.call_args.args[0].endswith('?on_conflict=user_id,date'))
        self.assertEqual(post.call_args.kwargs['json'], row)
        self.assertIn('missing=default', post.call_args.kwargs['headers']['Prefer'])
        with patch.object(sync.requests, 'post', return_value=Mock(ok=False, status_code=400, text='schema mismatch')):
            with self.assertRaisesRegex(RuntimeError, 'schema mismatch'):
                sync.upsert_to_supabase(row)


if __name__ == '__main__':
    unittest.main()
