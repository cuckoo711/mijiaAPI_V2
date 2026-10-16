"""Separate sampled application failures from missing transport observations."""


def analyze_samples(report):
    samples = report['samples']
    assert samples, 'No observations'
    healthy, gaps, segments = [], [], []
    current = []
    previous = None
    for sample in samples:
        if previous is not None:
            assert sample['elapsed_seconds'] > previous['elapsed_seconds'], 'Non-monotonic observations'
        if sample.get('kind') == 'observation_gap':
            assert sample.get('reason_category') == 'adb_transport'
            assert sample.get('http_ready') is not False, 'An HTTP failure cannot be relabelled a transport gap'
            gaps.append(dict(sample))
            if current:
                segments.append(current)
                current = []
        else:
            assert sample['http_ready'], 'Application HTTP failed'
            assert sample['pid'] == report['initial_pid'], 'Service process changed'
            assert sample['boot_id'] == report['guest_boot_id'], 'Guest restarted'
            assert sample['screen_off'] and sample['wake_lock'], 'Screen or wake lock changed'
            if report.get('process_start_ticks'):
                assert sample['process_start_ticks'] == report['process_start_ticks'], 'PID was reused'
            if healthy:
                assert sample['guest_uptime'] >= healthy[-1]['guest_uptime'], 'Guest uptime regressed'
            if current and sample['elapsed_seconds'] - current[-1]['elapsed_seconds'] > 90:
                fingerprint = report.get('process_start_ticks')
                gaps.append({'kind': 'cadence_gap', 'from_utc': current[-1]['utc'], 'to_utc': sample['utc'],
                             'http_availability': 'unobserved',
                             'continuity': 'process_identity_confirmed' if fingerprint else 'unresolved'})
                segments.append(current)
                current = []
            current.append(sample)
            healthy.append(sample)
        previous = sample
    if current:
        segments.append(current)
    assert healthy, 'No successful application observations'
    return {
        'healthy_sample_count': len(healthy), 'gap_count': len(gaps), 'observation_gaps': gaps,
        'unresolved_gap_count': sum(g.get('continuity') != 'process_identity_confirmed' for g in gaps),
        'observed_seconds': sum(s[-1]['elapsed_seconds']-s[0]['elapsed_seconds'] for s in segments),
        'segments': [{'started_utc': s[0]['utc'], 'finished_utc': s[-1]['utc'],
                      'observed_seconds': s[-1]['elapsed_seconds']-s[0]['elapsed_seconds'],
                      'sample_count': len(s)} for s in segments],
        'pid': report['initial_pid'], 'boot_id': report['guest_boot_id'],
        'continuous_http_availability_claim': False,
    }
