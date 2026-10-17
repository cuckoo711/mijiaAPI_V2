"""deploy/scripts/publish_gitee_release.py 的单元测试。"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "deploy" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from publish_gitee_release import expand_paths  # noqa: E402
import publish_gitee_release as publish  # noqa: E402


def test_expand_paths_keeps_order_and_dedupes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bin").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    result = expand_paths(["a.bin", "b.bin", "a.bin"])
    assert [p.name for p in result] == ["a.bin", "b.bin"]


def test_expand_paths_supports_glob(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mijia-server-linux-x64").write_bytes(b"1")
    (tmp_path / "mijia-server-linux-arm64").write_bytes(b"2")
    (tmp_path / "other.txt").write_bytes(b"3")
    result = expand_paths(["mijia-server-*"])
    assert sorted(p.name for p in result) == [
        "mijia-server-linux-arm64",
        "mijia-server-linux-x64",
    ]


def test_expand_paths_keeps_missing_literal_for_clear_error(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = expand_paths(["does-not-exist.bin"])
    assert [p.name for p in result] == ["does-not-exist.bin"]


def test_create_request_includes_official_required_fields_and_exact_tag_commit(monkeypatch):
    requests = []

    def respond(request, **kwargs):
        requests.append(request)
        return io.BytesIO(json.dumps({"id": 7}).encode())

    monkeypatch.setattr(publish, "urlopen", respond)
    assert publish.create_release(
        token="secret",
        owner="owner",
        repo="repo",
        tag="v1",
        name="Version 1",
        body="Full notes",
        prerelease=False,
        target_commitish="b" * 40,
    ) == {"id": 7}
    fields = parse_qs(requests[0].data.decode())
    assert set(fields) >= {"tag_name", "name", "body", "target_commitish"}
    assert fields["target_commitish"] == ["b" * 40]
    assert fields["auto_create_tag"] == ["false"]


@pytest.mark.parametrize("commit", ["", "main", "tag-object", "b" * 39])
def test_create_rejects_non_commit_target_without_api_call(monkeypatch, commit):
    monkeypatch.setattr(publish, "_api", lambda *a, **k: pytest.fail("must not create release"))
    with pytest.raises(publish.GiteeError, match="commit SHA"):
        publish.create_release(
            token="secret",
            owner="owner",
            repo="repo",
            tag="v1",
            name="v1",
            body="notes",
            prerelease=False,
            target_commitish=commit,
        )


def test_upload_multipart_uses_official_file_field_and_direct_attach_file_response(
    tmp_path, monkeypatch
):
    path = tmp_path / "server.bin"
    path.write_bytes(b"original")
    requests = []
    attachment = {
        "id": 8,
        "name": "server.bin",
        "size": 8,
        "browser_download_url": "https://gitee.com/owner/repo/attach_files/8/download",
    }

    def respond(request, **kwargs):
        requests.append(request)
        return io.BytesIO(json.dumps(attachment).encode())

    monkeypatch.setattr(publish, "urlopen", respond)
    assert (
        publish.upload_attachment(
            token="secret", owner="owner", repo="repo", release_id=7, path=path
        )
        == attachment
    )
    assert b'name="file"; filename="server.bin"' in requests[0].data
    assert b'name="_file"' not in requests[0].data


def test_tag_commit_reads_existing_annotated_tag_commit_with_pagination(monkeypatch):
    calls = []

    def api(method, path, **kwargs):
        calls.append((method, path, kwargs["params"]))
        if kwargs["params"]["page"] == 1:
            return [{"name": f"other-{i}", "commit": {"sha": "a" * 40}} for i in range(100)]
        return [{"name": "v1", "commit": {"sha": "b" * 40}}]

    monkeypatch.setattr(publish, "_api", api)
    assert publish.get_tag_commit(token="secret", owner="owner", repo="repo", tag="v1") == (
        "b" * 40
    )
    assert [call[2]["page"] for call in calls] == [1, 2]
    assert all(call[0] == "GET" for call in calls)


def test_legacy_publish_resolves_existing_tag_before_creating_release(monkeypatch):
    captured = []
    monkeypatch.setattr(publish, "get_release_by_tag", lambda **kwargs: None)
    monkeypatch.setattr(publish, "get_tag_commit", lambda **kwargs: "b" * 40)

    def create(**kwargs):
        captured.append(kwargs)
        return {"id": 7, "tag_name": "v1"}

    monkeypatch.setattr(publish, "create_release", create)
    monkeypatch.setattr(publish, "list_attachments", lambda **kwargs: [])
    publish.publish(
        token="secret",
        owner="owner",
        repo="repo",
        tag="v1",
        title="v1",
        body="notes",
        prerelease=False,
        files=[],
    )
    assert captured[0]["target_commitish"] == "b" * 40


def test_missing_legacy_tag_blocks_release_creation(monkeypatch):
    monkeypatch.setattr(publish, "get_release_by_tag", lambda **kwargs: None)
    monkeypatch.setattr(publish, "_api", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        publish, "create_release", lambda **kwargs: pytest.fail("must not create release")
    )
    with pytest.raises(publish.GiteeError, match="synchronize tags"):
        publish.publish(
            token="secret",
            owner="owner",
            repo="repo",
            tag="missing",
            title="missing",
            body="notes",
            prerelease=False,
            files=[],
        )
