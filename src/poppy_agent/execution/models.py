"""Transport-independent execution models and validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

SUPPORTED_EXECUTION_PROTOCOL_VERSION = 1


class UnsupportedExecutionProtocolError(ValueError):
    """Raised when an execution task uses an unsupported protocol version."""


@dataclass(frozen=True, slots=True)
class ExecutionTask:
    """Executable metadata after its transport-specific assignment has been validated."""

    execution_id: UUID
    robot_id: UUID
    protocol_version: int

    def __post_init__(self) -> None:
        if (
            type(self.protocol_version) is not int
            or self.protocol_version != SUPPORTED_EXECUTION_PROTOCOL_VERSION
        ):
            raise UnsupportedExecutionProtocolError(
                "unsupported execution protocol version: "
                f"{self.protocol_version}; supported version is "
                f"{SUPPORTED_EXECUTION_PROTOCOL_VERSION}"
            )


class ExecutionStatus(StrEnum):
    """Final outcomes returned by an execution executor."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Final outcome for one execution task."""

    execution_id: UUID
    status: ExecutionStatus
    failure_reason: str | None = None
