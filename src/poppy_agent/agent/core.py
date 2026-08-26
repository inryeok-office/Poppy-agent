"""Agent lifecycle independent of any concrete robot SDK."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from poppy_agent.config import AgentConfig
from poppy_agent.robot import (
    MockRobotAdapter,
    MockRobotSpec,
    RobotAdapter,
    RobotIdentity,
    RobotStatus,
    UnitreeGo2Adapter,
    UnitreeGo2Config,
)


class AgentState(StrEnum):
    """Lifecycle state of an Agent instance."""

    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"


class AgentLifecycleError(RuntimeError):
    """Raised when an Agent lifecycle transition is invalid."""


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    """Identity, state, and confirmed capabilities captured at startup."""

    identity: RobotIdentity
    status: RobotStatus
    capabilities: tuple[str, ...]


class Agent:
    """Coordinate startup and shutdown around a RobotAdapter."""

    def __init__(self, config: AgentConfig, adapter: RobotAdapter) -> None:
        self.config = config
        self.adapter = adapter
        self.state = AgentState.CREATED
        self.snapshot: AgentSnapshot | None = None

    def start(self) -> AgentSnapshot:
        """Initialize the adapter and capture its initial read-only state."""
        if self.state is not AgentState.CREATED:
            raise AgentLifecycleError(f"cannot start Agent from state {self.state}")

        self.adapter.initialize()
        self.snapshot = self.read_state()
        self.state = AgentState.RUNNING
        return self.snapshot

    def read_state(self) -> AgentSnapshot:
        """Read and retain the current read-only adapter state."""
        if self.state is not AgentState.RUNNING and self.state is not AgentState.CREATED:
            raise AgentLifecycleError(f"cannot read Agent state from state {self.state}")
        self.snapshot = AgentSnapshot(
            identity=self.adapter.identity(),
            status=self.adapter.status(),
            capabilities=self.adapter.capabilities(),
        )
        return self.snapshot

    def shutdown(self) -> None:
        """Stop the Agent and release adapter resources idempotently."""
        if self.state is AgentState.STOPPED:
            return
        if self.state is AgentState.RUNNING:
            self.adapter.shutdown()
        self.state = AgentState.STOPPED


def create_agent(config: AgentConfig) -> Agent:
    """Create the adapter selected by validated Phase 2 configuration."""
    if config.robot_mode == "unitree":
        required = (
            config.network_interface,
            config.robot_model,
            config.robot_edition,
            config.robot_firmware_version,
            config.unitree_sdk_version,
        )
        if any(value is None for value in required):
            raise ValueError("Unitree Agent configuration is incomplete")
        assert config.network_interface is not None
        assert config.robot_model is not None
        assert config.robot_edition is not None
        assert config.robot_firmware_version is not None
        assert config.unitree_sdk_version is not None
        identity = RobotIdentity(
            robot_id=config.robot_id,
            model=config.robot_model,
            edition=config.robot_edition,
            firmware_version=config.robot_firmware_version,
            sdk_version=config.unitree_sdk_version,
        )
        return Agent(
            config=config,
            adapter=UnitreeGo2Adapter(
                UnitreeGo2Config(network_interface=config.network_interface, identity=identity)
            ),
        )
    if config.robot_mode != "mock":
        raise ValueError(f"unsupported robot mode: {config.robot_mode}")
    return Agent(config=config, adapter=MockRobotAdapter(MockRobotSpec(robot_id=config.robot_id)))
