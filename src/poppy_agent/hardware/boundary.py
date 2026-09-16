"""Hardware-neutral command boundary and an inert backend for tests.

Nothing in this module imports a vendor SDK or opens a network/DDS connection.
The port is the only contract a future hardware-specific backend needs to
implement; the fake backend is deliberately useful only as a deterministic
test double.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from poppy_agent.command import CommandType, HighLevelCommand
from poppy_agent.command.models import CommandParameters
from poppy_agent.execution.executor import ExecutionTargetError


@dataclass(frozen=True, slots=True)
class HardwareCommandIntent:
    """Vendor-neutral intent derived from one validated protocol command."""

    sequence: int
    source_block_id: str
    type: CommandType
    parameters: CommandParameters

    @classmethod
    def from_command(cls, command: HighLevelCommand) -> HardwareCommandIntent:
        """Convert a typed protocol command without exposing it to a backend."""
        return cls(
            sequence=command.sequence,
            source_block_id=command.source_block_id,
            type=command.type,
            parameters=command.parameters,
        )


class HardwareCommandPort(Protocol):
    """Minimal boundary for a future hardware command backend."""

    def initialize(self) -> None:
        """Prepare the backend for command dispatch."""

    def supports(self, command_type: CommandType) -> bool:
        """Report explicit support for one protocol command type."""

    def dispatch(self, intent: HardwareCommandIntent) -> bool:
        """Dispatch one intent and report whether it terminates the program."""

    def shutdown(self) -> None:
        """Release backend resources without implying an emergency stop."""


class FakeHardwareBackendError(RuntimeError):
    """Raised by the inert backend for configured or invalid operations."""


@dataclass(frozen=True, slots=True)
class FakeHardwareEvent:
    """Recorded hardware-neutral intent, retaining typed parameters."""

    sequence: int
    source_block_id: str
    type: CommandType
    parameters: CommandParameters


class FakeHardwareBackend:
    """Inert, in-memory implementation of :class:`HardwareCommandPort`."""

    def __init__(
        self,
        supported_commands: Iterable[CommandType] = (),
        *,
        fail_initialize: bool = False,
        fail_at_sequence: int | None = None,
    ) -> None:
        self._supported_commands = frozenset(supported_commands)
        self._fail_initialize = fail_initialize
        self._fail_at_sequence = fail_at_sequence
        self._initialized = False
        self.events: list[FakeHardwareEvent] = []

    @property
    def initialized(self) -> bool:
        """Expose deterministic lifecycle state for tests."""
        return self._initialized

    def initialize(self) -> None:
        """Enter the initialized state without touching any external system."""
        if self._fail_initialize:
            raise FakeHardwareBackendError("configured fake hardware initialization failure")
        self._initialized = True

    def supports(self, command_type: CommandType) -> bool:
        """Return only explicitly configured command support."""
        return command_type in self._supported_commands

    def dispatch(self, intent: HardwareCommandIntent) -> bool:
        """Record an intent or deterministically raise a fake backend failure."""
        if not self._initialized:
            raise FakeHardwareBackendError("fake hardware backend is not initialized")
        if not self.supports(intent.type):
            raise FakeHardwareBackendError(
                f"fake hardware backend does not support {intent.type.value}"
            )
        if self._fail_at_sequence == intent.sequence:
            raise FakeHardwareBackendError(
                f"configured fake hardware failure at sequence {intent.sequence}"
            )
        self.events.append(
            FakeHardwareEvent(
                sequence=intent.sequence,
                source_block_id=intent.source_block_id,
                type=intent.type,
                parameters=intent.parameters,
            )
        )
        return intent.type is CommandType.STOP

    def shutdown(self) -> None:
        """Leave the initialized state; no stop command is synthesized."""
        self._initialized = False


class HardwareCommandTarget:
    """Adapt typed protocol commands to the hardware-neutral command port."""

    def __init__(self, port: HardwareCommandPort) -> None:
        self._port = port

    def initialize(self) -> None:
        """Initialize the underlying boundary explicitly."""
        self._port.initialize()

    def supports(self, command_type: CommandType) -> bool:
        """Delegate explicit support to the backend boundary."""
        return self._port.supports(command_type) is True

    def preflight(self, command: HighLevelCommand) -> None:
        """Validate optional backend planning before any dispatch occurs."""
        preflight = getattr(self._port, "preflight", None)
        if callable(preflight):
            preflight(HardwareCommandIntent.from_command(command))

    def dispatch(self, command: HighLevelCommand) -> bool:
        """Convert a command to intent and propagate boundary failures."""
        intent = HardwareCommandIntent.from_command(command)
        try:
            result = self._port.dispatch(intent)
        except Exception as exc:
            if isinstance(exc, ExecutionTargetError):
                raise
            raise ExecutionTargetError(str(exc)) from exc
        if type(result) is not bool:
            raise ExecutionTargetError("hardware command port returned a non-boolean result")
        return result

    def shutdown(self) -> None:
        """Shut down the underlying boundary explicitly."""
        self._port.shutdown()
