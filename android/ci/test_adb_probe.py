import subprocess
import unittest
from unittest.mock import patch

from adb_probe import probe


class AdbProbeTest(unittest.TestCase):
    command = ('shell', 'cat', '/proc/sys/kernel/random/boot_id')

    @patch('adb_probe.time.sleep')
    @patch('adb_probe.subprocess.run')
    def test_empty_error_is_recorded_and_recovered(self, run, sleep):
        run.side_effect = [subprocess.CompletedProcess([], 1, '', ''),
                           subprocess.CompletedProcess([], 0, 'same-boot\n', '')]
        records = []
        self.assertEqual(probe(['adb'], self.command, records.append), 'same-boot\n')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(records[0]['returncode'], 1)
        self.assertTrue(records[0]['will_retry'])

    @patch('adb_probe.time.sleep')
    @patch('adb_probe.subprocess.run')
    def test_retries_are_bounded(self, run, sleep):
        run.return_value = subprocess.CompletedProcess([], 1, '', '')
        records = []
        with self.assertRaisesRegex(RuntimeError, 'after 3 attempts'):
            probe(['adb'], self.command, records.append)
        self.assertEqual(run.call_count, 3)
        self.assertFalse(records[-1]['will_retry'])

    @patch('adb_probe.time.sleep')
    @patch('adb_probe.subprocess.run')
    def test_timeout_recovery_is_recorded(self, run, sleep):
        run.side_effect = [subprocess.TimeoutExpired('adb', 10),
                           subprocess.CompletedProcess([], 0, 'same-boot', '')]
        records = []
        self.assertEqual(probe(['adb'], self.command, records.append), 'same-boot')
        self.assertEqual(records[0]['error'], 'transport_timeout_10s')

    @patch('adb_probe.subprocess.run')
    def test_mutations_are_never_retried(self, run):
        with self.assertRaises(AssertionError):
            probe(['adb'], ('shell', 'pm', 'clear', 'com.cuckoo.mijia.standalone'), lambda _: None)
        run.assert_not_called()

    @patch('adb_probe.subprocess.run')
    def test_changed_pid_is_returned_for_callers_strict_identity_check(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '9999\n', '')
        value = probe(['adb'], ('shell', 'pidof', 'com.cuckoo.mijia.standalone:server'), lambda _: None)
        self.assertEqual(value.strip(), '9999')
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
