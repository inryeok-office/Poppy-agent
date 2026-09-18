"""Production entry point for the Poppy-Agent runtime."""

from __future__ import annotations

import logging
import signal
import sys
from signal import Signals
from threading import Event
from types import FrameType
from uuid import UUID

from poppy_agent.agent import create_agent
from poppy_agent.config import AgentConfig, ConfigurationError
from poppy_agent.execution import MockExecutionExecutor, PhysicalExecutionBlockedError
from poppy_agent.hardware import create_unitree_execution_executor
from poppy_agent.observability import (
    STARTUP_FAILURE,
    configure_logging,
    log_event,
    safe_exception_type,
)
from poppy_agent.server import (
    AgentServerRuntime,
    AgentServerRuntimeError,
    ServerClient,
    ServerClientError,
    ServerConfig,
    ServerConfigurationError,
)

logger = logging.getLogger(__name__)


def register_signal_handlers(stop_event: Event) -> None:
    """Arrange for supported process signals to request a graceful stop."""

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(Signals.SIGINT, request_stop)
    signal.signal(Signals.SIGTERM, request_stop)


def main() -> int:
    """Run the Agent registration and heartbeat lifecycle."""
    runtime: AgentServerRuntime | None = None
    executor: object | None = None
    configure_logging()

    try:
        agent_config = AgentConfig.from_environment()
        server_config = ServerConfig.from_environment()
        agent = create_agent(agent_config)
        server = ServerClient(server_config)
        runtime = AgentServerRuntime(agent, server, server_config)
        executor = _create_executor(agent_config)

        stop_event = Event()
        register_signal_handlers(stop_event)

        runtime.start()
        if executor is None:
            runtime.run_heartbeat_loop(stop_event)
        else:
            runtime.run_loop(stop_event, executor)
        return 0
    except (ConfigurationError, ServerConfigurationError) as exc:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type=safe_exception_type(exc))
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except PhysicalExecutionBlockedError as exc:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type=safe_exception_type(exc))
        print(f"Poppy-Agent physical execution is blocked: {exc}", file=sys.stderr)
        return 1
    except (AgentServerRuntimeError, ServerClientError, ValueError) as exc:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type=safe_exception_type(exc))
        print(f"Poppy-Agent failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type="UnexpectedError")
        print("Poppy-Agent failed due to an unexpected runtime error", file=sys.stderr)
        return 1
    finally:
        try:
            if runtime is not None:
                runtime.shutdown()
        finally:
            if executor is not None:
                shutdown = getattr(executor, "shutdown", None)
                if callable(shutdown):
                    shutdown()


def _create_executor(config: AgentConfig) -> MockExecutionExecutor | None:
    if getattr(config, "robot_mode", None) != "mock":
        if getattr(config, "enable_physical_execution", False):
            raw_robot_id = getattr(config, "robot_id", None)
            if not isinstance(raw_robot_id, str):
                raise ValueError("Unitree physical execution requires a valid Robot ID")
            return create_unitree_execution_executor(
                robot_id=UUID(raw_robot_id),
                physical_execution_enabled=True,
                network_interface=getattr(config, "network_interface", None),
            )
        return None
    raw_robot_id = getattr(config, "robot_id", None)
    bound_robot_id = UUID(raw_robot_id) if isinstance(raw_robot_id, str) else None
    return MockExecutionExecutor(bound_robot_id=bound_robot_id)


if __name__ == "__main__":
    raise SystemExit(main())
