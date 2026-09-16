"""Execution executor contract and deterministic mock implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from poppy_agent.command import CommandType, HighLevelCommand
from poppy_agent.command.models import CommandParameters
from poppy_agent.execution.models import ExecutionResult, ExecutionStatus, ExecutionTask
from poppy_agent.execution.safety import (
    CommandSafetyPolicy,
    ExecutionSafetyValidator,
    SafetyValidationError,
)


class ExecutionExecutor(Protocol):
    """Produce a final outcome for a validated execution task."""

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Execute a task without imposing a transport or robot implementation."""


class ExecutionTargetError(RuntimeError):
    """Raised when a command target cannot dispatch a typed command."""


class CommandExecutionTarget(Protocol):
    """Target contract for typed command support and dispatch."""

    def supports(self, command_type: CommandType) -> bool:
        """Return whether this target can execute a command type."""

    def dispatch(self, command: HighLevelCommand) -> bool:
        """Dispatch one already-validated command and report STOP termination."""


@dataclass(frozen=True, slots=True)
class MockCommandEvent:
    """One typed command dispatched by the deterministic mock target."""

    sequence: int
    source_block_id: str
    type: CommandType
    parameters: CommandParameters


class MockCommandTarget:
    """Record typed commands without simulating or controlling a robot."""

    def __init__(self) -> None:
        self.events: list[MockCommandEvent] = []

    def supports(self, _command_type: CommandType) -> bool:
        """Support every protocol command as trace-only Mock behavior."""
        return True

    def dispatch(self, command: HighLevelCommand) -> bool:
        """Record one command and return whether it requests program termination."""
        self.events.append(
            MockCommandEvent(
                sequence=command.sequence,
                source_block_id=command.source_block_id,
                type=command.type,
                parameters=command.parameters,
            )
        )
        return command.type is CommandType.STOP


class MockExecutionExecutor:
    """Execute a typed command program as a deterministic, side-effect-free trace."""

    def __init__(
        self,
        target: CommandExecutionTarget | None = None,
        *,
        fail_execution: bool = False,
        fail_at_sequence: int | None = None,
        safety_policy: CommandSafetyPolicy | None = None,
        bound_robot_id: UUID | None = None,
    ) -> None:
        self.target = target or MockCommandTarget()
        self._fail_execution = fail_execution
        self._fail_at_sequence = fail_at_sequence
        self._safety_validator = ExecutionSafetyValidator(
            self.target,
            policy=safety_policy or CommandSafetyPolicy.for_mock_trace(),
            bound_robot_id=bound_robot_id,
        )

    @property
    def events(self) -> list[MockCommandEvent]:
        """Expose the target trace for deterministic tests and local inspection."""
        return cast(list[MockCommandEvent], getattr(self.target, "events", []))

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Dispatch the program in order and preserve the execution identifier."""
        if self._fail_execution:
            return ExecutionResult(
                execution_id=task.execution_id,
                status=ExecutionStatus.FAILED,
                failure_reason="configured mock execution failure",
            )

        try:
            self._safety_validator.validate(task)
        except SafetyValidationError as exc:
            return ExecutionResult(
                execution_id=task.execution_id,
                status=ExecutionStatus.FAILED,
                failure_reason=str(exc),
            )

        for command in task.command_program.commands:
            if command.sequence == self._fail_at_sequence:
                return ExecutionResult(
                    execution_id=task.execution_id,
                    status=ExecutionStatus.FAILED,
                    failure_reason=(
                        f"configured mock execution failure at sequence {command.sequence}"
                    ),
                )
            try:
                should_stop = self.target.dispatch(command)
            except ExecutionTargetError as exc:
                return ExecutionResult(
                    execution_id=task.execution_id,
                    status=ExecutionStatus.FAILED,
                    failure_reason=f"execution target failed: {exc}",
                )
            if should_stop:
                break

        return ExecutionResult(
            execution_id=task.execution_id,
            status=ExecutionStatus.COMPLETED,
        )
