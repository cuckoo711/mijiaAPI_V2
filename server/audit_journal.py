"""Durable recovery of audit events when their SQLite insert fails."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from typing import Any, Callable, Optional
import uuid

from server.logging_utils import get_server_logger

logger = get_server_logger(__name__)
MAX_EVENT_BYTES = 1024 * 1024
EVENT_FIELDS = {
    "id",
    "occurred_at",
    "actor_type",
    "actor_id",
    "action",
    "source_ip",
    "request_path",
    "result",
    "duration_ms",
    "request_id",
    "metadata",
}
SENSITIVE_FIELDS = {
    "password",
    "currentpassword",
    "newpassword",
    "token",
    "servicetoken",
    "passtoken",
    "accesstoken",
    "refreshtoken",
    "secrettoken",
    "secret",
    "ssecurity",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "apikey",
}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:password|pass[_-]?token|service[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|token|secret|ssecurity)\s*[=:]\s*)[^\s&;,]+"
)


def _safe_text(value: str) -> str:
    value = SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    return re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)


def _safe_metadata_object(value: dict[str, Any], depth: int) -> dict[str, Any]:
    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        sensitive = normalized in SENSITIVE_FIELDS or normalized.endswith(
            ("password", "token", "secret")
        )
        result[key] = "[REDACTED]" if sensitive else _safe_metadata(item, depth + 1)
    return result


def _safe_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return _safe_metadata_object(value, depth)
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    return "[UNSUPPORTED]"


def prepare_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate the recovery schema and keep secrets out of both audit stores."""
    if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
        raise ValueError("Invalid audit event fields")
    prepared = dict(event)
    event_id = prepared["id"]
    if not isinstance(event_id, str) or str(uuid.UUID(event_id)) != event_id:
        raise ValueError("Invalid audit event id")
    occurred_at = prepared["occurred_at"]
    if not isinstance(occurred_at, str) or datetime.fromisoformat(occurred_at).tzinfo is None:
        raise ValueError("Invalid audit event timestamp")
    for field in ("actor_type", "action", "result"):
        _validate_text(prepared, field, required=True)
    for field in ("actor_id", "source_ip", "request_path", "request_id"):
        _validate_text(prepared, field, required=False)
    duration = prepared["duration_ms"]
    if duration is not None and (type(duration) is not int or not 0 <= duration < 2**63):
        raise ValueError("Invalid audit duration")
    if not isinstance(prepared["metadata"], dict):
        raise ValueError("Invalid audit metadata")
    prepared["metadata"] = _safe_metadata(prepared["metadata"])
    encoded = json.dumps(prepared, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError("Audit event exceeds size limit")
    return prepared


def _validate_text(event: dict[str, Any], field: str, *, required: bool) -> None:
    value = event[field]
    if value is None and not required:
        return
    if not isinstance(value, str) or len(value) > 2048 or (required and not value.strip()):
        raise ValueError("Invalid audit text field")
    event[field] = _safe_text(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate audit JSON field")
        result[key] = value
    return result


class AuditJournal:
    """Atomic private files; only audit inserts are replayed, never operations."""

    def __init__(self, data_dir: Path):
        self.path = Path(os.path.abspath(data_dir)) / "audit-pending"
        self._lock = threading.RLock()
        self._unavailable_count = 0

    @property
    def unavailable_count(self) -> int:
        with self._lock:
            return self._unavailable_count

    def record_unavailable(self) -> None:
        with self._lock:
            self._unavailable_count += 1

    @staticmethod
    def _event_id(value: str) -> str:
        canonical = str(uuid.UUID(value))
        if canonical != value:
            raise ValueError("Invalid audit event id")
        return canonical

    def _check_directory(self, *, create: bool = False) -> bool:
        # Resolve no symlinks: reject aliases and Windows junctions in every
        # ancestor before reading or writing the private recovery directory.
        for path in (*reversed(self.path.parents), self.path):
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                continue
            is_junction = getattr(path, "is_junction", lambda: False)
            if stat.S_ISLNK(mode) or is_junction() or not stat.S_ISDIR(mode):
                raise OSError("Unsafe audit recovery directory")
        if create:
            self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._check_directory()
            if os.name == "posix":
                self.path.chmod(0o700)
        return self.path.exists()

    @contextmanager
    def _directory_fd(self, *, create: bool = False):
        """Anchor POSIX operations to a directory opened without following links."""
        if os.name != "posix":
            self._check_directory(create=create)
            yield None
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(self.path.anchor, flags)
        try:
            for part in self.path.parts[1:]:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                        os.fsync(descriptor)  # Persist the new directory entry too.
                    except FileExistsError:
                        pass  # A concurrent store may have created the directory.
                    child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            if create:
                os.fchmod(descriptor, 0o700)
            yield descriptor
        finally:
            os.close(descriptor)

    def _stat_file(self, name: str, descriptor: Optional[int]):
        if descriptor is None:
            return (self.path / name).lstat()
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)

    def _unlink_file(self, name: str, descriptor: Optional[int]) -> None:
        try:
            if descriptor is None:
                (self.path / name).unlink()
            else:
                os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            pass

    def save(self, event: dict[str, Any]) -> None:
        event = prepare_audit_event(event)
        payload = json.dumps({"version": 1, "event": event}, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("Audit recovery event exceeds size limit")
        with self._lock, self._directory_fd(create=True) as directory:
            target_name = f"{event['id']}.json"
            try:
                if not stat.S_ISREG(self._stat_file(target_name, directory).st_mode):
                    raise OSError("Unsafe audit recovery file")
            except FileNotFoundError:
                pass
            if directory is None:
                descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.path)
                temporary_name = Path(name).name
            else:
                temporary_name = f".pending-{uuid.uuid4().hex}"
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    if os.name == "posix":
                        os.fchmod(handle.fileno(), 0o600)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._check_directory()
                if directory is None:
                    os.replace(self.path / temporary_name, self.path / target_name)
                else:
                    os.replace(
                        temporary_name, target_name, src_dir_fd=directory, dst_dir_fd=directory
                    )
                self._sync_directory(directory)
            finally:
                self._unlink_file(temporary_name, directory)

    def _sync_directory(self, descriptor: Optional[int] = None) -> None:
        if os.name != "posix":
            return
        if descriptor is not None:
            os.fsync(descriptor)
            return
        with self._directory_fd() as directory:
            os.fsync(directory)

    def _read_event(self, path: Path) -> dict[str, Any]:
        self._event_id(path.stem)
        with self._directory_fd() as directory:
            before = self._stat_file(path.name, directory)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EVENT_BYTES:
                raise ValueError("Invalid audit recovery file")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            filename = path if directory is None else path.name
            descriptor = os.open(filename, flags, dir_fd=directory)
            with os.fdopen(descriptor, "rb") as handle:
                current = os.fstat(handle.fileno())
                if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (
                    current.st_dev,
                    current.st_ino,
                ):
                    raise ValueError("Audit recovery file changed while opening")
                raw = handle.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise ValueError("Audit recovery event exceeds size limit")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "event"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
        ):
            raise ValueError("Invalid audit recovery envelope")
        event = prepare_audit_event(payload["event"])
        if event["id"] != path.stem or event != payload["event"]:
            raise ValueError("Invalid or unsafe audit recovery event")
        return event

    def get(self, event_id: str) -> Optional[dict[str, Any]]:
        try:
            path = self.path / f"{self._event_id(event_id)}.json"
        except (ValueError, AttributeError, TypeError):
            return None
        with self._lock:
            try:
                return self._read_event(path)
            except FileNotFoundError:
                return None
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self._quarantine(path)
                return None
            except OSError as exc:
                logger.warning("audit recovery lookup unavailable (%s)", type(exc).__name__)
                return None

    def _entries(self, suffix: str) -> list[Path]:
        with (
            self._directory_fd() as descriptor,
            os.scandir(self.path if descriptor is None else descriptor) as entries,
        ):
            return [self.path / entry.name for entry in entries if entry.name.endswith(suffix)]

    def replay(self, persist: Callable[[dict[str, Any]], None], limit: int = 100) -> dict[str, int]:
        delivered = 0
        with self._lock:
            try:
                paths = sorted(self._entries(".json")) if self._check_directory() else []
                for path in paths:
                    if delivered >= max(0, limit):
                        break
                    delivered += self._deliver(path, persist)
                if delivered:
                    self._sync_directory()
            except Exception as exc:
                # Recovery IO failures must not replace the original control result.
                logger.warning("audit replay paused (%s)", type(exc).__name__)
        return {"delivered": delivered, **self.status()}

    def _deliver(self, path: Path, persist: Callable[[dict[str, Any]], None]) -> int:
        try:
            event = self._read_event(path)
        except FileNotFoundError:
            return 0  # Another store may have committed and removed it already.
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._quarantine(path)
            return 0
        except OSError as exc:
            logger.warning("audit recovery file unavailable (%s)", type(exc).__name__)
            return 0
        persist(event)  # DB failure leaves this and following valid events queued.
        with self._directory_fd() as directory:
            self._unlink_file(path.name, directory)
        return 1

    def _quarantine(self, path: Path) -> None:
        try:
            with self._directory_fd() as directory:
                invalid_name = f"{uuid.uuid4().hex}.invalid"
                # Rename a link itself; never inspect or modify its target.
                if directory is None:
                    path.rename(self.path / invalid_name)
                else:
                    os.rename(path.name, invalid_name, src_dir_fd=directory, dst_dir_fd=directory)
                self._sync_directory(directory)
        except FileNotFoundError:
            return
        except OSError:
            self.record_unavailable()
        logger.error("invalid audit recovery event requires operator review")

    def status(self) -> dict[str, int]:
        with self._lock:
            try:
                exists = self._check_directory()
                pending = len(self._entries(".json")) if exists else 0
                invalid = len(self._entries(".invalid")) if exists else 0
            except OSError:
                pending, invalid = 0, 1
            return {"pending": pending, "invalid": invalid, "unavailable": self._unavailable_count}
