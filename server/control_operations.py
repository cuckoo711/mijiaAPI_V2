"""Shared control receipts and outcome auditing for API keys and administrators."""

from __future__ import annotations

import time
import logging
from typing import Any, Callable, Optional
import uuid

from fastapi import Request
from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError
from server.logging_utils import get_server_logger
from server.store import ServerStore

logger = get_server_logger(__name__)


def control_audit_status(result: dict[str, Any], expected_count: Optional[int]) -> str:
    def succeeded(item: Any) -> bool:
        return isinstance(item, dict) and type(item.get("code")) is int and item["code"] == 0

    if expected_count is not None:
        items = result.get("items")
        if not isinstance(items, list):
            return "failed"
        count = sum(succeeded(item) for item in items)
        if expected_count > 0 and len(items) == expected_count and count == expected_count:
            return "success"
        return "warning" if count else "failed"
    if "success" in result:
        return "success" if result["success"] is True else "failed"
    return "success" if succeeded(result.get("result")) else "failed"


def run_audited_control(
    store: ServerStore,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    metadata: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
    request: Optional[Request] = None,
    expected_count: Optional[int] = None,
    audit_logger: Optional[logging.Logger] = None,
) -> dict[str, Any]:
    operation_id = str(uuid.uuid4())
    started = time.monotonic()
    if request is not None:
        request.state.operation_id = operation_id
        request.state.audit_delivery = "unavailable"

    def record(status: str, details: dict[str, Any]) -> None:
        delivery = "unavailable"
        try:
            event = store.add_audit(
                action,
                status,
                actor_type=actor_type,
                actor_id=actor_id,
                event_id=operation_id,
                metadata=details,
                source_ip=(
                    (getattr(request.state, "source_ip", "")[:2048] or None) if request else None
                ),
                request_id=getattr(request.state, "request_id", None) if request else None,
                request_path=request.url.path[:2048] if request else None,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            delivery = event.get("delivery", "stored")
        except Exception as exc:
            (audit_logger or logger).warning(
                "failed to audit control action %s (%s)", action, type(exc).__name__
            )
        if request is not None:
            request.state.audit_delivery = delivery

    try:
        result = operation()
    except ExecutionUnknownError as exc:
        details = {**metadata, "error_type": type(exc).__name__, "retry_safe": False}
        completed_count = exc.context.get("completed_count")
        if type(completed_count) is int and completed_count >= 0:
            details["completed_count"] = completed_count
        record("unknown", details)
        raise
    except Exception as exc:
        record("failed", {**metadata, "error_type": type(exc).__name__})
        raise
    record(control_audit_status(result, expected_count), metadata)
    return result
