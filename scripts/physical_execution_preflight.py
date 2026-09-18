"""Run a software-only preflight of the gated physical execution path.

This harness deliberately uses an injected recording SDK double.  It parses a
Server-shaped command payload, runs the existing safety validator and physical
readiness gate, and records the command boundary without importing or
initializing the real Unitree SDK, DDS, or a network transport.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from poppy_agent.command import (  # noqa: E402
    CommandType,
    HighLevelCommand,
    HighLevelCommandProgram,
    HighLevelCommandProtocolParser,
    MoveDirection,
    MoveParameters,
    Posture,
    PostureParameters,
    PresetParameters,
    StopParameters,
    TurnDirection,
    TurnParameters,
    WaitParameters,
)
from poppy_agent.execution import (  # noqa: E402
    ExecutionCancellationToken,
    ExecutionStatus,
    ExecutionTask,
    MockExecutionExecutor,
    MotionExecutionStrategy,
    MotionPlan,
    MotionProfile,
    PhysicalCommandClientKind,
    PhysicalExecutionBlockedError,
    PhysicalExecutionGate,
    PhysicalReadinessEvidence,
    RecordingSleeper,
)
from poppy_agent.hardware import (  # noqa: E402
    UnitreeMotionCommand,
    UnitreeSdkCommandClient,
    UnitreeSdkCommandError,
    create_unitree_execution_executor,
)

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000077")


class PhysicalExecutionPreflightError(RuntimeError):
    """Raised when the software-only preflight contract is violated."""


@dataclass(frozen=True, slots=True)
class RecordingCall:
    """One call made to the injected SDK-shaped recording double."""

    operation: str
    arguments: tuple[object, ...] = ()


class RecordingSportClient:
    """In-memory SDK double; it never opens a network or DDS transport."""

    def __init__(
        self,
        *,
        fail_init: bool = False,
        fail_operation: str | None = None,
        fail_close: bool = False,
    ) -> None:
        self.calls: list[RecordingCall] = []
        self._fail_init = fail_init
        self._fail_operation = fail_operation
        self._fail_close = fail_close

    @property
    def initialize_calls(self) -> int:
        return self._count("Init")

    @property
    def shutdown_calls(self) -> int:
        return self._count("Close")

    @property
    def dispatch_calls(self) -> list[RecordingCall]:
        return [call for call in self.calls if call.operation in {"Sit", "StandUp", "Move"}]

    @property
    def duplicate_dispatch_count(self) -> int:
        keys = [(call.operation, call.arguments) for call in self.dispatch_calls]
        return len(keys) - len(set(keys))

    def Init(self) -> int:
        self.calls.append(RecordingCall("Init"))
        if self._fail_init:
            raise RuntimeError("recording initialization failure")
        return 0

    def Sit(self) -> int:
        return self._operation("Sit")

    def StandUp(self) -> int:
        return self._operation("StandUp")

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        return self._operation("Move", vx, vy, vyaw)

    def Close(self) -> None:
        self.calls.append(RecordingCall("Close"))
        if self._fail_close:
            raise RuntimeError("recording shutdown failure")

    def _operation(self, name: str, *arguments: object) -> int:
        self.calls.append(RecordingCall(name, arguments))
        if self._fail_operation == name:
            raise RuntimeError("recording operation failure")
        return 0

    def _count(self, name: str) -> int:
        return sum(call.operation == name for call in self.calls)


@dataclass(frozen=True, slots=True)
class PreflightPhaseResult:
    """Machine-readable result for one preflight phase."""

    name: str
    details: str


@dataclass(slots=True)
class LocalExecutionAuthority:
    """Minimal Server-shaped delivery/reconciliation double for this harness."""

    command_payload: str
    available: bool = True
    status: str = "RUNNING"
    transitions: list[str] = field(default_factory=lambda: ["CONNECTED"])

    def poll(self) -> str:
        if not self.available:
            raise ConnectionError("local authoritative delivery unavailable")
        return self.command_payload

    def disconnect(self) -> None:
        self.available = False
        self.transitions.append("DEGRADED")

    def reconnect_and_reconcile(self) -> None:
        self.available = True
        self.transitions.append("CONNECTED")
        self.status = "FAILED"


class DisconnectingSleeper(RecordingSleeper):
    """Cancel a motion at its wait boundary to model a Server outage."""

    def __init__(self, authority: LocalExecutionAuthority) -> None:
        super().__init__()
        self._authority = authority

    def sleep(
        self,
        duration_seconds: float,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> None:
        super().sleep(duration_seconds, cancellation_token)
        self._authority.disconnect()
        if cancellation_token is not None:
            cancellation_token.cancel("Server connectivity lost")


def synthetic_test_evidence() -> PhysicalReadinessEvidence:
    """Return evidence only for downstream test coverage, never production use."""
    return PhysicalReadinessEvidence(
        command_client_kind=PhysicalCommandClientKind.REAL,
        production_motion_profile_approved=True,
        physical_limits_defined=True,
        preset_policy_defined=True,
        emergency_procedure_confirmed=True,
        telemetry_requirements_met=True,
        observability_requirements_met=True,
        equipment_owner_approved=True,
        hardware_validation_completed=True,
    )


def _server_payload(*commands: dict[str, object]) -> str:
    return json.dumps({"protocolVersion": 1, "commands": list(commands)})


def _task(payload: str) -> ExecutionTask:
    program = HighLevelCommandProtocolParser().parse(payload)
    return ExecutionTask(
        execution_id=UUID("00000000-0000-0000-0000-000000000078"),
        robot_id=ROBOT_ID,
        protocol_version=program.protocol_version,
        command_program=program,
    )


def _command(
    sequence: int,
    source_block_id: str,
    command_type: CommandType,
    parameters: object,
) -> HighLevelCommand:
    return HighLevelCommand(sequence, source_block_id, command_type, parameters)  # type: ignore[arg-type]


def _program(*commands: HighLevelCommand) -> ExecutionTask:
    return ExecutionTask(
        execution_id=UUID("00000000-0000-0000-0000-000000000078"),
        robot_id=ROBOT_ID,
        protocol_version=1,
        command_program=HighLevelCommandProgram(1, commands),
    )


def _executor(
    sdk: RecordingSportClient,
    *,
    motion_strategy: MotionExecutionStrategy | None = None,
    sleeper: RecordingSleeper | None = None,
    motion_mapper: Callable[[MotionPlan], UnitreeMotionCommand] | None = None,
) -> tuple[MockExecutionExecutor, list[int]]:
    adapter = UnitreeSdkCommandClient(sdk_client=sdk, motion_mapper=motion_mapper)
    factory_calls: list[int] = []

    def factory() -> UnitreeSdkCommandClient:
        factory_calls.append(1)
        return adapter

    executor = create_unitree_execution_executor(
        robot_id=ROBOT_ID,
        physical_execution_enabled=True,
        evidence=synthetic_test_evidence(),
        client_factory=factory,
        motion_strategy=motion_strategy,
        sleeper=sleeper,
    )
    return executor, factory_calls


def _assert_blocked(physical_execution_enabled: bool) -> None:
    factory_calls = 0

    def forbidden_factory() -> UnitreeSdkCommandClient:
        nonlocal factory_calls
        factory_calls += 1
        raise PhysicalExecutionPreflightError("blocked path created a client")

    readiness = PhysicalExecutionGate().evaluate(
        physical_execution_enabled=physical_execution_enabled,
    )
    if readiness.ready:
        raise PhysicalExecutionPreflightError("default evidence unexpectedly became ready")
    try:
        create_unitree_execution_executor(
            robot_id=ROBOT_ID,
            physical_execution_enabled=physical_execution_enabled,
            client_factory=forbidden_factory,
        )
    except PhysicalExecutionBlockedError:
        pass
    if factory_calls != 0:
        raise PhysicalExecutionPreflightError("blocked path called the client factory")


def _test_only_mapper(plan: MotionPlan) -> UnitreeMotionCommand:
    """Use fixed fixture values solely to exercise the adapter seam."""
    command_type = plan.command_type
    direction = plan.direction
    if command_type is CommandType.MOVE:
        return UnitreeMotionCommand(0.25 if direction is MoveDirection.FORWARD else -0.25, 0.0, 0.0)
    return UnitreeMotionCommand(0.0, 0.0, 0.5 if direction is TurnDirection.LEFT else -0.5)


def run_preflight(*, emit: bool = True) -> tuple[PreflightPhaseResult, ...]:
    """Run all deterministic software-only preflight phases."""
    _assert_software_only_environment()
    results: list[PreflightPhaseResult] = []

    def phase(name: str, check: Callable[[], str]) -> None:
        try:
            details = check()
        except Exception as exc:
            raise PhysicalExecutionPreflightError(f"{name} failed: {type(exc).__name__}") from exc
        result = PreflightPhaseResult(name, details)
        results.append(result)
        if emit:
            print(f"[{len(results):02d}] {name} ... PASS ({details})")

    phase("default readiness is blocked", lambda: (_assert_blocked(False), "factory=0")[1])
    phase("enable flag alone remains blocked", lambda: (_assert_blocked(True), "factory=0")[1])
    phase("recording posture lifecycle", _posture_phase)
    phase("WAIT has no physical call", _wait_phase)
    phase("program STOP has no physical stop call", _stop_phase)
    phase("PRESET remains fail-closed", _preset_phase)
    phase("unconfigured MOVE and TURN fail closed", _unconfigured_motion_phase)
    phase("test-only mapped MOVE and TURN record", _mapped_motion_phase)
    phase("invalid later command preflights before dispatch", _later_invalid_phase)
    phase("initialization and backend failures are normalized", _failure_phase)
    phase("cancellation preserves CANCELLED", _cancellation_phase)
    phase("disconnect fails closed with no replay", _disconnect_phase)
    phase("disable is a rollback boundary", lambda: (_assert_blocked(False), "factory=0")[1])

    sdk_modules = [
        name
        for name in sys.modules
        if name == "unitree_sdk2py" or name.startswith("unitree_sdk2py.")
    ]
    if sdk_modules:
        raise PhysicalExecutionPreflightError("real Unitree SDK modules were imported")
    return tuple(results)


def _posture_phase() -> str:
    sdk = RecordingSportClient()
    executor, factory_calls = _executor(sdk)
    try:
        result = executor.execute(
            _task(
                _server_payload(
                    {
                        "sequence": 0,
                        "sourceBlockId": "sit",
                        "type": "POSTURE",
                        "parameters": {"posture": "SIT"},
                    },
                    {
                        "sequence": 1,
                        "sourceBlockId": "stand",
                        "type": "POSTURE",
                        "parameters": {"posture": "STAND"},
                    },
                )
            )
        )
        operations = [call.operation for call in sdk.dispatch_calls]
        if result.status is not ExecutionStatus.COMPLETED or operations != ["Sit", "StandUp"]:
            raise PhysicalExecutionPreflightError("posture recording mismatch")
        if factory_calls != [1] or sdk.initialize_calls != 1:
            raise PhysicalExecutionPreflightError("posture lifecycle count mismatch")
        return "factory=1 initialize=1 Sit=1 StandUp=1"
    finally:
        executor.shutdown()
        if sdk.shutdown_calls != 1:
            raise PhysicalExecutionPreflightError("posture shutdown count mismatch")


def _wait_phase() -> str:
    sdk = RecordingSportClient()
    executor, _ = _executor(sdk)
    try:
        result = executor.execute(
            _program(_command(0, "wait", CommandType.WAIT, WaitParameters(0.0)))
        )
        if result.status is not ExecutionStatus.COMPLETED or sdk.dispatch_calls:
            raise PhysicalExecutionPreflightError("WAIT reached the SDK boundary")
        return "physical_calls=0"
    finally:
        executor.shutdown()


def _stop_phase() -> str:
    sdk = RecordingSportClient()
    executor, _ = _executor(sdk)
    try:
        result = executor.execute(_program(_command(0, "stop", CommandType.STOP, StopParameters())))
        if result.status is not ExecutionStatus.COMPLETED or sdk.dispatch_calls:
            raise PhysicalExecutionPreflightError("STOP reached the SDK boundary")
        if any(call.operation == "StopMove" for call in sdk.calls):
            raise PhysicalExecutionPreflightError("program STOP mapped to StopMove")
        return "physical_calls=0 StopMove=0"
    finally:
        executor.shutdown()


def _preset_phase() -> str:
    sdk = RecordingSportClient()
    executor, _ = _executor(sdk)
    try:
        result = executor.execute(
            _program(_command(0, "preset", CommandType.PRESET, PresetParameters("test-only")))
        )
        if result.status is not ExecutionStatus.FAILED or sdk.dispatch_calls:
            raise PhysicalExecutionPreflightError("PRESET was not fail-closed")
        return "status=FAILED physical_calls=0"
    finally:
        executor.shutdown()


def _unconfigured_motion_phase() -> str:
    for command_type, parameters in (
        (CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, 1.0)),
        (CommandType.TURN, TurnParameters(TurnDirection.LEFT, 90.0)),
    ):
        sdk = RecordingSportClient()
        executor, _ = _executor(sdk)
        try:
            result = executor.execute(
                _program(_command(0, command_type.value, command_type, parameters))
            )
            if result.status is not ExecutionStatus.FAILED or sdk.dispatch_calls:
                raise PhysicalExecutionPreflightError(f"{command_type.value} was not fail-closed")
        finally:
            executor.shutdown()
    return "MOVE=FAILED TURN=FAILED physical_calls=0"


def _mapped_motion_phase() -> str:
    sdk = RecordingSportClient()
    strategy = MotionExecutionStrategy(MotionProfile(0.5, 90.0))
    sleeper = RecordingSleeper()
    executor, _ = _executor(
        sdk,
        motion_strategy=strategy,
        sleeper=sleeper,
        motion_mapper=_test_only_mapper,
    )
    try:
        result = executor.execute(
            _program(
                _command(0, "move", CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, 1.0)),
                _command(1, "turn", CommandType.TURN, TurnParameters(TurnDirection.LEFT, 90.0)),
            )
        )
        moves = [call for call in sdk.dispatch_calls if call.operation == "Move"]
        if result.status is not ExecutionStatus.COMPLETED or len(moves) != 2:
            raise PhysicalExecutionPreflightError("test-only motion mapping mismatch")
        if sleeper.durations != [2.0, 1.0]:
            raise PhysicalExecutionPreflightError("motion duration planning mismatch")
        return "Move-shaped calls=2 physical_transport=recording"
    finally:
        executor.shutdown()


def _later_invalid_phase() -> str:
    sdk = RecordingSportClient()
    executor, _ = _executor(sdk)
    try:
        result = executor.execute(
            _program(
                _command(0, "sit", CommandType.POSTURE, PostureParameters(Posture.SIT)),
                _command(1, "preset", CommandType.PRESET, PresetParameters("invalid")),
            )
        )
        if result.status is not ExecutionStatus.FAILED or sdk.dispatch_calls:
            raise PhysicalExecutionPreflightError("later invalid command was dispatched early")
        return "dispatch_before_invalid=0"
    finally:
        executor.shutdown()


def _failure_phase() -> str:
    failing_init = RecordingSportClient(fail_init=True)
    adapter = UnitreeSdkCommandClient(sdk_client=failing_init)
    try:
        create_unitree_execution_executor(
            robot_id=ROBOT_ID,
            physical_execution_enabled=True,
            evidence=synthetic_test_evidence(),
            client_factory=lambda: adapter,
        )
    except UnitreeSdkCommandError:
        pass
    else:
        raise PhysicalExecutionPreflightError("initialization failure was accepted")
    if [call.operation for call in failing_init.calls] != ["Init", "Close"]:
        raise PhysicalExecutionPreflightError("partial initialization was not cleaned up")

    failing_operation = RecordingSportClient(fail_operation="Sit")
    executor, _ = _executor(failing_operation)
    try:
        result = executor.execute(
            _program(_command(0, "sit", CommandType.POSTURE, PostureParameters(Posture.SIT)))
        )
        if result.status is not ExecutionStatus.FAILED or "recording operation failure" in (
            result.failure_reason or ""
        ):
            raise PhysicalExecutionPreflightError("raw SDK failure escaped")
    finally:
        executor.shutdown()

    shutdown_failure = RecordingSportClient(fail_close=True)
    executor, _ = _executor(shutdown_failure)
    result = executor.execute(_program(_command(0, "wait", CommandType.WAIT, WaitParameters(0.0))))
    try:
        executor.shutdown()
    except UnitreeSdkCommandError:
        pass
    else:
        raise PhysicalExecutionPreflightError("shutdown failure was hidden")
    if result.status is not ExecutionStatus.COMPLETED:
        raise PhysicalExecutionPreflightError("cleanup failure changed primary result")
    return "init cleanup=Close backend failure=FAILED shutdown failure=visible"


def _cancellation_phase() -> str:
    sdk = RecordingSportClient()
    executor, _ = _executor(sdk)
    try:
        token = ExecutionCancellationToken()
        token.cancel("pre-dispatch cancellation")
        before = executor.execute(
            _program(_command(0, "sit", CommandType.POSTURE, PostureParameters(Posture.SIT))),
            token,
        )
        if before.status is not ExecutionStatus.CANCELLED or sdk.dispatch_calls:
            raise PhysicalExecutionPreflightError("pre-dispatch cancellation dispatched")
    finally:
        executor.shutdown()

    sdk = RecordingSportClient()
    authority = LocalExecutionAuthority(
        _server_payload(
            {
                "sequence": 0,
                "sourceBlockId": "move",
                "type": "MOVE",
                "parameters": {"direction": "FORWARD", "distanceMeters": 1.0},
            }
        )
    )
    sleeper = DisconnectingSleeper(authority)
    executor, _ = _executor(
        sdk,
        motion_strategy=MotionExecutionStrategy(MotionProfile(0.5, 90.0)),
        sleeper=sleeper,
        motion_mapper=_test_only_mapper,
    )
    try:
        during = executor.execute(_task(authority.poll()))
        if during.status is not ExecutionStatus.CANCELLED or len(sdk.dispatch_calls) != 1:
            raise PhysicalExecutionPreflightError("motion cancellation semantics changed")
    finally:
        executor.shutdown()
    return "before_dispatch=0 during_wait=cancelled"


def _disconnect_phase() -> str:
    authority = LocalExecutionAuthority(
        _server_payload(
            {
                "sequence": 0,
                "sourceBlockId": "move",
                "type": "MOVE",
                "parameters": {"direction": "FORWARD", "distanceMeters": 1.0},
            }
        )
    )
    sdk = RecordingSportClient()
    sleeper = DisconnectingSleeper(authority)
    executor, _ = _executor(
        sdk,
        motion_strategy=MotionExecutionStrategy(MotionProfile(0.5, 90.0)),
        sleeper=sleeper,
        motion_mapper=_test_only_mapper,
    )
    try:
        payload = authority.poll()
        result = executor.execute(_task(payload))
        if result.status is not ExecutionStatus.CANCELLED:
            raise PhysicalExecutionPreflightError("outage did not interrupt execution")
        dispatch_count = len(sdk.dispatch_calls)
    finally:
        executor.shutdown()
    try:
        authority.poll()
    except ConnectionError:
        pass
    else:
        raise PhysicalExecutionPreflightError("polling continued while authority was unavailable")
    authority.reconnect_and_reconcile()
    if authority.transitions != ["CONNECTED", "DEGRADED", "CONNECTED"]:
        raise PhysicalExecutionPreflightError("connectivity transition mismatch")
    if authority.status != "FAILED" or dispatch_count != 1 or sdk.duplicate_dispatch_count != 0:
        raise PhysicalExecutionPreflightError("reconciliation/replay contract mismatch")
    return "CONNECTED->DEGRADED->CONNECTED terminal=FAILED replay=0"


def _assert_software_only_environment() -> None:
    """Fail closed if a caller tries to turn this harness into a live test."""
    if os.environ.get("ROBOT_MODE", "mock").lower() == "unitree":
        raise PhysicalExecutionPreflightError("ROBOT_MODE=unitree is forbidden")
    if os.environ.get("POPPY_PREFLIGHT_LIVE_TRANSPORT") == "1":
        raise PhysicalExecutionPreflightError("live preflight transport is forbidden")
    if os.environ.get("POPPY_PREFLIGHT_USE_REAL_SDK") == "1":
        raise PhysicalExecutionPreflightError("real SDK preflight is forbidden")


def main() -> int:
    try:
        run_preflight()
    except PhysicalExecutionPreflightError as exc:
        print(f"PHYSICAL EXECUTION PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 1
    print("PHYSICAL EXECUTION PREFLIGHT PASSED: software-only recording boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
