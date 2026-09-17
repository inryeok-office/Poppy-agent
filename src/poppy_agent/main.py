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
from poppy_agent.execution import MockExecutionExecutor
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
    configure_logging()

    try:
        agent_config = AgentConfig.from_environment()
        server_config = ServerConfig.from_environment()
        agent = create_agent(agent_config)
        server = ServerClient(server_config)
        runtime = AgentServerRuntime(agent, server, server_config)
        executor = _create_mock_executor(agent_config)

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
    except (AgentServerRuntimeError, ServerClientError, ValueError) as exc:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type=safe_exception_type(exc))
        print(f"Poppy-Agent failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type="UnexpectedError")
        print("Poppy-Agent failed due to an unexpected runtime error", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            runtime.shutdown()


def _create_mock_executor(config: AgentConfig) -> MockExecutionExecutor | None:
    if getattr(config, "robot_mode", None) != "mock":
        return None
    raw_robot_id = getattr(config, "robot_id", None)
    bound_robot_id = UUID(raw_robot_id) if isinstance(raw_robot_id, str) else None
    return MockExecutionExecutor(bound_robot_id=bound_robot_id)


if __name__ == "__main__":
    raise SystemExit(main())
