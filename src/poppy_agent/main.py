"""Production entry point for the Poppy-Agent runtime."""

from __future__ import annotations

import signal
import sys
from signal import Signals
from threading import Event
from types import FrameType

from poppy_agent.agent import create_agent
from poppy_agent.config import AgentConfig, ConfigurationError
from poppy_agent.server import (
    AgentServerRuntime,
    AgentServerRuntimeError,
    ServerClient,
    ServerClientError,
    ServerConfig,
    ServerConfigurationError,
)


def register_signal_handlers(stop_event: Event) -> None:
    """Arrange for supported process signals to request a graceful stop."""

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(Signals.SIGINT, request_stop)
    signal.signal(Signals.SIGTERM, request_stop)


def main() -> int:
    """Run the Agent registration and heartbeat lifecycle."""
    runtime: AgentServerRuntime | None = None

    try:
        agent_config = AgentConfig.from_environment()
        server_config = ServerConfig.from_environment()
        agent = create_agent(agent_config)
        server = ServerClient(server_config)
        runtime = AgentServerRuntime(agent, server, server_config)

        stop_event = Event()
        register_signal_handlers(stop_event)

        registration = runtime.start()
        print(f"Agent registered: {registration.agent_id}")
        print("Heartbeat loop started")
        runtime.run_heartbeat_loop(stop_event)
        return 0
    except (ConfigurationError, ServerConfigurationError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except (AgentServerRuntimeError, ServerClientError, ValueError) as exc:
        print(f"Poppy-Agent failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Poppy-Agent failed due to an unexpected runtime error", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            runtime.shutdown()
            print("Agent stopped")


if __name__ == "__main__":
    raise SystemExit(main())
