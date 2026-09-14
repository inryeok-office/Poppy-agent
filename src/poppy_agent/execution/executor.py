"""Execution executor contract and deterministic mock implementation."""

from __future__ import annotations

from typing import Protocol

from poppy_agent.execution.models import ExecutionResult, ExecutionStatus, ExecutionTask


class ExecutionExecutor(Protocol):
    """Produce a final outcome for a validated execution task."""

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Execute a task without imposing a transport or robot implementation."""


class MockExecutionExecutor:
    """Deterministically return configured outcomes without external side effects."""

    def __init__(self, *, fail_execution: bool = False) -> None:
        self._fail_execution = fail_execution

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Return the configured final result while preserving the execution identifier."""
        if self._fail_execution:
            return ExecutionResult(
                execution_id=task.execution_id,
                status=ExecutionStatus.FAILED,
                failure_reason="configured mock execution failure",
            )
        return ExecutionResult(
            execution_id=task.execution_id,
            status=ExecutionStatus.COMPLETED,
        )
