"""Selection and authorization boundaries for automated Gitee release mirroring."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "deploy" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import gitee_release_policy as policy  # noqa: E402

REPOSITORY = "cuckoo711/mijiaAPI_V2"
SOURCE_SHA = "a" * 40


def release(tag="v3.9.1", prerelease=False, **changes):
    return {
        "id": 1,
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": False,
        "published_at": "2026-10-14T15:04:50Z",
        **changes,
    }


def upstream(**changes):
    return {
        "name": "Build Multi-Platform Release",
        "conclusion": "success",
        "event": "push",
        "head_branch": "v3.9.1",
        "head_repository": {"full_name": REPOSITORY},
        **changes,
    }


def test_latest_is_numeric_and_never_rolls_back_for_late_historical_publication():
    stable = release("v3.10.0", id=2)
    android = release("v3.10.0-android-test.10", prerelease=True, id=3)
    releases = [
        release("v3.9.99", published_at="2099-01-01T00:00:00Z"),
        release("v3.10.0-android-test.9", prerelease=True),
        stable,
        android,
        release("v3.9.99-android-test.999", prerelease=True),
    ]
    original = deepcopy(releases)
    assert policy.latest_releases(releases) == [stable, android]
    assert releases == original


def test_stable_and_android_are_selected_independently_and_stable_is_first():
    android = release("v4.0.0-android-test.1", prerelease=True)
    stable = release("v3.9.1")
    assert policy.latest_releases([android, stable]) == [stable, android]
    assert policy.latest_releases([android]) == [android]
    assert policy.latest_releases([stable]) == [stable]
    assert policy.latest_releases([]) == []


@pytest.mark.parametrize(
    "invalid",
    [
        release("v99.0.0", draft=True),
        release("v99.0.0", draft=None),
        release("v99.0.0", published_at=None),
        release("v99.0.0", published_at=""),
        release("v99.0.0", published_at="  "),
        release("v99.0.0", prerelease=True),
        release("v99.0.0-android-test.1", prerelease=False),
        release("v99.0.0-beta.1", prerelease=True),
        release("v99.0.0-rc.1", prerelease=True),
        release("v99.0.0-android-test.1", prerelease="true"),
        release("v99.0.0", prerelease=0),
        release("99.0.0"),
        release("v99.0"),
        release("v099.0.0"),
        release("v99.0.0\n"),
        release("v99.0.0-android-test.1-extra", prerelease=True),
        release("v99.0.0-android-test.01", prerelease=True),
    ],
)
def test_unpublished_malformed_or_other_prereleases_are_not_candidates(invalid):
    assert policy.latest_releases([invalid]) == []


@pytest.mark.parametrize("name", ["Build Multi-Platform Release", "Android Test APK"])
@pytest.mark.parametrize("tag", ["v3.9.1", "v3.9.1-android-test.9"])
@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_successful_owned_release_workflow_may_trigger_reconciliation(name, tag, event):
    payload = {"workflow_run": upstream(name=name, head_branch=tag, event=event)}
    assert policy.should_sync("workflow_run", payload, REPOSITORY)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Unrelated CI"},
        {"name": {}},
        {"conclusion": "failure"},
        {"conclusion": "cancelled"},
        {"conclusion": None},
        {"event": "pull_request"},
        {"event": "pull_request_target"},
        {"event": "workflow_run"},
        {"event": []},
        {"head_repository": {"full_name": "fork/mijiaAPI_V2"}},
        {"head_repository": None},
        {"head_repository": {}},
        {"head_branch": "main"},
        {"head_branch": "feature/v3.9.1"},
        {"head_branch": "refs/tags/v3.9.1"},
        {"head_branch": "v3.9.1-beta.1"},
        {"head_branch": "v3.9.1-android-test.9\n"},
    ],
)
def test_untrusted_unrelated_or_unsuccessful_workflow_run_is_rejected(changes):
    assert not policy.should_sync("workflow_run", {"workflow_run": upstream(**changes)}, REPOSITORY)


@pytest.mark.parametrize("action", ["published", "edited"])
@pytest.mark.parametrize("source", [release(), release("v3.9.1-android-test.9", prerelease=True)])
def test_release_events_accept_only_supported_published_channels(action, source):
    assert policy.should_sync("release", {"action": action, "release": source}, REPOSITORY)


@pytest.mark.parametrize(
    "action,source",
    [
        ("created", release()),
        ({}, release()),
        ("deleted", release()),
        ("unpublished", release()),
        ("published", release(draft=True)),
        ("edited", release(published_at=None)),
        ("published", release("v9.0.0-beta.1", prerelease=True)),
        ("published", release("v9.0.0-android-test.1", prerelease=False)),
        ("published", {}),
        ("published", None),
    ],
)
def test_release_events_reject_drafts_unrelated_actions_and_other_prereleases(action, source):
    assert not policy.should_sync("release", {"action": action, "release": source}, REPOSITORY)


@pytest.mark.parametrize("event_name", ["schedule", "workflow_dispatch", "workflow_run", "release"])
def test_explicit_payload_repository_mismatch_is_always_rejected(event_name):
    event = {
        "repository": {"full_name": "fork/mijiaAPI_V2"},
        "workflow_run": upstream(),
        "release": release(),
        "action": "published",
    }
    assert not policy.should_sync(event_name, event, REPOSITORY)


@pytest.mark.parametrize("event_name", ["schedule", "workflow_dispatch"])
def test_trusted_context_events_allow_missing_repository_payload(event_name):
    assert policy.should_sync(event_name, {}, REPOSITORY)
    assert policy.should_sync(event_name, {"repository": {"full_name": REPOSITORY}}, REPOSITORY)


@pytest.mark.parametrize("event_name", ["push", "pull_request", "repository_dispatch", ""])
def test_other_events_are_not_authorized(event_name):
    assert not policy.should_sync(event_name, {}, REPOSITORY)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "output.txt"
    event_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(sys, "argv", ["policy", "--github-repo", REPOSITORY])
    state = {
        "event_path": event_path,
        "output_path": output_path,
        "releases": [release()],
        "commands": [],
    }

    def run(command):
        state["commands"].append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return SOURCE_SHA + "\n"
        assert command == [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{REPOSITORY}/releases?per_page=100",
        ]
        return json.dumps([state["releases"]], ensure_ascii=False)

    monkeypatch.setattr(policy, "_run", run)
    return state


def outputs(state):
    return dict(
        line.split("=", 1) for line in state["output_path"].read_text(encoding="utf-8").splitlines()
    )


def test_cli_emits_only_latest_two_releases_and_all_required_outputs(cli):
    cli["releases"] = [
        release("v3.9.0"),
        release("v3.9.1", id=2),
        release("v3.9.1-android-test.9", prerelease=True, id=3),
        release("v9.0.0-beta.1", prerelease=True),
    ]
    assert policy.main() == 0
    result = outputs(cli)
    assert result == {
        "matrix": '{"include":[{"tag":"v3.9.1","release_id":2},{"tag":"v3.9.1-android-test.9","release_id":3}]}',
        "has_releases": "true",
        "source_sha": SOURCE_SHA,
        "dry_run": "false",
    }


@pytest.mark.parametrize(
    "value,expected", [(True, "true"), (False, "false"), ("true", "true"), ("false", "false")]
)
def test_manual_dry_run_accepts_boolean_and_exact_string_values(cli, monkeypatch, value, expected):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    cli["event_path"].write_text(json.dumps({"inputs": {"dry_run": value}}), encoding="utf-8")
    assert policy.main() == 0
    assert outputs(cli)["dry_run"] == expected


@pytest.mark.parametrize("value", [None, 0, 1, "", "False", "yes", [], {}])
def test_invalid_manual_dry_run_fails_closed(cli, monkeypatch, value):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    cli["event_path"].write_text(json.dumps({"inputs": {"dry_run": value}}), encoding="utf-8")
    assert policy.main() == 1
    assert not cli["output_path"].exists()
    assert cli["commands"] == []


def test_manual_input_cannot_request_historical_or_all_releases(cli, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    cli["event_path"].write_text(json.dumps({"inputs": {"tag": "all"}}), encoding="utf-8")
    assert policy.main() == 1
    assert cli["commands"] == []


@pytest.mark.parametrize("event_name", ["schedule", "workflow_dispatch"])
@pytest.mark.parametrize("ref", ["refs/heads/feature", "refs/tags/v3.9.1", ""])
def test_schedule_and_manual_cli_require_trusted_main(cli, monkeypatch, event_name, ref):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_REF", ref)
    assert policy.main() == 0
    assert outputs(cli)["has_releases"] == "false"
    assert json.loads(outputs(cli)["matrix"]) == {"include": []}
    assert cli["commands"] == [["git", "rev-parse", "HEAD"]]


@pytest.mark.parametrize("event_name", ["workflow_run", "release"])
def test_release_and_workflow_run_cli_do_not_depend_on_default_branch_ref(
    cli, monkeypatch, event_name
):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v3.9.1")
    payload = {"workflow_run": upstream(), "release": release(), "action": "published"}
    cli["event_path"].write_text(json.dumps(payload), encoding="utf-8")
    assert policy.main() == 0
    assert outputs(cli)["has_releases"] == "true"


def test_untrusted_cli_event_skips_source_release_api_and_emits_empty_matrix(cli, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    payload = {"workflow_run": upstream(event="pull_request")}
    cli["event_path"].write_text(json.dumps(payload), encoding="utf-8")
    assert policy.main() == 0
    assert outputs(cli)["has_releases"] == "false"
    assert cli["commands"] == [["git", "rev-parse", "HEAD"]]


def test_no_qualifying_release_is_a_successful_empty_plan(cli):
    cli["releases"] = [release("v9.0.0-beta.1", prerelease=True)]
    assert policy.main() == 0
    assert outputs(cli)["has_releases"] == "false"


def test_invalid_slug_fails_before_event_or_api_reads(cli, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["policy", "--github-repo", "owner/repo?token=secret"])
    assert policy.main() == 1
    assert cli["commands"] == []


def test_cli_never_logs_third_party_exception_text_or_captured_credentials(
    cli, monkeypatch, capsys
):
    def fail(command):
        raise subprocess.CalledProcessError(1, "secret command", stderr="token=secret")

    monkeypatch.setattr(policy.subprocess, "run", lambda *args, **kwargs: fail(args[0]))
    monkeypatch.setattr(policy, "_run", _ORIGINAL_RUN)
    assert policy.main() == 1
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    assert "CalledProcessError" in output.err


_ORIGINAL_RUN = policy._run


def test_subprocess_metadata_is_captured_and_decoded_as_utf8(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="教程", stderr="")

    monkeypatch.setattr(policy.subprocess, "run", run)
    assert policy._run(["gh", "api", "metadata"]) == "教程"
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["check"] is True


def test_cli_rejects_missing_release_id_before_writing_outputs(cli):
    cli["releases"] = [release(id=None)]
    assert policy.main() == 1
    assert not cli["output_path"].exists()
