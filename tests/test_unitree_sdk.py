from uuid import UUID

import pytest

import poppy_agent.hardware.unitree_sdk as unitree_sdk
from poppy_agent.command import CommandType, MoveDirection
from poppy_agent.execution import (
    MotionPlan,
    MotionRateUnit,
    MotionUnit,
    PhysicalCommandClientKind,
    PhysicalExecutionBlockedError,
    PhysicalReadinessEvidence,
)
from poppy_agent.hardware import (
    FakeUnitreeCommandClient,
    UnitreeMotionCommand,
    UnitreeSdkCommandClient,
    UnitreeSdkCommandError,
    UnitreeSdkUnavailableError,
    create_unitree_execution_executor,
)

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeSdkClient:
    def __init__(
        self,
        *,
        operation_result: object = 0,
        init_result: object = 0,
        fail_init: bool = False,
        fail_operation: str | None = None,
    ) -> None:
        self.operation_result = operation_result
        self.init_result = init_result
        self.fail_init = fail_init
        self.fail_operation = fail_operation
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def Init(self) -> object:
        self.calls.append(("Init", ()))
        if self.fail_init:
            raise RuntimeError("sdk initialization secret")
        return self.init_result

    def Sit(self) -> object:
        return self._call("Sit")

    def StandUp(self) -> object:
        return self._call("StandUp")

    def Move(self, vx: float, vy: float, vyaw: float) -> object:
        return self._call("Move", vx, vy, vyaw)

    def Close(self) -> None:
        self.calls.append(("Close", ()))

    def _call(self, name: str, *args: object) -> object:
        self.calls.append((name, args))
        if self.fail_operation == name:
            raise RuntimeError("sdk secret must not escape")
        return self.operation_result


def motion_plan() -> MotionPlan:
    return MotionPlan(
        sequence=0,
        source_block_id="move-block",
        command_type=CommandType.MOVE,
        direction=MoveDirection.FORWARD,
        magnitude=1.0,
        magnitude_unit=MotionUnit.METERS,
        rate=0.5,
        rate_unit=MotionRateUnit.METERS_PER_SECOND,
        duration_seconds=2.0,
    )


def complete_evidence() -> PhysicalReadinessEvidence:
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


def test_sdk_module_import_does_not_require_optional_sdk() -> None:
    assert UnitreeSdkCommandClient is not None


def test_missing_sdk_is_reported_only_when_default_factory_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_import(_name: str) -> object:
        raise ImportError("optional SDK is absent")

    monkeypatch.setattr(unitree_sdk, "import_module", missing_import)

    with pytest.raises(UnitreeSdkUnavailableError, match="official unitree_sdk2_python"):
        unitree_sdk.default_unitree_sport_client_factory("enp2s0")


def test_default_factory_initializes_explicit_channel_before_sport_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class FakeSportClient:
        pass

    class FakeChannel:
        @staticmethod
        def ChannelFactoryInitialize(domain: int, interface: str) -> None:
            calls.append(("channel", (domain, interface)))

    class FakeSportModule:
        SportClient = FakeSportClient

    def fake_import(name: str) -> object:
        if name == "unitree_sdk2py.core.channel":
            return FakeChannel
        if name == "unitree_sdk2py.go2.sport.sport_client":
            return FakeSportModule
        raise AssertionError(name)

    monkeypatch.setattr(unitree_sdk, "import_module", fake_import)

    client = unitree_sdk.default_unitree_sport_client_factory("enp2s0")

    assert isinstance(client, FakeSportClient)
    assert calls == [("channel", (0, "enp2s0"))]


def test_command_adapter_lifecycle_and_posture_mapping() -> None:
    sdk = FakeSdkClient()
    client = UnitreeSdkCommandClient(sdk_client=sdk)

    with pytest.raises(UnitreeSdkCommandError, match="not initialized"):
        client.sit()

    client.initialize()
    client.initialize()
    assert client.sit() is True
    assert client.stand_up() is True
    client.shutdown()
    client.shutdown()

    assert sdk.calls == [("Init", ()), ("Sit", ()), ("StandUp", ()), ("Close", ())]
    with pytest.raises(UnitreeSdkCommandError, match="not initialized"):
        client.stand_up()


def test_command_adapter_initialization_failure_is_normalized_and_sanitized() -> None:
    sdk = FakeSdkClient(fail_init=True)
    client = UnitreeSdkCommandClient(sdk_client=sdk)

    with pytest.raises(UnitreeSdkCommandError, match="initialization failed") as error:
        client.initialize()

    assert "sdk initialization secret" not in str(error.value)
    assert client.initialized is False
    client.shutdown()
    assert sdk.calls == [("Init", ()), ("Close", ())]


def test_command_adapter_requires_explicit_motion_mapping() -> None:
    sdk = FakeSdkClient()
    client = UnitreeSdkCommandClient(sdk_client=sdk)
    client.initialize()

    with pytest.raises(UnitreeSdkCommandError, match="explicit motion mapping policy"):
        client.execute_motion(motion_plan())
    assert [name for name, _args in sdk.calls] == ["Init"]


def test_command_adapter_uses_injected_motion_mapping_without_defaults() -> None:
    sdk = FakeSdkClient()
    client = UnitreeSdkCommandClient(
        sdk_client=sdk,
        motion_mapper=lambda _plan: UnitreeMotionCommand(0.1, 0.0, 0.0),
    )
    client.initialize()

    assert client.execute_motion(motion_plan()) is True
    assert sdk.calls[-1] == ("Move", (0.1, 0.0, 0.0))


def test_command_adapter_normalizes_sdk_status_and_sanitizes_errors() -> None:
    failing = UnitreeSdkCommandClient(
        sdk_client=FakeSdkClient(fail_operation="Sit"),
    )
    failing.initialize()
    with pytest.raises(UnitreeSdkCommandError) as error:
        failing.sit()
    assert "sdk secret" not in str(error.value)

    unsuccessful = UnitreeSdkCommandClient(sdk_client=FakeSdkClient(operation_result=False))
    unsuccessful.initialize()
    with pytest.raises(UnitreeSdkCommandError, match="reported failure"):
        unsuccessful.sit()


def test_readiness_gate_runs_before_sdk_factory() -> None:
    calls = 0

    def forbidden_factory() -> FakeUnitreeCommandClient:
        nonlocal calls
        calls += 1
        raise AssertionError("SDK factory must not run while readiness is blocked")

    with pytest.raises(PhysicalExecutionBlockedError):
        create_unitree_execution_executor(
            robot_id=ROBOT_ID,
            physical_execution_enabled=False,
            client_factory=forbidden_factory,
        )

    assert calls == 0


def test_enable_flag_alone_does_not_create_sdk_client() -> None:
    calls = 0

    def forbidden_factory() -> FakeUnitreeCommandClient:
        nonlocal calls
        calls += 1
        raise AssertionError("SDK factory must not run without reviewed evidence")

    with pytest.raises(PhysicalExecutionBlockedError):
        create_unitree_execution_executor(
            robot_id=ROBOT_ID,
            physical_execution_enabled=True,
            client_factory=forbidden_factory,
        )

    assert calls == 0


def test_gated_executor_can_use_an_injected_software_double() -> None:
    client = FakeUnitreeCommandClient()
    executor = create_unitree_execution_executor(
        robot_id=ROBOT_ID,
        physical_execution_enabled=True,
        evidence=complete_evidence(),
        client_factory=lambda: client,
    )

    assert client.initialized is True
    executor.shutdown()
    assert client.initialized is False
