import copy
import unittest

from observation_evidence import analyze_samples


def sample(elapsed):
    return {'elapsed_seconds': elapsed, 'utc': f'fixture-{elapsed}',
            'http_ready': True, 'pid': '100', 'boot_id': 'boot', 'guest_uptime': elapsed+100,
            'screen_off': True, 'wake_lock': True, 'process_start_ticks': '50'}


class ObservationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.report = {'initial_pid': '100', 'guest_boot_id': 'boot', 'process_start_ticks': '50',
                       'samples': [sample(0), sample(30), sample(60)]}

    def test_transport_gap_keeps_separate_observed_segments(self):
        self.report['samples'] = [sample(0), sample(30),
            {'elapsed_seconds': 60, 'kind': 'observation_gap', 'reason_category': 'adb_transport',
             'continuity': 'process_identity_confirmed'}, sample(90), sample(120)]
        summary = analyze_samples(self.report)
        self.assertEqual(summary['observed_seconds'], 60)
        self.assertEqual(summary['gap_count'], 1)
        self.assertEqual(summary['unresolved_gap_count'], 0)
        self.assertFalse(summary['continuous_http_availability_claim'])

    def test_unresolved_gap_remains_unknown(self):
        self.report['samples'].append({'elapsed_seconds': 90, 'kind': 'observation_gap',
                                      'reason_category': 'adb_transport', 'continuity': 'unresolved'})
        self.assertEqual(analyze_samples(self.report)['unresolved_gap_count'], 1)

    def test_real_http_failure_cannot_be_relabelled_as_adb(self):
        self.report['samples'][-1].update(kind='observation_gap', reason_category='adb_transport', http_ready=False)
        with self.assertRaises(AssertionError):
            analyze_samples(self.report)

    def test_boot_and_pid_reuse_are_application_identity_failures(self):
        for field, value in [('pid', '101'), ('boot_id', 'other-boot'), ('process_start_ticks', '99')]:
            report = copy.deepcopy(self.report)
            report['samples'][-1][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                analyze_samples(report)

    def test_unlogged_cadence_gap_is_disclosed(self):
        self.report['samples'][-1] = sample(300)
        summary = analyze_samples(self.report)
        self.assertEqual(summary['observed_seconds'], 30)
        self.assertEqual(summary['gap_count'], 1)


if __name__ == '__main__':
    unittest.main()
