import sys
import types
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
    )


def test_sdk_unavailable_error_is_explicit() -> None:
    adapter = UnitreeGo2Adapter(unitree_config())
    with pytest.raises(UnitreeSdkUnavailableError, match="official unitree_sdk2_python"):
        adapter.initialize()


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
    assert status.battery_percent is None
    assert status.current_execution_id is None
    assert adapter.capabilities() == ("TELEMETRY",)

    adapter.shutdown()
    assert calls["closed"] is True
