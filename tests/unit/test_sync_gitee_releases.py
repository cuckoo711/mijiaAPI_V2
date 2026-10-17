"""Safety and resumability checks for mirroring existing release artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "deploy" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import sync_gitee_releases as sync  # noqa: E402


def asset(name="server.bin", content=b"original"):
    return {
        "name": name,
        "size": len(content),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def release():
    return {
        "id": 1,
        "tag_name": "v1.0",
        "name": "Version 1",
        "body": "Full notes\n\nDetails",
        "prerelease": True,
        "created_at": "2026-01-01T00:00:00Z",
        "assets": [asset()],
    }


def test_cli_json_is_decoded_as_utf8_on_windows():
    assert (
        sync.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes.fromhex('e69599e7a88b'))",
            ]
        )
        == "教程"
    )


@pytest.mark.parametrize("name", ["../outside", "x/y.bin", "x\\y", "C:drive", "CON", "a.", "a\n"])
def test_rejects_unsafe_attachment_paths(name):
    with pytest.raises(sync.SyncError, match="Unsafe"):
        sync.assets_by_name([asset(name)], source=True)


def test_rejects_colliding_names_and_missing_source_digest():
    with pytest.raises(sync.SyncError, match="Duplicate"):
        sync.assets_by_name([asset("Package.apk"), asset("package.apk")], source=True)
    unsigned = asset()
    unsigned.pop("digest")
    with pytest.raises(sync.SyncError, match="source SHA256"):
        sync.assets_by_name([unsigned], source=True)


def test_local_hash_mismatch_is_detected_with_same_length(tmp_path):
    (tmp_path / "server.bin").write_bytes(b"tampered")
    with pytest.raises(sync.SyncError, match="SHA256 mismatch"):
        sync.verify_local(tmp_path, {"server.bin": asset()})


def test_annotated_tag_object_must_match_even_when_peeled_commit_matches(monkeypatch):
    refs = [
        {"refs/tags/v1": "tag-object-a", "refs/tags/v1^{}": "commit"},
        {"refs/tags/v1": "tag-object-b", "refs/tags/v1^{}": "commit"},
    ]
    monkeypatch.setattr(sync, "tag_refs", lambda *args: refs.pop(0))
    with pytest.raises(sync.SyncError, match="Exact"):
        sync.verify_tag("source/repo", "target", "repo", "v1")


@pytest.mark.parametrize("annotated", [True, False])
def test_verified_tag_returns_peeled_commit_or_lightweight_commit(monkeypatch, annotated):
    refs = {"refs/tags/v1": "a" * 40}
    if annotated:
        refs["refs/tags/v1^{}"] = "b" * 40
    monkeypatch.setattr(sync, "tag_refs", lambda *args: refs)
    assert sync.verify_tag("source/repo", "target", "repo", "v1") == (
        "b" * 40 if annotated else "a" * 40
    )


def test_missing_target_tag_blocks_download_and_creation(monkeypatch):
    refs = [{"refs/tags/v1.0": "source"}, {}]
    monkeypatch.setattr(sync, "tag_refs", lambda *args: refs.pop(0))
    monkeypatch.setattr(sync, "run", lambda *a, **k: pytest.fail("must not download"))
    monkeypatch.setattr(sync, "_api", lambda *a, **k: pytest.fail("must not create release"))
    with pytest.raises(sync.SyncError, match="synchronize tags"):
        sync.sync_release(release(), "source/repo", "target", "repo", "secret")


@pytest.fixture
def target(monkeypatch):
    source = release()
    state = {
        "release": {"id": 7, **{key: source[key] for key in ("name", "body", "prerelease")}},
        "attachments": [{"id": 8, "name": "server.bin"}],
        "api": [],
        "uploads": 0,
    }
    monkeypatch.setattr(sync, "verify_tag", lambda *args: "b" * 40)

    def download(command, **kwargs):
        directory = Path(command[command.index("--dir") + 1])
        (directory / "server.bin").write_bytes(b"original")
        return ""

    def api(method, path, **kwargs):
        state["api"].append((method, path, kwargs.get("form")))
        if method == "POST":
            state["release"] = {"id": 7, **kwargs["form"], "prerelease": True}
            return state["release"]
        if method == "PATCH":
            state["release"].update(kwargs["form"])
            state["release"]["prerelease"] = kwargs["form"]["prerelease"] == "true"
            return state["release"]
        pytest.fail(f"Unexpected mutation {method}")

    def upload(**kwargs):
        state["uploads"] += 1
        item = {"id": 8, "name": kwargs["path"].name}
        state["attachments"].append(item)
        return item

    monkeypatch.setattr(sync, "run", download)
    monkeypatch.setattr(sync, "get_release_by_tag", lambda **kwargs: state["release"])
    monkeypatch.setattr(sync, "list_attachments", lambda **kwargs: state["attachments"])
    monkeypatch.setattr(sync, "upload_attachment", upload)
    monkeypatch.setattr(sync, "_api", api)
    monkeypatch.setattr(sync, "urlopen", lambda *a, **k: io.BytesIO(b"original"))
    return state


def test_existing_verified_attachment_skips_upload_and_copies_full_metadata(target):
    target["release"].update(name="old", body="short", prerelease=False)
    result = sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert result["skipped"] == result["verified"] == 1
    assert target["uploads"] == 0
    assert [call[0] for call in target["api"]] == ["PATCH"]
    assert target["release"]["body"] == release()["body"]
    assert target["release"]["name"] == release()["name"]
    assert target["release"]["prerelease"] is True
    assert target["api"][0][2]["tag_name"] == "v1.0"


def test_existing_corrupt_attachment_is_never_deleted_or_replaced(target, monkeypatch):
    monkeypatch.setattr(sync, "urlopen", lambda *a, **k: io.BytesIO(b"tampered"))
    with pytest.raises(sync.SyncError, match="mismatch"):
        sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert target["uploads"] == 0
    assert target["api"] == []
    assert target["attachments"] == [{"id": 8, "name": "server.bin"}]


def test_missing_attachment_is_uploaded_and_downloaded_for_verification(target):
    target["attachments"] = []
    result = sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert result["uploaded"] == result["verified"] == target["uploads"] == 1


def test_new_release_never_auto_creates_tag(target):
    target["release"] = None
    target["attachments"] = []
    result = sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert result["status"] == "verified"
    assert target["api"][0][0] == "POST"
    assert target["api"][0][2]["auto_create_tag"] == "false"
    assert target["api"][0][2]["target_commitish"] == "b" * 40
    assert target["api"][0][2]["tag_name"] == "v1.0"
    assert all(
        required in target["api"][0][2]
        for required in ("tag_name", "name", "body", "target_commitish")
    )


@pytest.mark.parametrize(
    "items", [[{"id": 9, "name": "extra.txt"}], [{"id": 8, "name": "server.bin"}] * 2]
)
def test_unexpected_or_duplicate_remote_attachments_fail_without_deletion(target, items):
    target["attachments"] = items
    with pytest.raises(sync.SyncError):
        sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert target["api"] == []
    assert target["uploads"] == 0


def test_new_upload_is_also_hash_checked(target, monkeypatch):
    target["attachments"] = []
    monkeypatch.setattr(sync, "urlopen", lambda *a, **k: io.BytesIO(b"tampered"))
    with pytest.raises(sync.SyncError, match="mismatch"):
        sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert target["uploads"] == 1
    assert target["api"] == []


def test_ci_upload_diagnostics_are_cancelled_even_after_upload_failure(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        sync.faulthandler,
        "dump_traceback_later",
        lambda *args, **kwargs: calls.append(("start", args, kwargs)),
    )
    monkeypatch.setattr(
        sync.faulthandler, "cancel_dump_traceback_later", lambda: calls.append(("cancel",))
    )
    parameters = {
        "token": "secret",
        "owner": "owner",
        "repo": "repo",
        "release_id": 7,
        "path": tmp_path / "server.bin",
    }

    def fail(**kwargs):
        assert kwargs == parameters
        raise sync.GiteeError("upload failed")

    monkeypatch.setattr(sync, "upload_attachment", fail)
    with pytest.raises(sync.GiteeError, match="upload failed"):
        sync.upload_with_diagnostics(**parameters)
    assert calls == [
        ("start", (120,), {"repeat": True, "file": sys.__stderr__}),
        ("cancel",),
    ]


def test_local_upload_does_not_enable_traceback_timer(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setattr(
        sync.faulthandler, "dump_traceback_later", lambda *a, **k: pytest.fail("CI only")
    )
    monkeypatch.setattr(
        sync.faulthandler, "cancel_dump_traceback_later", lambda: pytest.fail("no timer")
    )
    monkeypatch.setattr(sync, "upload_attachment", lambda **kwargs: {"id": 8})
    assert sync.upload_with_diagnostics(
        token="secret", owner="owner", repo="repo", release_id=7, path=tmp_path / "server.bin"
    ) == {"id": 8}


def curl_response(body=None, status="201", code=0, stderr=""):
    attachment = {"id": 8, "name": "server.bin"} if body is None else body
    payload = json.dumps(attachment) if not isinstance(attachment, str) else attachment
    return subprocess.CompletedProcess(
        ["curl"],
        code,
        payload + sync.CURL_METRICS_MARKER + f"{status}\t218\t109.5\t1.25\n",
        stderr,
    )


def test_curl_upload_keeps_token_in_stdin_and_reports_only_numeric_metrics(
    monkeypatch, tmp_path, capsys
):
    directory = tmp_path / "space directory"
    directory.mkdir()
    path = directory / "server.bin"
    path.write_bytes(b"original")
    monkeypatch.setenv("GITEE_UPLOAD_MAX_SECONDS", "120")
    monkeypatch.setenv("GITEE_TOKEN", "secret")
    calls = []

    def curl(command, **kwargs):
        calls.append((command, kwargs))
        return curl_response(body={"id": 8, "name": path.name, "private": "secret"})

    monkeypatch.setattr(sync.subprocess, "run", curl)
    result = sync.upload_with_curl(
        token="secret", owner="owner", repo="repo", release_id=7, path=path
    )
    command, arguments = calls[0]
    assert command == ["curl", "--disable", "--config", "-"]
    assert "secret" not in " ".join(command)
    assert "secret" in arguments["input"]
    assert "GITEE_TOKEN" not in arguments["env"]
    assert arguments["timeout"] == 150
    assert 'max-time = "120"' in arguments["input"]
    assert 'connect-timeout = "20"' in arguments["input"]
    assert 'proto = "=https"' in arguments["input"]
    assert "no-location\n" in arguments["input"]
    assert "insecure" not in arguments["input"]
    assert "retry" not in arguments["input"]
    assert 'form = "file=@\\"' in arguments["input"]
    assert ';filename=\\"server.bin\\";type=application/octet-stream' in arguments["input"]
    assert "%{json}" not in arguments["input"]
    assert result["id"] == 8
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    metrics = json.loads(output.out)
    assert metrics == {
        "asset": "server.bin",
        "transport": "curl",
        "http_code": 201,
        "size_upload": 218,
        "speed_upload": 109.5,
        "time_total": 1.25,
    }


@pytest.mark.parametrize("status,code", [("400", 0), ("000", 28), ("302", 0)])
def test_curl_failures_omit_remote_body_stderr_and_authenticated_url(
    monkeypatch, tmp_path, capsys, status, code
):
    leak = "https://gitee.com/?access_token=secret"
    calls = []

    def curl(command, **kwargs):
        calls.append(command)
        return curl_response(body=leak, stderr=leak, status=status, code=code)

    monkeypatch.setattr(sync.subprocess, "run", curl)
    with pytest.raises(sync.SyncError) as caught:
        sync.upload_with_curl(
            token="secret",
            owner="owner",
            repo="repo",
            release_id=7,
            path=tmp_path / "server.bin",
        )
    output = capsys.readouterr()
    assert "secret" not in str(caught.value) + output.out + output.err
    assert "https:" not in str(caught.value) + output.out + output.err
    assert f"exit {code}" in str(caught.value)
    assert f"HTTP {int(status)}" in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("seconds", ["0", "-1", "1.5", "nan", "120\nverbose", "100000"])
def test_curl_rejects_invalid_absolute_timeout_before_start(monkeypatch, tmp_path, seconds):
    monkeypatch.setenv("GITEE_UPLOAD_MAX_SECONDS", seconds)
    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **k: pytest.fail("invalid timeout"))
    with pytest.raises(sync.SyncError, match="positive integer"):
        sync.upload_with_curl(
            token="secret",
            owner="owner",
            repo="repo",
            release_id=7,
            path=tmp_path / "server.bin",
        )


def test_curl_config_quotes_every_supported_escape():
    assert sync.curl_config_quote('a\\b"\t\n\r\v') == '"a\\\\b\\"\\t\\n\\r\\v"'


def test_curl_timeout_exception_omits_captured_response_and_config(monkeypatch, tmp_path, capsys):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret URL", 1, output="secret", stderr="secret")

    monkeypatch.setattr(sync.subprocess, "run", fail)
    with pytest.raises(sync.SyncError, match="TimeoutExpired") as caught:
        sync.upload_with_curl(
            token="secret",
            owner="owner",
            repo="repo",
            release_id=7,
            path=tmp_path / "server.bin",
        )
    output = capsys.readouterr()
    assert "secret" not in str(caught.value) + output.out + output.err


def test_curl_transport_still_downloads_new_attachment_for_sha_validation(
    target, monkeypatch, capsys
):
    target["attachments"] = []
    monkeypatch.setenv("GITEE_UPLOAD_TRANSPORT", "curl")

    def curl(command, **kwargs):
        item = {"id": 8, "name": "server.bin"}
        target["attachments"].append(item)
        return curl_response(item)

    monkeypatch.setattr(sync.subprocess, "run", curl)
    monkeypatch.setattr(sync, "urlopen", lambda *a, **k: io.BytesIO(b"tampered"))
    with pytest.raises(sync.SyncError, match="SHA256/size mismatch"):
        sync.sync_release(release(), "source/repo", "target", "repo", "secret")
    assert target["api"] == []
    assert "secret" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://example/?token=secret", 403, "secret", {}, None),
        URLError("https://example/?token=secret"),
    ],
)
def test_remote_download_errors_do_not_expose_urls_or_tokens(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(sync, "urlopen", fail)
    with pytest.raises(sync.SyncError) as caught:
        sync.verify_remote("secret", "owner", "repo", 1, {"id": 2}, asset())
    assert "secret" not in str(caught.value)
    assert "https" not in str(caught.value)


def test_dry_run_needs_no_token_and_makes_no_downloads_or_mutations(monkeypatch, capsys):
    monkeypatch.setattr(sync, "verify_tag", lambda *args: None)
    monkeypatch.setattr(sync, "run", lambda *a, **k: pytest.fail("must not download"))
    monkeypatch.setattr(sync, "_api", lambda *a, **k: pytest.fail("must not mutate"))
    result = sync.sync_release(release(), "source/repo", "target", "repo", "", dry_run=True)
    assert result["status"] == "dry-run"
    assert "server.bin" in capsys.readouterr().out


def test_failed_version_report_survives_and_omits_third_party_error_text(
    monkeypatch, tmp_path, capsys
):
    output = tmp_path / "report.json"
    monkeypatch.setenv("GITEE_TOKEN", "secret")
    monkeypatch.setattr(sys, "argv", ["sync", "--all", "--report", str(output)])
    monkeypatch.setattr(sync, "source_releases", lambda *args: [release()])

    def fail(*args, **kwargs):
        raise RuntimeError("https://example/?access_token=secret")

    monkeypatch.setattr(sync, "sync_release", fail)
    assert sync.main() == 1
    assert json.loads(output.read_text())[0]["status"] == "failed"
    assert "secret" not in output.read_text() + capsys.readouterr().err


def test_reads_complete_release_and_asset_metadata_in_creation_order(monkeypatch):
    newer = {**release(), "id": 2, "tag_name": "v2", "created_at": "2026-02-01"}
    calls = []

    def pages(endpoint):
        calls.append(endpoint)
        if endpoint.endswith("/releases?per_page=100"):
            return [newer, {**release(), "draft": True}, release()]
        return [asset()]

    monkeypatch.setattr(sync, "github_pages", pages)
    assert [item["tag_name"] for item in sync.source_releases("source/repo", None)] == [
        "v1.0",
        "v2",
    ]
    assert len(calls) == 3


def test_api_failure_retains_http_status_without_response_secrets(monkeypatch, capsys):
    monkeypatch.setenv("GITEE_TOKEN", "secret")
    monkeypatch.setattr(sys, "argv", ["sync", "--all"])

    def fail(*args, **kwargs):
        raise sync.GiteeError("POST /repos/owner/repo/releases failed HTTP 403: secret")

    monkeypatch.setattr(sync, "source_releases", fail)
    assert sync.main() == 1
    error = capsys.readouterr().err
    assert "HTTP 403" in error
    assert "secret" not in error
