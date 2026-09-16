"""Execution executor contract and deterministic mock implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from poppy_agent.command import CommandType, HighLevelCommand
from poppy_agent.command.models import CommandParameters
from poppy_agent.execution.models import ExecutionResult, ExecutionStatus, ExecutionTask


class ExecutionExecutor(Protocol):
    """Produce a final outcome for a validated execution task."""

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Execute a task without imposing a transport or robot implementation."""


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
        target: MockCommandTarget | None = None,
        *,
        fail_execution: bool = False,
        fail_at_sequence: int | None = None,
    ) -> None:
        self.target = target or MockCommandTarget()
        self._fail_execution = fail_execution
        self._fail_at_sequence = fail_at_sequence

    @property
    def events(self) -> list[MockCommandEvent]:
        """Expose the target trace for deterministic tests and local inspection."""
        return self.target.events

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Dispatch the program in order and preserve the execution identifier."""
        if self._fail_execution:
            return ExecutionResult(
                execution_id=task.execution_id,
                status=ExecutionStatus.FAILED,
                failure_reason="configured mock execution failure",
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
            if self.target.dispatch(command):
                break

        return ExecutionResult(
            execution_id=task.execution_id,
            status=ExecutionStatus.COMPLETED,
        )
