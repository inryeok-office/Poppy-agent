"""Secret-safe structured logging for Agent lifecycle events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

AGENT_STARTING = "agent_starting"
AGENT_REGISTERED = "agent_registered"
RUNTIME_READY = "runtime_ready"
RUNTIME_STOPPING = "runtime_stopping"
RUNTIME_STOPPED = "runtime_stopped"
STARTUP_FAILURE = "startup_failure"

EXECUTION_ASSIGNED = "execution_assigned"
EXECUTION_STARTED = "execution_started"
EXECUTION_COMPLETED = "execution_completed"
EXECUTION_FAILED = "execution_failed"
EXECUTION_CANCELLED = "execution_cancelled"

EXECUTION_CANCELLATION_DETECTED = "execution_cancellation_detected"
EXECUTION_CANCELLATION_REQUESTED = "execution_cancellation_requested"

EXECUTION_RECOVERY_CHECKED = "execution_recovery_checked"
EXECUTION_RECOVERY_NO_ACTIVE = "execution_recovery_no_active"
EXECUTION_RECOVERY_DETECTED = "execution_recovery_detected"
EXECUTION_RECOVERY_STARTED = "execution_recovery_started"
EXECUTION_RECOVERY_COMPLETED = "execution_recovery_completed"
EXECUTION_RECOVERY_FAILED = "execution_recovery_failed"

SERVER_REQUEST_RETRY = "server_request_retry"
SERVER_REQUEST_FAILED = "server_request_failed"
SERVER_RESPONSE_INVALID = "server_response_invalid"

_ALLOWED_CONTEXT = frozenset(
    {
        "agent_id",
        "robot_id",
        "execution_id",
        "execution_status",
        "recovery_action",
        "error_type",
        "attempt",
        "max_attempts",
        "protocol_version",
        "method",
        "path",
        "status_code",
    }
)


def log_event(logger: logging.Logger, level: int, event: str, **context: object) -> None:
    """Emit one event with a deliberately small, allow-listed context."""

    safe_context = {
        key: _safe_value(key, value)
        for key, value in context.items()
        if key in _ALLOWED_CONTEXT and value is not None
    }
    logger.log(level, event, extra={"poppy_event": event, "poppy_context": safe_context})


def configure_logging(level: int = logging.INFO) -> None:
    """Install the stdlib JSON formatter for the Agent process if needed."""

    root = logging.getLogger()
    root.setLevel(level)
    if any(getattr(handler, "_poppy_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler._poppy_json = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


class JsonFormatter(logging.Formatter):
    """Render only structured event fields; arbitrary record data is excluded."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "poppy_event", record.getMessage()),
        }
        context = getattr(record, "poppy_context", None)
        if isinstance(context, dict) and context:
            payload["context"] = {
                key: _safe_value(key, value)
                for key, value in context.items()
                if key in _ALLOWED_CONTEXT and value is not None
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def safe_exception_type(exc: BaseException) -> str:
    """Return exception type only for safe operational context."""

    return type(exc).__name__


def _safe_value(key: str, value: object) -> str | int | float | bool:
    if key == "path" and isinstance(value, str):
        return urlsplit(value).path
    if isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__
