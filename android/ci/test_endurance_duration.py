from datetime import datetime, timedelta, timezone
import unittest

from endurance_duration import validate_duration


class EnduranceDurationTest(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.report = {
            'requested_seconds': 86400, 'screen_off_seconds': 86400.0,
            'screen_off_started_utc': start.isoformat(),
            'screen_off_finished_utc': (start + timedelta(seconds=86400.01)).isoformat(),
            'samples': [
                {'elapsed_seconds': 0, 'guest_uptime': 100},
                {'elapsed_seconds': 86399.9, 'guest_uptime': 86500.98,
                 'utc': (start + timedelta(seconds=86399.9)).isoformat()},
            ],
        }

    def test_completed_day_with_probe_started_just_before_boundary(self):
        validate_duration(self.report)

    def test_short_monotonic_duration_rejected(self):
        self.report['screen_off_seconds'] = 86399.9
        with self.assertRaises(AssertionError):
            validate_duration(self.report)

    def test_short_wall_duration_rejected(self):
        self.report['screen_off_finished_utc'] = self.report['samples'][-1]['utc']
        with self.assertRaises(AssertionError):
            validate_duration(self.report)

    def test_stale_final_probe_rejected(self):
        self.report['samples'][-1]['elapsed_seconds'] = 86394
        with self.assertRaises(AssertionError):
            validate_duration(self.report)

    def test_guest_clock_reset_rejected(self):
        self.report['samples'][-1]['guest_uptime'] = 1000
        with self.assertRaises(AssertionError):
            validate_duration(self.report)


if __name__ == '__main__':
    unittest.main()
