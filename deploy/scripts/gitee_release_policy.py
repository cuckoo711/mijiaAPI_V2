#!/usr/bin/env python3
"""Select the latest supported releases from trusted GitHub Actions events."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_NUMBER = r"(0|[1-9][0-9]*)"
_STABLE_TAG = re.compile(rf"v{_NUMBER}\.{_NUMBER}\.{_NUMBER}")
_ANDROID_TAG = re.compile(rf"v{_NUMBER}\.{_NUMBER}\.{_NUMBER}-android-test\.{_NUMBER}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_RELEASE_WORKFLOWS = ("Build Multi-Platform Release", "Android Test APK")


class PolicyError(RuntimeError):
    """A planning failure whose message is safe to show in Actions logs."""


def _tag_version(tag: Any, android: bool) -> tuple[int, ...] | None:
    if not isinstance(tag, str):
        return None
    match = (_ANDROID_TAG if android else _STABLE_TAG).fullmatch(tag)
    return tuple(int(part) for part in match.groups()) if match else None


def _release_version(release: dict[str, Any], android: bool) -> tuple[int, ...] | None:
    published = release.get("published_at")
    if (
        release.get("draft") is not False
        or release.get("prerelease") is not android
        or not isinstance(published, str)
        or not published.strip()
    ):
        return None
    return _tag_version(release.get("tag_name"), android)


def latest_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return at most the newest stable and Android test release, in that order."""
    selected = []
    for android in (False, True):
        candidates = [
            (version, release)
            for release in releases
            if (version := _release_version(release, android)) is not None
        ]
        if candidates:
            selected.append(max(candidates, key=lambda item: item[0])[1])
    return selected


def _trusted_workflow_run(event: dict[str, Any], repository: str) -> bool:
    upstream = event.get("workflow_run")
    if not isinstance(upstream, dict):
        return False
    head_repository = upstream.get("head_repository")
    if not isinstance(head_repository, dict):
        return False
    return (
        upstream.get("name") in _RELEASE_WORKFLOWS
        and upstream.get("conclusion") == "success"
        and upstream.get("event") in ("push", "workflow_dispatch")
        and head_repository.get("full_name") == repository
        and any(_tag_version(upstream.get("head_branch"), android) for android in (False, True))
    )


def should_sync(event_name: str, event: dict[str, Any], repository: str) -> bool:
    """Reject unrelated events, forks, pull requests, and incomplete publications."""
    if not isinstance(event, dict) or not _REPOSITORY.fullmatch(repository):
        return False
    origin = event.get("repository")
    if origin is not None and (
        not isinstance(origin, dict)
        or ("full_name" in origin and origin["full_name"] != repository)
    ):
        return False
    if event_name == "workflow_run":
        return _trusted_workflow_run(event, repository)
    if event_name == "release":
        release = event.get("release")
        return (
            event.get("action") in ("published", "edited")
            and isinstance(release, dict)
            and any(_release_version(release, android) for android in (False, True))
        )
    # The CLI also checks GITHUB_REF for these default-branch-only entry points.
    return event_name in {"schedule", "workflow_dispatch"}


def _manual_dry_run(event_name: str, event: dict[str, Any]) -> bool:
    if event_name != "workflow_dispatch":
        return False
    inputs = event.get("inputs", {})
    if not isinstance(inputs, dict):
        raise PolicyError("Manual inputs must be an object")
    if set(inputs) - {"dry_run"}:
        raise PolicyError("Only manual dry_run input is supported")
    value = inputs.get("dry_run", False)
    if type(value) is bool:
        return value
    if value in ("true", "false"):
        return value == "true"
    raise PolicyError("Manual dry_run must be true or false")


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PolicyError(f"{command[0]} failed ({type(exc).__name__})") from None
    return result.stdout


def _published_releases(repository: str) -> list[dict[str, Any]]:
    pages = json.loads(
        _run(["gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"])
    )
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise PolicyError("GitHub release response must contain paginated lists")
    releases = [release for page in pages for release in page]
    if not all(isinstance(release, dict) for release in releases):
        raise PolicyError("GitHub release response contains invalid records")
    return releases


def _read_event() -> dict[str, Any]:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        raise PolicyError("Unable to read GitHub event payload") from None
    if not isinstance(event, dict):
        raise PolicyError("GitHub event payload must be an object")
    return event


def _write_outputs(selected: list[dict[str, Any]], source_sha: str, dry_run: bool) -> None:
    include = []
    for release in selected:
        release_id = release.get("id")
        if type(release_id) is not int or release_id <= 0:
            raise PolicyError("Selected GitHub Release requires a positive numeric id")
        include.append({"tag": release["tag_name"], "release_id": release_id})
    outputs = {
        "matrix": json.dumps({"include": include}, separators=(",", ":")),
        "has_releases": str(bool(include)).lower(),
        "source_sha": source_sha,
        "dry_run": str(dry_run).lower(),
    }
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise PolicyError("GITHUB_OUTPUT is required")
    with Path(output_path).open("a", encoding="utf-8") as output:
        for name, value in outputs.items():
            output.write(f"{name}={value}\n")
    print(json.dumps({**outputs, "matrix": {"include": include}}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-repo", required=True)
    args = parser.parse_args()
    try:
        if not _REPOSITORY.fullmatch(args.github_repo):
            raise PolicyError("Invalid GitHub repository name")
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        event = _read_event()
        allowed = should_sync(event_name, event, args.github_repo)
        if event_name in {"schedule", "workflow_dispatch"}:
            allowed = allowed and os.environ.get("GITHUB_REF") == "refs/heads/main"
        dry_run = _manual_dry_run(event_name, event) if allowed else False
        source_sha = _run(["git", "rev-parse", "HEAD"]).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", source_sha):
            raise PolicyError("Git HEAD did not resolve to a commit hash")
        selected = latest_releases(_published_releases(args.github_repo)) if allowed else []
        _write_outputs(selected, source_sha, dry_run)
    except Exception as exc:
        message = str(exc) if isinstance(exc, PolicyError) else type(exc).__name__
        print(f"Gitee release planning failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
