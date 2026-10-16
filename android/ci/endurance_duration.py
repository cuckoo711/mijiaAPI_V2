"""Validate completed time separately from the start timestamp of the last probe."""
from datetime import datetime


def validate_duration(report):
    required = max(86400, report['requested_seconds'])
    assert report['requested_seconds'] >= 86400
    assert report['screen_off_seconds'] >= required
    started = datetime.fromisoformat(report['screen_off_started_utc'])
    finished = datetime.fromisoformat(report['screen_off_finished_utc'])
    assert (finished - started).total_seconds() >= required
    samples = report['samples']
    assert samples[0]['elapsed_seconds'] <= 5
    # Each sample timestamps request start. Its successful HTTP/PID/power probes
    # can finish just after the requested duration; they must still be fresh.
    assert 0 <= report['screen_off_seconds'] - samples[-1]['elapsed_seconds'] <= 5
    last_started = datetime.fromisoformat(samples[-1]['utc'])
    assert 0 <= (finished - last_started).total_seconds() <= 5
    healthy = [s for s in samples if s.get('kind') != 'observation_gap']
    assert healthy
    baseline = report.get('guest_uptime_at_start', healthy[0]['guest_uptime'])
    assert healthy[-1]['guest_uptime'] - baseline >= 86390
