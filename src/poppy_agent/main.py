"""Production entry point for the Poppy-Agent runtime."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Callable
from signal import Signals
from threading import Event
from types import FrameType
from uuid import UUID

from poppy_agent.agent import Agent, create_agent
from poppy_agent.config import AgentConfig, ConfigurationError, OpenMotionSettings
from poppy_agent.execution import MockExecutionExecutor, PhysicalExecutionBlockedError
from poppy_agent.hardware import create_controlled_trial_executor, create_open_motion_executor
from poppy_agent.observability import (
    PHYSICAL_EXECUTION_BLOCKED,
    PHYSICAL_EXECUTION_ENABLED,
    RUNTIME_SHUTDOWN_FAILED,
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
        if executor is None and getattr(agent_config, "robot_mode", None) == "unitree":
            executor = _create_physical_trial_executor(agent_config, agent, runtime)

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
            _shutdown_executor_safely(executor)


def _shutdown_executor_safely(executor: object | None) -> None:
    """Release executor resources without masking an earlier lifecycle result."""
    if executor is None:
        return
    shutdown = getattr(executor, "shutdown", None)
    if not callable(shutdown):
        return
    try:
        shutdown()
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            RUNTIME_SHUTDOWN_FAILED,
            error_type=safe_exception_type(exc),
        )


def _create_executor(config: AgentConfig) -> MockExecutionExecutor | None:
    if getattr(config, "robot_mode", None) != "mock":
        return None
    raw_robot_id = getattr(config, "robot_id", None)
    bound_robot_id = UUID(raw_robot_id) if isinstance(raw_robot_id, str) else None
    return MockExecutionExecutor(bound_robot_id=bound_robot_id)


def _create_physical_trial_executor(
    config: AgentConfig, agent: Agent, runtime: AgentServerRuntime
) -> MockExecutionExecutor | None:
    """Return the controlled TURN trial executor, or ``None`` for heartbeat-only.

    A blocked physical runtime never exits: it keeps heartbeating as
    UNAVAILABLE and publishes the blocking reasons locally.
    """
    adapter = agent.adapter
    telemetry_fresh = getattr(adapter, "telemetry_is_fresh", None)
    set_command_readiness = getattr(adapter, "set_command_readiness", None)
    if not config.enable_physical_execution:
        _publish_blocked(runtime, config, ("PHYSICAL_EXECUTION_DISABLED",))
        return None
    if not callable(telemetry_fresh) or not callable(set_command_readiness):
        _publish_blocked(runtime, config, ("ROBOT_ADAPTER_UNSUPPORTED",))
        return None
    if isinstance(config.physical_trial, OpenMotionSettings):
        return _create_open_motion_executor(
            config, config.physical_trial, runtime, telemetry_fresh, set_command_readiness
        )
    try:
        trial = create_controlled_trial_executor(
            robot_id=UUID(config.robot_id),
            physical_execution_enabled=True,
            trial_settings=config.physical_trial
            if not isinstance(config.physical_trial, OpenMotionSettings)
            else None,
            telemetry_fresh=telemetry_fresh,
            network_interface=config.network_interface,
        )
    except PhysicalExecutionBlockedError as exc:
        reasons = str(exc).split(": ", 1)[-1].split(", ")
        if config.physical_trial is None:
            reasons.insert(0, "TRIAL_CONFIGURATION_INVALID")
        _publish_blocked(runtime, config, tuple(reasons))
        return None
    except Exception as exc:
        _publish_blocked(
            runtime,
            config,
            (f"SDK_COMMAND_CLIENT_INITIALIZATION_FAILED:{safe_exception_type(exc)}",),
        )
        return None

    guard = trial.guard
    settings = guard.settings

    def command_ready() -> bool:
        return guard.available() and runtime.active_execution_id is None

    def physical_status() -> dict[str, object]:
        ready = command_ready() and telemetry_fresh() is True
        return {
            "enabled": True,
            "state": "READY" if ready else "NOT_READY",
            "reasons": [],
            "configIssues": [],
            "mode": settings.mode,
            "turnRateDegreesPerSecond": settings.turn_rate_degrees_per_second,
            "maxTurnDegreesPerCommand": settings.max_turn_degrees_per_command,
            "turnLeftYawSign": settings.turn_left_yaw_sign,
            "trial": guard.snapshot().to_dict(),
        }

    set_command_readiness(command_ready)
    runtime.set_physical_execution_status(physical_status)
    log_event(
        logger,
        logging.WARNING,
        PHYSICAL_EXECUTION_ENABLED,
        trial_commands_max=settings.max_commands,
        approval_ref=settings.approval_ref,
    )
    return trial.executor


def _create_open_motion_executor(
    config: AgentConfig,
    settings: OpenMotionSettings,
    runtime: AgentServerRuntime,
    telemetry_fresh: Callable[[], bool],
    set_command_readiness: Callable[[Callable[[], bool]], None],
) -> MockExecutionExecutor | None:
    """Return the ``controlled_motion_open`` executor, or ``None`` for heartbeat-only."""
    try:
        trial = create_open_motion_executor(
            robot_id=UUID(config.robot_id),
            physical_execution_enabled=True,
            settings=settings,
            telemetry_fresh=telemetry_fresh,
            network_interface=config.network_interface,
        )
    except PhysicalExecutionBlockedError as exc:
        _publish_blocked(runtime, config, tuple(str(exc).split(": ", 1)[-1].split(", ")))
        return None
    except Exception as exc:
        _publish_blocked(
            runtime,
            config,
            (f"SDK_COMMAND_CLIENT_INITIALIZATION_FAILED:{safe_exception_type(exc)}",),
        )
        return None

    guard = trial.guard

    def command_ready() -> bool:
        return guard.available() and runtime.active_execution_id is None

    def physical_status() -> dict[str, object]:
        if guard.expired():
            return {
                "enabled": True,
                "state": "BLOCKED",
                "reasons": ["TRIAL_EXPIRED"],
                "configIssues": [],
                "mode": settings.mode,
                "trial": guard.snapshot(),
            }
        ready = command_ready() and telemetry_fresh() is True
        return {
            "enabled": True,
            "state": "READY" if ready else "NOT_READY",
            "reasons": [],
            "configIssues": [],
            "mode": settings.mode,
            "linearSpeedMetersPerSecond": settings.linear_speed_meters_per_second,
            "maxMoveMetersPerCommand": settings.max_move_meters_per_command,
            "maxTotalMoveMeters": settings.max_total_move_meters,
            "turnRateDegreesPerSecond": settings.turn_rate_degrees_per_second,
            "maxTurnDegreesPerCommand": settings.max_turn_degrees_per_command,
            "maxTotalSeconds": settings.max_total_seconds,
            "postureSettleSeconds": settings.posture_settle_seconds,
            "presetSettleSeconds": settings.preset_settle_seconds,
            "allowedCommands": sorted(settings.allowed_commands),
            "allowedPresets": sorted(settings.allowed_presets),
            "turnLeftYawSign": settings.turn_left_yaw_sign,
            "trial": guard.snapshot(),
        }

    set_command_readiness(command_ready)
    runtime.set_physical_execution_status(physical_status)
    log_event(
        logger,
        logging.WARNING,
        PHYSICAL_EXECUTION_ENABLED,
        trial_mode=settings.mode,
        expires_at=settings.expires_at.isoformat(),
        approval_ref=settings.approval_ref,
    )
    return trial.executor


def _publish_blocked(
    runtime: AgentServerRuntime, config: AgentConfig, reasons: tuple[str, ...]
) -> None:
    issues = list(config.physical_trial_issues)
    runtime.set_physical_execution_status(
        lambda: {
            "enabled": config.enable_physical_execution,
            "state": "BLOCKED",
            "reasons": list(reasons),
            "configIssues": issues,
        }
    )
    log_event(
        logger,
        logging.WARNING,
        PHYSICAL_EXECUTION_BLOCKED,
        blocked_reasons=",".join(reasons),
    )
    for issue in issues:
        log_event(logger, logging.WARNING, PHYSICAL_EXECUTION_BLOCKED, blocked_reasons=issue)


if __name__ == "__main__":
    raise SystemExit(main())
