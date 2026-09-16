"""Hardware-independent safety validation for command execution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from poppy_agent.command import (
    CommandType,
    HighLevelCommand,
    MoveParameters,
    PostureParameters,
    PresetParameters,
    StopParameters,
    TurnParameters,
    WaitParameters,
)
from poppy_agent.execution.models import (
    SUPPORTED_EXECUTION_PROTOCOL_VERSION,
    ExecutionTask,
)

if TYPE_CHECKING:
    from poppy_agent.execution.executor import CommandExecutionTarget


class SafetyValidationError(ValueError):
    """Raised when a command program cannot be safely sent to its target."""


@dataclass(frozen=True, slots=True)
class CommandSafetyPolicy:
    """Software-level command policy without hardware-specific numeric limits."""

    preset_allowlist: frozenset[str] | None = None
    allow_preset_trace: bool = False

    @classmethod
    def for_mock_trace(cls) -> CommandSafetyPolicy:
        """Allow PRESET only as a trace-only Mock behavior."""
        return cls(allow_preset_trace=True)

    def __post_init__(self) -> None:
        if self.preset_allowlist is not None and any(
            not isinstance(code, str) or not code.strip() for code in self.preset_allowlist
        ):
            raise ValueError("preset_allowlist must contain non-blank strings")


class ExecutionSafetyValidator:
    """Preflight a typed execution task before any target dispatch occurs."""

    def __init__(
        self,
        target: CommandExecutionTarget,
        *,
        policy: CommandSafetyPolicy | None = None,
        bound_robot_id: UUID | None = None,
    ) -> None:
        self._target = target
        self._policy = policy or CommandSafetyPolicy()
        self._bound_robot_id = bound_robot_id

    def validate(self, task: ExecutionTask) -> None:
        """Validate the complete task before allowing target execution."""
        if task.protocol_version != SUPPORTED_EXECUTION_PROTOCOL_VERSION:
            raise SafetyValidationError(
                "unsupported execution protocol version: "
                f"{task.protocol_version}; supported version is "
                f"{SUPPORTED_EXECUTION_PROTOCOL_VERSION}"
            )
        if self._bound_robot_id is not None and task.robot_id != self._bound_robot_id:
            raise SafetyValidationError("execution robot identity does not match Agent binding")

        for index, command in enumerate(task.command_program.commands):
            self._validate_command(index, command)

    def _validate_command(self, index: int, command: HighLevelCommand) -> None:
        if type(command.sequence) is not int or command.sequence != index:
            raise SafetyValidationError("command sequence is not contiguous")
        if not isinstance(command.source_block_id, str) or not command.source_block_id.strip():
            raise SafetyValidationError("command sourceBlockId must be non-blank")
        if not isinstance(command.type, CommandType):
            raise SafetyValidationError("command type is not supported")
        self._validate_parameters(command)
        try:
            supported = self._target.supports(command.type)
        except Exception as exc:
            raise SafetyValidationError(
                f"execution target support is unavailable for {command.type.value}"
            ) from exc
        if supported is not True:
            raise SafetyValidationError(
                f"execution target does not support command type {command.type.value}"
            )

    def _validate_parameters(self, command: HighLevelCommand) -> None:
        parameters = command.parameters
        if command.type is CommandType.WAIT:
            valid = isinstance(parameters, WaitParameters) and _finite_number(
                parameters.duration_seconds
            )
        elif command.type is CommandType.MOVE:
            valid = isinstance(parameters, MoveParameters) and _finite_number(
                parameters.distance_meters
            )
        elif command.type is CommandType.TURN:
            valid = isinstance(parameters, TurnParameters) and _finite_number(
                parameters.angle_degrees
            )
        elif command.type is CommandType.STOP:
            valid = isinstance(parameters, StopParameters)
        elif command.type is CommandType.POSTURE:
            valid = isinstance(parameters, PostureParameters)
        else:
            valid = isinstance(parameters, PresetParameters)
        if not valid:
            raise SafetyValidationError(
                f"{command.type.value} parameters are not a valid typed parameter model"
            )
        if command.type is CommandType.PRESET:
            self._validate_preset(command)

    def _validate_preset(self, command: HighLevelCommand) -> None:
        if not isinstance(command.parameters, PresetParameters):
            raise SafetyValidationError("PRESET parameters are not typed PresetParameters")
        code = command.parameters.preset_code
        if self._policy.allow_preset_trace:
            return
        if self._policy.preset_allowlist is None:
            raise SafetyValidationError(
                "PRESET execution is disabled until an explicit allow-list is configured"
            )
        if code not in self._policy.preset_allowlist:
            raise SafetyValidationError(f"PRESET code is not allow-listed: {code}")


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(cast(int | float, value)))
    except (OverflowError, ValueError):
        return False
