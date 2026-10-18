import sys
import types
from datetime import UTC, datetime
from uuid import UUID

import pytest

from poppy_agent.robot import (
    RobotIdentity,
    UnitreeGo2Adapter,
    UnitreeGo2Config,
    UnitreeSdkUnavailableError,
)


def unitree_config() -> UnitreeGo2Config:
    return UnitreeGo2Config(
        network_interface="enp2s0",
        identity=RobotIdentity(
            robot_id=str(UUID("00000000-0000-0000-0000-000000000001")),
            model="GO2",
            edition="configured",
            firmware_version="configured",
            sdk_version="unitree_sdk2_python",
        ),
        telemetry_stale_timeout_seconds=5.0,
    )


def test_sdk_unavailable_error_is_explicit(monkeypatch) -> None:
    import_calls: list[str] = []

    def unavailable_import(name: str):
        import_calls.append(name)
        raise ImportError("simulated missing Unitree SDK")

    monkeypatch.setattr("poppy_agent.robot.unitree.import_module", unavailable_import)

    adapter = UnitreeGo2Adapter(unitree_config())
    with pytest.raises(UnitreeSdkUnavailableError, match="official unitree_sdk2_python"):
        adapter.initialize()

    assert import_calls == ["unitree_sdk2py.core.channel"]


def test_adapter_uses_official_read_only_subscription_shape(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def channel_factory_initialize(domain: int, interface: str) -> None:
        calls["factory"] = (domain, interface)

    class FakeSubscriber:
        instance: "FakeSubscriber | None" = None

        def __init__(self, topic: str, message_type: object) -> None:
            calls["subscriber"] = (topic, message_type)
            self.handler = None
            FakeSubscriber.instance = self

        def Init(self, handler, queue_length: int) -> None:
            self.handler = handler
            calls["init"] = queue_length

        def Close(self) -> None:
            calls["closed"] = True

    package = types.ModuleType("unitree_sdk2py")
    core = types.ModuleType("unitree_sdk2py.core")
    channel = types.ModuleType("unitree_sdk2py.core.channel")
    channel.ChannelFactoryInitialize = channel_factory_initialize
    channel.ChannelSubscriber = FakeSubscriber
    idl = types.ModuleType("unitree_sdk2py.idl")
    unitree_go = types.ModuleType("unitree_sdk2py.idl.unitree_go")
    msg = types.ModuleType("unitree_sdk2py.idl.unitree_go.msg")
    dds = types.ModuleType("unitree_sdk2py.idl.unitree_go.msg.dds_")

    class LowState:
        power_v = 24.0
        power_a = 1.0

        class bms_state:
            soc = 72

    dds.LowState_ = LowState
    modules = {
        "unitree_sdk2py": package,
        "unitree_sdk2py.core": core,
        "unitree_sdk2py.core.channel": channel,
        "unitree_sdk2py.idl": idl,
        "unitree_sdk2py.idl.unitree_go": unitree_go,
        "unitree_sdk2py.idl.unitree_go.msg": msg,
        "unitree_sdk2py.idl.unitree_go.msg.dds_": dds,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    adapter = UnitreeGo2Adapter(unitree_config())
    adapter.initialize()
    assert calls["factory"] == (0, "enp2s0")
    assert calls["subscriber"] == ("rt/lowstate", LowState)
    assert calls["init"] == 10
    assert adapter.status().connection_status == "OFFLINE"

    assert FakeSubscriber.instance is not None
    assert FakeSubscriber.instance.handler is not None
    FakeSubscriber.instance.handler(LowState())

    status = adapter.status()
    assert status.connection_status == "ONLINE"
    assert status.operational_status == "UNAVAILABLE"
    assert status.battery_percent == 72
    assert status.current_execution_id is None
    assert adapter.capabilities() == ("TELEMETRY",)

    adapter.shutdown()
    assert calls["closed"] is True


def test_adapter_retains_snapshot_and_fails_closed_when_telemetry_is_stale(monkeypatch) -> None:
    clock = [100.0]
    received_at = datetime(2026, 10, 16, tzinfo=UTC)

    class FakeSubscriber:
        instance: "FakeSubscriber | None" = None

        def __init__(self, _topic: str, _message_type: object) -> None:
            self.handler = None
            FakeSubscriber.instance = self

        def Init(self, handler, _queue_length: int) -> None:
            self.handler = handler

    class LowState:
        class bms_state:
            soc = 100

    monkeypatch.setattr(
        "poppy_agent.robot.unitree._load_sdk",
        lambda: (lambda _domain, _interface: None, FakeSubscriber, LowState),
    )
    adapter = UnitreeGo2Adapter(
        unitree_config(),
        monotonic_clock=lambda: clock[0],
        utcnow=lambda: received_at,
    )
    adapter.initialize()
    assert FakeSubscriber.instance is not None
    assert FakeSubscriber.instance.handler is not None

    FakeSubscriber.instance.handler(LowState())
    snapshot = adapter.telemetry_snapshot()
    assert snapshot is not None
    assert snapshot.received_at == received_at
    assert snapshot.battery_percent == 100
    assert snapshot.mode is None
    assert adapter.status().connection_status == "ONLINE"
    assert adapter.status().battery_percent == 100

    clock[0] += 5.01
    stale_status = adapter.status()
    assert stale_status.connection_status == "OFFLINE"
    assert stale_status.battery_percent is None
    assert stale_status.operational_status == "UNAVAILABLE"


@pytest.mark.parametrize("state_of_charge", [-1, 101, "75", True, None])
def test_adapter_rejects_malformed_or_unverified_battery_values(
    monkeypatch, state_of_charge: object
) -> None:
    class FakeSubscriber:
        instance: "FakeSubscriber | None" = None

        def __init__(self, _topic: str, _message_type: object) -> None:
            self.handler = None
            FakeSubscriber.instance = self

        def Init(self, handler, _queue_length: int) -> None:
            self.handler = handler

    class LowState:
        class bms_state:
            soc = state_of_charge

    monkeypatch.setattr(
        "poppy_agent.robot.unitree._load_sdk",
        lambda: (lambda _domain, _interface: None, FakeSubscriber, LowState),
    )
    adapter = UnitreeGo2Adapter(unitree_config())
    adapter.initialize()
    assert FakeSubscriber.instance is not None
    assert FakeSubscriber.instance.handler is not None
    FakeSubscriber.instance.handler(LowState())

    assert adapter.status().connection_status == "ONLINE"
    assert adapter.status().battery_percent is None
    assert adapter.telemetry_snapshot() is not None
    assert adapter.telemetry_snapshot().battery_percent is None


def test_unitree_config_requires_positive_explicit_stale_timeout() -> None:
    identity = unitree_config().identity
    with pytest.raises(ValueError, match="must be explicit"):
        UnitreeGo2Config(network_interface="enp2s0", identity=identity)
    for invalid_timeout in (0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="must be positive and finite"):
            UnitreeGo2Config(
                network_interface="enp2s0",
                identity=identity,
                telemetry_stale_timeout_seconds=invalid_timeout,
            )


def test_adapter_ignores_late_callback_after_shutdown_and_resets_on_reinitialize(
    monkeypatch,
) -> None:
    subscribers: list[object] = []

    class FakeSubscriber:
        def __init__(self, _topic: str, _message_type: object) -> None:
            self.handler = None
            self.closed = False
            subscribers.append(self)

        def Init(self, handler, _queue_length: int) -> None:
            self.handler = handler

        def Close(self) -> None:
            self.closed = True

    class LowState:
        class bms_state:
            soc = 55

    monkeypatch.setattr(
        "poppy_agent.robot.unitree._load_sdk",
        lambda: (lambda _domain, _interface: None, FakeSubscriber, LowState),
    )
    adapter = UnitreeGo2Adapter(unitree_config())
    adapter.initialize()
    first_subscriber = subscribers[0]
    assert isinstance(first_subscriber, FakeSubscriber)
    assert first_subscriber.handler is not None
    first_subscriber.handler(LowState())
    assert adapter.status().connection_status == "ONLINE"

    adapter.shutdown()
    assert first_subscriber.closed is True
    first_subscriber.handler(LowState())
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.status()

    adapter.initialize()
    assert len(subscribers) == 2
    assert adapter.status().connection_status == "OFFLINE"


def test_adapter_cleans_up_when_subscription_initialization_fails(monkeypatch) -> None:
    class FailingSubscriber:
        closed = False

        def __init__(self, _topic: str, _message_type: object) -> None:
            pass

        def Init(self, _handler, _queue_length: int) -> None:
            raise RuntimeError("subscription init failed")

        def Close(self) -> None:
            type(self).closed = True

    monkeypatch.setattr(
        "poppy_agent.robot.unitree._load_sdk",
        lambda: (lambda _domain, _interface: None, FailingSubscriber, object),
    )
    adapter = UnitreeGo2Adapter(unitree_config())
    with pytest.raises(RuntimeError, match="subscription init failed"):
        adapter.initialize()
    assert FailingSubscriber.closed is True
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter.status()
