#!/usr/bin/env python3
"""Mirror published GitHub Releases without rebuilding or replacing attachments."""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from publish_gitee_release import (
    API_BASE,
    DEFAULT_OWNER,
    DEFAULT_REPO,
    GiteeError,
    _api,
    get_release_by_tag,
    list_attachments,
    upload_attachment,
)

WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
CURL_METRICS_MARKER = "\n__MIJIA_GITEE_UPLOAD_METRICS__\t"


class SyncError(RuntimeError):
    """An actionable error which contains no credentials or remote response body."""


def run(command: list[str], timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError(f"{command[0]} failed ({type(exc).__name__})") from None
    return result.stdout


def github_pages(endpoint: str) -> list[dict[str, Any]]:
    pages = json.loads(run(["gh", "api", "--paginate", "--slurp", endpoint]))
    return [item for page in pages for item in page]


def source_releases(repository: str, tag: str | None) -> list[dict[str, Any]]:
    releases = [
        r
        for r in github_pages(f"repos/{repository}/releases?per_page=100")
        if not r.get("draft") and (tag is None or r["tag_name"] == tag)
    ]
    if tag is not None and not releases:
        raise SyncError("Requested published GitHub Release was not found")
    for release in releases:
        release["assets"] = github_pages(
            f"repos/{repository}/releases/{int(release['id'])}/assets?per_page=100"
        )
    return sorted(releases, key=lambda release: (release["created_at"], release["tag_name"]))


def assets_by_name(assets: list[dict[str, Any]], source: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    folded: set[str] = set()
    for asset in assets:
        name = asset.get("name")
        if (
            not isinstance(name, str)
            or len(name) > 255
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name)
            or name.endswith((".", " "))
            or name.split(".", 1)[0].upper() in WINDOWS_RESERVED
        ):
            raise SyncError("Unsafe attachment filename")
        if name.casefold() in folded:
            raise SyncError("Duplicate attachment filename")
        folded.add(name.casefold())
        if source and (
            type(asset.get("size")) is not int
            or asset["size"] <= 0
            or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", asset.get("digest") or "")
        ):
            raise SyncError(f"Attachment requires a positive size and source SHA256: {name}")
        result[name] = asset
    return result


def tag_refs(repository_url: str, tag: str) -> dict[str, str]:
    if (
        not tag
        or tag.startswith("-")
        or any(c.isspace() for c in tag)
        or ".." in tag
        or any(c in tag for c in "~^:?*[\\")
    ):
        raise SyncError("Invalid release tag")
    ref = f"refs/tags/{tag}"
    output = run(["git", "ls-remote", repository_url, ref, f"{ref}^{{}}"])
    return {
        name: sha
        for line in output.splitlines()
        for sha, name in [line.split()]
        if name in {ref, f"{ref}^{{}}"}
    }


def verify_tag(repository: str, owner: str, repo: str, tag: str) -> str:
    source = tag_refs(f"https://github.com/{repository}.git", tag)
    target = tag_refs(f"https://gitee.com/{owner}/{repo}.git", tag)
    if not source or source != target:
        raise SyncError("Exact GitHub/Gitee tag refs differ; synchronize tags before releases")
    ref = f"refs/tags/{tag}"
    return source.get(f"{ref}^{{}}") or source[ref]


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_local(directory: Path, assets: dict[str, Any]) -> None:
    if {path.name for path in directory.iterdir()} != set(assets):
        raise SyncError("Downloaded attachment names differ from GitHub metadata")
    for name, asset in assets.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != asset["size"]:
            raise SyncError(f"Downloaded attachment size/type mismatch: {name}")
        if file_digest(path) != asset["digest"].split(":", 1)[1].lower():
            raise SyncError(f"Downloaded attachment SHA256 mismatch: {name}")


def attachments(token: str, owner: str, repo: str, release_id: int) -> dict[str, Any]:
    items = list_attachments(token=token, owner=owner, repo=repo, release_id=release_id)
    # Gitee's default page contains 20 items. Explicitly page larger releases.
    if len(items) >= 20:
        items = []
        page = 1
        while True:
            batch = _api(
                "GET",
                f"/repos/{owner}/{repo}/releases/{release_id}/attach_files",
                token=token,
                params={"page": page, "per_page": 100},
            )
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    return assets_by_name(items)


def verify_remote(
    token: str,
    owner: str,
    repo: str,
    release_id: int,
    remote: dict[str, Any],
    asset: dict[str, Any],
) -> None:
    attach_id = int(remote["id"])
    url = (
        f"{API_BASE}/repos/{owner}/{repo}/releases/{release_id}/attach_files/"
        f"{attach_id}/download?{urlencode({'access_token': token})}"
    )
    digest, size = hashlib.sha256(), 0
    try:
        with urlopen(url, timeout=120) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if size > asset["size"]:
                    raise SyncError("Gitee attachment exceeds source size")
    except HTTPError as exc:
        raise SyncError(f"Gitee attachment download failed (HTTP {exc.code})") from None
    except SyncError:
        raise
    except Exception as exc:
        raise SyncError(f"Gitee attachment download failed ({type(exc).__name__})") from None
    if size != asset["size"] or digest.hexdigest() != asset["digest"].split(":", 1)[1].lower():
        raise SyncError(f"Gitee attachment SHA256/size mismatch: {asset['name']}")


def curl_config_quote(value: str) -> str:
    """Quote a single curl config value, including control characters."""
    escapes = {"\\": "\\\\", '"': '\\"', "\t": "\\t", "\n": "\\n", "\r": "\\r", "\v": "\\v"}
    return '"' + "".join(escapes.get(character, character) for character in value) + '"'


def curl_upload_config(
    *, token: str, owner: str, repo: str, release_id: int, path: Path
) -> tuple[str, int]:
    """Keep the authenticated URL in stdin, never argv or a config file."""
    if (
        not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (owner, repo))
        or type(release_id) is not int
        or release_id <= 0
    ):
        raise SyncError("Curl upload failed (ValueError)")
    assets_by_name([{"name": path.name}])
    seconds = os.environ.get("GITEE_UPLOAD_MAX_SECONDS", "600")
    if not re.fullmatch(r"[1-9][0-9]{0,4}", seconds):
        raise SyncError("GITEE_UPLOAD_MAX_SECONDS must be a positive integer up to 99999")
    url = f"{API_BASE}/repos/{owner}/{repo}/releases/{release_id}/attach_files?" + urlencode(
        {"access_token": token}
    )
    # --form has its own quoting layer inside the curl config value.
    source = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    form = f'file=@"{source}";filename="{path.name}";type={mime}'
    options = {
        "url": url,
        "request": "POST",
        "header": "Accept: application/json",
        "form": form,
        "connect-timeout": "20",
        "max-time": seconds,
        "proto": "=https",
        "max-redirs": "0",
        "write-out": CURL_METRICS_MARKER
        + "%{http_code}\t%{size_upload}\t%{speed_upload}\t%{time_total}\n",
    }
    config = "silent\nno-location\n" + "".join(
        f"{key} = {curl_config_quote(value)}\n" for key, value in options.items()
    )
    return config, int(seconds)


def curl_upload_result(result: subprocess.CompletedProcess[str], path: Path) -> dict[str, Any]:
    body, marker, fields = result.stdout.rpartition(CURL_METRICS_MARKER)
    numeric = re.fullmatch(r"([0-9]{3})\t([0-9]{1,20})\t([0-9.]{1,30})\t([0-9.]{1,30})\n?", fields)
    if not marker or numeric is None:
        raise SyncError(f"Curl upload failed (exit {result.returncode}, ValueError)")
    try:
        http_code, size_upload = int(numeric[1]), int(numeric[2])
        speed_upload, time_total = float(numeric[3]), float(numeric[4])
    except ValueError:
        raise SyncError(f"Curl upload failed (exit {result.returncode}, ValueError)") from None
    print(
        json.dumps(
            {
                "asset": path.name,
                "transport": "curl",
                "http_code": http_code,
                "size_upload": size_upload,
                "speed_upload": speed_upload,
                "time_total": time_total,
            }
        ),
        flush=True,
    )
    if result.returncode != 0 or not 200 <= http_code < 300:
        raise SyncError(f"Curl upload failed (exit {result.returncode}, HTTP {http_code})")
    try:
        attachment = json.loads(body)
        if (
            not isinstance(attachment, dict)
            or type(attachment.get("id")) is not int
            or attachment["id"] <= 0
            or attachment.get("name") != path.name
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise SyncError("Curl upload failed (ValueError)") from None
    return attachment


def upload_with_curl(
    *, token: str, owner: str, repo: str, release_id: int, path: Path
) -> dict[str, Any]:
    config, seconds = curl_upload_config(
        token=token, owner=owner, repo=repo, release_id=release_id, path=path
    )
    try:
        result = subprocess.run(
            ["curl", "--disable", "--config", "-"],
            input=config,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=seconds + 30,
            check=False,
            env={key: value for key, value in os.environ.items() if key != "GITEE_TOKEN"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError(f"Curl upload failed ({type(exc).__name__})") from None
    return curl_upload_result(result, path)


def upload_with_diagnostics(
    *, token: str, owner: str, repo: str, release_id: int, path: Path
) -> dict[str, Any]:
    """Report only stack locations for slow CI uploads, never request data or locals."""
    diagnostics = os.environ.get("GITHUB_ACTIONS") == "true"
    if diagnostics:
        faulthandler.dump_traceback_later(120, repeat=True, file=sys.__stderr__)
    try:
        transport = (
            upload_with_curl
            if os.environ.get("GITEE_UPLOAD_TRANSPORT") == "curl"
            else upload_attachment
        )
        return transport(token=token, owner=owner, repo=repo, release_id=release_id, path=path)
    finally:
        if diagnostics:
            faulthandler.cancel_dump_traceback_later()


def sync_release(
    release: dict[str, Any],
    repository: str,
    owner: str,
    repo: str,
    token: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    tag = release["tag_name"]
    # Verify the upload path with small checksum/report files before large binaries.
    assets = dict(
        sorted(
            assets_by_name(release["assets"], source=True).items(), key=lambda item: item[1]["size"]
        )
    )
    target_commitish = verify_tag(repository, owner, repo, tag)
    summary = {
        "tag": tag,
        "asset_count": len(assets),
        "verified": 0,
        "uploaded": 0,
        "skipped": 0,
        "status": "dry-run" if dry_run else "verified",
    }
    if dry_run:
        print(json.dumps({"tag": tag, "attachments": list(assets)}, ensure_ascii=False))
        return summary
    with TemporaryDirectory(prefix="gitee-release-") as temporary:
        directory = Path(temporary)
        if assets:
            print(
                json.dumps({"tag": tag, "stage": "download", "asset_count": len(assets)}),
                flush=True,
            )
            run(
                ["gh", "release", "download", tag, "--repo", repository, "--dir", str(directory)],
                timeout=600,
            )
        verify_local(directory, assets)
        print(json.dumps({"tag": tag, "stage": "release-metadata"}), flush=True)
        target = get_release_by_tag(token=token, owner=owner, repo=repo, tag=quote(tag, safe=""))
        metadata = {
            "tag_name": tag,
            "name": release.get("name") or "",
            "body": release.get("body") or "",
            "prerelease": "true" if release.get("prerelease") else "false",
        }
        endpoint = f"/repos/{owner}/{repo}/releases"
        if target is None:
            # Tag existence and both annotated-tag refs were checked above.
            target = _api(
                "POST",
                endpoint,
                token=token,
                form={
                    **metadata,
                    "target_commitish": target_commitish,
                    "auto_create_tag": "false",
                },
            )
        release_id = int(target["id"])
        existing = attachments(token, owner, repo, release_id)
        if set(existing) - set(assets):
            raise SyncError("Gitee release contains unexpected attachments; refusing to delete")
        for name, asset in assets.items():
            print(
                json.dumps(
                    {"tag": tag, "stage": "verify" if name in existing else "upload", "asset": name}
                ),
                flush=True,
            )
            if name in existing:
                verify_remote(token, owner, repo, release_id, existing[name], asset)
                summary["skipped"] += 1
            else:
                uploaded = upload_with_diagnostics(
                    token=token,
                    owner=owner,
                    repo=repo,
                    release_id=release_id,
                    path=directory / name,
                )
                verify_remote(token, owner, repo, release_id, uploaded, asset)
                summary["uploaded"] += 1
            summary["verified"] += 1
            print(json.dumps({"tag": tag, "stage": "verified", "asset": name}), flush=True)
        final = attachments(token, owner, repo, release_id)
        if set(final) != set(assets):
            raise SyncError("Final Gitee attachment names differ from source")
        _api("PATCH", f"{endpoint}/{release_id}", token=token, form=metadata)
        target = get_release_by_tag(token=token, owner=owner, repo=repo, tag=quote(tag, safe=""))
        if (
            target is None
            or target.get("name") != metadata["name"]
            or (target.get("body") or "") != metadata["body"]
            or bool(target.get("prerelease")) != bool(release.get("prerelease"))
        ):
            raise SyncError("Final Gitee release metadata differs from source")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--tag")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--github-repo", default="cuckoo711/mijiaAPI_V2")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args()
    token = os.environ.get("GITEE_TOKEN", "").strip()
    report: list[dict[str, Any]] = []
    try:
        if not args.dry_run and not token:
            raise SyncError("GITEE_TOKEN is required for synchronization")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.github_repo) or not all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (args.owner, args.repo)
        ):
            raise SyncError("Invalid repository name")
        for release in source_releases(args.github_repo, args.tag):
            entry = {
                "tag": release["tag_name"],
                "asset_count": len(release["assets"]),
                "status": "failed",
            }
            report.append(entry)
            try:
                entry.update(
                    sync_release(
                        release, args.github_repo, args.owner, args.repo, token, args.dry_run
                    )
                )
            finally:
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            print(json.dumps(entry, ensure_ascii=False))
    except Exception as exc:
        # Third-party exception text can include request URLs or response bodies.
        message = f"Sync failed ({type(exc).__name__})"
        if isinstance(exc, SyncError):
            message = str(exc)
        elif isinstance(exc, GiteeError):
            status = re.search(r"HTTP (\d{3})", str(exc))
            message = f"Gitee API failed (HTTP {status[1]})" if status else "Gitee API failed"
        print(
            message,
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
