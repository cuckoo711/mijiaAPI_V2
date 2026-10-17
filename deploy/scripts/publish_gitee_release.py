#!/usr/bin/env python3
"""把本地构建产物发布到 Gitee Release（与 GitHub Release 对齐的镜像）。

用法：
    export GITEE_TOKEN=...   # 具备 projects 权限的私人令牌
    python deploy/scripts/publish_gitee_release.py \
        --tag v3.9.1 \
        --notes-file notes.md \
        [--owner cuckoo711] [--repo mijiaAPI] \
        [--prerelease] \
        dist/mijia-server-* SHA256SUMS

行为：
- 若 Gitee 上该 tag 的 Release 不存在则创建；已存在则复用（幂等，可重跑）。
- Gitee 必须已有该标签；创建 Release 时绑定标签的提交，不自动创建或移动标签。
- 附件按文件名对齐：同名附件会先删除再上传，避免重复或半截文件。
- 只依赖标准库；令牌从环境变量 ``GITEE_TOKEN`` 读取，不写入命令行历史。

仓库地址默认 ``cuckoo711/mijiaAPI``（Gitee 镜像仓库名与 GitHub 的
``cuckoo711/mijiaAPI_V2`` 不同）。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://gitee.com/api/v5"
DEFAULT_OWNER = "cuckoo711"
DEFAULT_REPO = "mijiaAPI"
DEFAULT_TIMEOUT = 120


class GiteeError(RuntimeError):
    """Gitee API 调用失败。"""


def _api(
    method: str,
    path: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    file_field: str | None = None,
    file_path: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """调用 Gitee v5 API，返回解析后的 JSON。"""
    url = f"{API_BASE}{path}"
    query = {"access_token": token}
    if params:
        query.update({k: v for k, v in params.items() if v is not None})
    url = f"{url}?{urlencode(query)}"

    data: bytes | None = None
    headers: dict[str, str] = {"Accept": "application/json"}

    if file_field and file_path is not None:
        boundary = f"----mijia{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in (form or {}).items():
            body.extend(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        filename = file_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(file_path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        data = bytes(body)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif form is not None:
        data = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        data = b""
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GiteeError(f"{method} {path} 失败 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise GiteeError(f"{method} {path} 网络错误: {exc.reason}") from exc

    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GiteeError(f"{method} {path} 返回的不是 JSON: {raw[:200]!r}") from exc


def get_release_by_tag(*, token: str, owner: str, repo: str, tag: str) -> dict[str, Any] | None:
    try:
        return _api(
            "GET",
            f"/repos/{owner}/{repo}/releases/tags/{tag}",
            token=token,
        )
    except GiteeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def create_release(
    *,
    token: str,
    owner: str,
    repo: str,
    tag: str,
    name: str,
    body: str,
    prerelease: bool,
    target_commitish: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", target_commitish):
        raise GiteeError("Release target_commitish must be an existing tag commit SHA")
    form: dict[str, Any] = {
        "access_token": token,
        "tag_name": tag,
        "name": name,
        "body": body,
        "prerelease": "true" if prerelease else "false",
        "target_commitish": target_commitish,
        "auto_create_tag": "false",
    }
    return _api(
        "POST",
        f"/repos/{owner}/{repo}/releases",
        token=token,
        form=form,
    )


def get_tag_commit(*, token: str, owner: str, repo: str, tag: str) -> str:
    """Resolve an existing Gitee tag to its commit without creating or moving it."""
    page = 1
    while True:
        tags = _api(
            "GET",
            f"/repos/{owner}/{repo}/tags",
            token=token,
            params={"page": page, "per_page": 100},
        )
        if not isinstance(tags, list):
            raise GiteeError("Gitee tag listing did not return an array")
        for item in tags:
            if item.get("name") == tag:
                commit = (item.get("commit") or {}).get("sha") or ""
                if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
                    raise GiteeError("Gitee tag is missing its commit SHA")
                return commit
        if len(tags) < 100:
            raise GiteeError("Gitee tag does not exist; synchronize tags before releases")
        page += 1


def list_attachments(*, token: str, owner: str, repo: str, release_id: int) -> list[dict[str, Any]]:
    data = _api(
        "GET",
        f"/repos/{owner}/{repo}/releases/{release_id}/attach_files",
        token=token,
    )
    return data if isinstance(data, list) else []


def delete_attachment(
    *, token: str, owner: str, repo: str, release_id: int, attach_id: int
) -> None:
    _api(
        "DELETE",
        f"/repos/{owner}/{repo}/releases/{release_id}/attach_files/{attach_id}",
        token=token,
    )


def upload_attachment(
    *,
    token: str,
    owner: str,
    repo: str,
    release_id: int,
    path: Path,
) -> dict[str, Any]:
    return _api(
        "POST",
        f"/repos/{owner}/{repo}/releases/{release_id}/attach_files",
        token=token,
        file_field="file",
        file_path=path,
        timeout=600,
    )


def publish(
    *,
    token: str,
    owner: str,
    repo: str,
    tag: str,
    title: str,
    body: str,
    prerelease: bool,
    files: list[Path],
) -> dict[str, Any]:
    """创建/复用 Release 并对齐附件，返回最终 Release 摘要。"""
    release = get_release_by_tag(token=token, owner=owner, repo=repo, tag=tag)
    if release is None:
        target_commitish = get_tag_commit(token=token, owner=owner, repo=repo, tag=tag)
        print(f"创建 Gitee Release {tag} ...")
        release = create_release(
            token=token,
            owner=owner,
            repo=repo,
            tag=tag,
            name=title,
            body=body,
            prerelease=prerelease,
            target_commitish=target_commitish,
        )
    else:
        print(f"复用已有 Gitee Release {tag} (id={release.get('id')})")

    release_id = int(release["id"])
    existing = {
        item.get("name"): item
        for item in list_attachments(token=token, owner=owner, repo=repo, release_id=release_id)
        if item.get("name")
    }

    uploaded: list[str] = []
    for path in files:
        if not path.is_file():
            raise GiteeError(f"附件不存在或不是文件: {path}")
        if path.stat().st_size == 0:
            raise GiteeError(f"附件为空，拒绝上传: {path}")

        name = path.name
        prior = existing.get(name)
        if prior is not None:
            attach_id = prior.get("id")
            if attach_id is None:
                raise GiteeError(f"已有附件缺少 id，无法替换: {name}")
            print(f"替换同名附件 {name} ...")
            delete_attachment(
                token=token,
                owner=owner,
                repo=repo,
                release_id=release_id,
                attach_id=int(attach_id),
            )
        else:
            print(f"上传附件 {name} ({path.stat().st_size} bytes) ...")
        result = upload_attachment(
            token=token,
            owner=owner,
            repo=repo,
            release_id=release_id,
            path=path,
        )
        uploaded.append(result.get("name") or name)

    return {
        "id": release_id,
        "tag_name": release.get("tag_name") or tag,
        "html_url": release.get("html_url"),
        "attachments": uploaded,
    }


def expand_paths(raw: list[str]) -> list[Path]:
    """展开通配符路径并去重，保持输入顺序。"""
    seen: set[Path] = set()
    result: list[Path] = []
    for item in raw:
        matches = sorted(Path().glob(item)) if any(ch in item for ch in "*?[") else [Path(item)]
        if not matches and not Path(item).exists():
            # glob 无匹配且路径不存在时仍交给 publish 报错，保留可读路径
            matches = [Path(item)]
        for match in matches:
            resolved = match if match.exists() else match
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append(resolved)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="要上传的本地产物路径（可含通配符）")
    parser.add_argument("--tag", required=True, help="版本标签，如 v3.9.1")
    parser.add_argument("--notes-file", help="Release 描述文件（markdown）")
    parser.add_argument("--title", help="Release 标题，默认使用标签名")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="Gitee 仓库属主")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Gitee 仓库名")
    parser.add_argument(
        "--prerelease",
        action="store_true",
        help="标记为预发布（例如 Android 测试包）",
    )
    args = parser.parse_args()

    token = os.environ.get("GITEE_TOKEN", "").strip()
    if not token:
        print(
            "缺少环境变量 GITEE_TOKEN。请在仓库 Secret 中配置具备 projects 权限的"
            " Gitee 私人令牌，再重试发布。",
            file=sys.stderr,
        )
        return 2

    body = "发布产物镜像自 GitHub Actions 构建。"
    if args.notes_file:
        notes_path = Path(args.notes_file)
        if not notes_path.is_file():
            print(f"找不到 --notes-file: {notes_path}", file=sys.stderr)
            return 2
        content = notes_path.read_text(encoding="utf-8").strip()
        if content:
            body = content

    files = expand_paths(args.files)
    missing = [path for path in files if not path.is_file()]
    if missing:
        print(f"以下产物不存在: {[str(p) for p in missing]}", file=sys.stderr)
        return 2

    title = args.title or args.tag
    try:
        summary = publish(
            token=token,
            owner=args.owner,
            repo=args.repo,
            tag=args.tag,
            title=title,
            body=body,
            prerelease=args.prerelease,
            files=files,
        )
    except GiteeError as exc:
        print(f"发布到 Gitee 失败: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        f"已同步到 {summary.get('html_url') or f'https://gitee.com/{args.owner}/{args.repo}/releases'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
