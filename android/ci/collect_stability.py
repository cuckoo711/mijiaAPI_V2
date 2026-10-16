"""Evidence-reviewed prerelease acceptance; raw interrupted runs stay interrupted."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from endurance_duration import validate_duration
from observation_evidence import analyze_samples


def load(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(data), {'file': path.name, 'sha256': hashlib.sha256(data).hexdigest()}


def evaluate(manifest, digest):
    assert manifest['decision'] == 'accept_test_release' and manifest['rationale'].strip()
    commit = manifest['apk_source_commit']
    reference, reference_file = load(manifest['reference_report'])
    assert reference['passed'] and reference['state'] == 'passed'
    assert reference['apk_sha256'] == digest and reference['commit'] == commit
    assert reference['api'] == 36 and reference['page_size'] == 16384
    assert reference['page_size_backcompat_disabled']
    validate_duration(reference)
    reference_summary = analyze_samples(reference)
    assert not reference_summary['gap_count']
    assert reference['console_after_unlock'] and reference['http_idle_exempted']
    observations = []
    for entry in manifest['legacy_reports']:
        report, source = load(entry['path'])
        assert report['apk_sha256'] == digest and report['commit'] == commit
        assert report['api'] == 24 and report['page_size'] == 4096
        summary = analyze_samples(report)
        classification = entry['classification']
        if classification == 'adb_metadata_failure':
            diagnostic_path = Path(entry['diagnostic'])
            diagnostic = diagnostic_path.read_text(encoding='utf-8')
            assert report['state'] == 'failed' and report['error'].startswith('RuntimeError')
            assert "sample['boot_id']" in diagnostic and '/proc/sys/kernel/random/boot_id' in diagnostic
            source['diagnostic'] = {'file': diagnostic_path.name,
                                    'sha256': hashlib.sha256(diagnostic_path.read_bytes()).hexdigest()}
            summary['unobserved_tail'] = {
                'after_utc': report['samples'][-1]['utc'],
                'http_availability': 'unknown',
                'end': 'not joined to later operator-restarted run',
                'process_assessment': 'PID and boot identity were rechecked after the error; older start ticks were not recorded',
            }
        elif classification == 'operator_review_stop':
            receipt, receipt_file = load(entry['receipt'])
            assert receipt['reason'] == 'user_authorized_evidence_review'
            assert receipt['snapshot_sha256'] == source['sha256']
            assert report['state'] == 'screen_off_running'
            source['operator_receipt'] = receipt_file
        else:
            raise AssertionError('Unreviewed interruption; supplement evidence before accepting')
        observations.append({'source': source, 'classification': classification,
                             'summary': summary, 'raw_report': report})
    assert observations
    postflight, postflight_file = load(manifest['postflight_report'])
    assert postflight['passed'] and postflight['apk_sha256'] == digest and postflight['commit'] == commit
    assert postflight['identity_before']['pid'] == observations[-1]['raw_report']['initial_pid']
    assert postflight['identity_before']['boot_id'] == observations[-1]['raw_report']['guest_boot_id']
    assert postflight['identity_before']['start_ticks']
    assert all(postflight[k] for k in ('identity_verified_until_dom_inspection', 'http_before_unlock',
                                      'forced_idle_confirmed', 'user_exemption_flow', 'network_idle_exempted',
                                      'http_idle_exempted', 'http_after_unlock', 'console_after_unlock'))
    return {
        'schema': 'android-stability-review.v2', 'accepted_for_test_release': True,
        'apk_sha256': digest, 'apk_source_commit': commit,
        'review': {'decision': manifest['decision'], 'reviewer': manifest['reviewer'],
                   'rationale': manifest['rationale'], 'tool_commit': manifest['tool_commit']},
        'reference_16k': {'source': reference_file, 'screen_off_seconds': reference['screen_off_seconds'],
                          'summary': reference_summary, 'raw_report': reference},
        'legacy_android7': {'continuous_24h_claim': False,
                            'has_acquisition_gap': any(o['classification'] == 'adb_metadata_failure' or o['summary']['gap_count'] for o in observations),
                            'observed_seconds_across_distinct_runs': sum(o['summary']['observed_seconds'] for o in observations),
                            'observations': observations, 'postflight_source': postflight_file, 'postflight': postflight},
        'limitations': ['Android 7 has interrupted observations, not a completed continuous 24-hour run',
                        'Missing HTTP observations remain unknown; process identity does not prove request availability',
                        'Different service PIDs and operator resets are distinct runs and never joined as continuous time',
                        '16 KiB userspace is simulated on x86_64 with a 4 KiB kernel; no ARM phone or OEM battery-policy proof',
                        'No real Xiaomi cloud account or physical device control'],
        'generated_utc': datetime.now(timezone.utc).isoformat(),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.review.read_text(encoding='utf-8')),
                      hashlib.sha256(args.apk.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'accepted': True, 'legacy_continuous_24h_claim': False,
                      'legacy_observed_seconds': result['legacy_android7']['observed_seconds_across_distinct_runs']}))
